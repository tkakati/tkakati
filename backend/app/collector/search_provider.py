from datetime import UTC, datetime
from typing import Any

import httpx
from tenacity import Retrying, stop_after_attempt, wait_exponential

from app.collector.company_extractor import CompanyExtractor
from app.config import Settings


class SearchProvider:
    """Collect LinkedIn hiring post candidates using Serper Google Search API."""

    BASE_URL = "https://google.serper.dev/search"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.company_extractor = CompanyExtractor(settings)

    def fetch(self, role_query: str, *, days_back: int | None = None, location: str | None = None) -> list[dict]:
        now = datetime.now(tz=UTC)
        max_days = days_back if days_back is not None else self.settings.collector_days_back
        results: list[dict] = []
        hits, _ = self._search_hits(role_query, days_back=days_back, location=location)

        for hit in hits:
            title = hit["title"]
            link = hit["url"]
            description = hit["snippet"]
            text = f"{title} {description}".strip()

            if _contains_block_term(title, self.settings.blocked_terms):
                continue
            if not _is_linkedin_post_url(link):
                continue
            if not _contains_hiring_term(text, self.settings.hiring_terms):
                continue

            # Serper results don't provide stable per-item publish timestamp.
            first_seen = now
            if (now - first_seen).days > max_days:
                continue

            normalized_title = _strip_linkedin_suffix(title)
            metadata = self.company_extractor.extract_metadata(normalized_title, link, description)
            results.append(
                {
                    "post_url": link,
                    "title": normalized_title,
                    "company": metadata.company or None,
                    "seniority": metadata.seniority or None,
                    "location": metadata.location or None,
                    "remote": metadata.remote,
                    "query_used": role_query,
                    "first_seen": first_seen,
                }
            )

        return results

    def debug_preview(
        self,
        role_query: str,
        *,
        days_back: int | None = None,
        location: str | None = None,
        limit: int = 50,
    ) -> dict:
        hits, errors = self._search_hits(role_query, days_back=days_back, location=location)
        items: list[dict] = []
        for hit in hits[:limit]:
            title = hit["title"]
            snippet = hit["snippet"]
            url = hit["url"]
            text = f"{title} {snippet}".strip()
            items.append(
                {
                    "search_query": hit.get("search_query", ""),
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "is_linkedin": "linkedin.com" in _netloc(url),
                    "has_hiring_term": _contains_hiring_term(text, self.settings.hiring_terms),
                    "is_blocked": _contains_block_term(title, self.settings.blocked_terms),
                }
            )
        return {
            "designation": role_query,
            "location": location or "",
            "total_raw": len(hits),
            "returned": len(items),
            "errors": errors,
            "items": items,
        }

    def _search_hits(
        self, role_query: str, *, days_back: int | None, location: str | None
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        hits: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        for search_query in self._build_search_queries(role_query, location=location):
            try:
                rows = self._serper_search(search_query, days_back=days_back)
            except Exception as exc:  # noqa: BLE001
                errors.append({"search_query": search_query, "error": str(exc)})
                continue

            for row in rows:
                link = row.get("url") or ""
                if not link or link in seen_urls:
                    continue
                row["search_query"] = search_query
                hits.append(row)
                seen_urls.add(link)

        return hits, errors

    def _serper_search(self, search_query: str, *, days_back: int | None = None) -> list[dict[str, str]]:
        if not self.settings.serper_api_key:
            raise RuntimeError("serper_api_key is not configured")

        max_rows = max(1, min(self.settings.serper_results_per_query, 100))
        collected: list[dict[str, str]] = []

        page = 1
        while len(collected) < max_rows and page <= 10:
            batch = min(100, max_rows - len(collected))
            payload = self._fetch_serper_page(search_query, page=page, num=batch, days_back=days_back)
            items = payload.get("organic", [])
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                link = str(item.get("link") or item.get("url") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                if not title or not link:
                    continue
                collected.append({"title": title, "url": link, "snippet": snippet})

            if len(items) < min(10, batch):
                break
            page += 1

        return collected

    def _fetch_serper_page(self, search_query: str, *, page: int, num: int, days_back: int | None = None) -> dict[str, Any]:
        retries = max(1, self.settings.collector_max_retries)
        data: dict[str, Any] = {}
        for attempt in Retrying(
            wait=wait_exponential(min=1, max=8),
            stop=stop_after_attempt(retries),
            reraise=True,
        ):
            with attempt:
                with httpx.Client(timeout=self.settings.collector_timeout_seconds) as client:
                    payload: dict[str, Any] = {
                        "q": search_query,
                        "num": num,
                        "page": page,
                        "hl": "en",
                        "gl": "us",
                    }
                    if days_back and days_back > 0:
                        payload["tbs"] = _serper_tbs(days_back)
                    response = client.post(
                        self.BASE_URL,
                        headers={
                            "X-API-KEY": self.settings.serper_api_key,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    parsed = response.json()
                    if not isinstance(parsed, dict):
                        raise RuntimeError("Invalid Serper response")
                    data = parsed
        return data

    def _build_search_queries(self, role_query: str, *, location: str | None = None) -> list[str]:
        queries: list[str] = []
        location_part = f' "{location.strip()}"' if location and location.strip() else ""
        queries.append(f'site:linkedin.com/posts "{role_query}" hiring{location_part}')
        queries.append(f'site:linkedin.com/feed/update "{role_query}" hiring{location_part}')
        queries.append(f'site:linkedin.com "{role_query}" hiring{location_part}')
        queries.append(f'site:linkedin.com/posts "{role_query}"{location_part}')
        queries.append(f'site:linkedin.com/feed/update "{role_query}"{location_part}')
        queries.append(f'site:linkedin.com "{role_query}"{location_part}')
        return queries


def _strip_linkedin_suffix(title: str) -> str:
    suffix = " - LinkedIn"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def _contains_block_term(text: str, blocked_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in blocked_terms)


def _contains_hiring_term(text: str, hiring_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in hiring_terms)


def _serper_tbs(days_back: int) -> str:
    if days_back <= 1:
        return "qdr:d"
    if days_back <= 30:
        return "qdr:w" if days_back <= 7 else "qdr:m"
    if days_back <= 180:
        return "qdr:m"
    return "qdr:y"


def _netloc(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""


def _is_linkedin_post_url(url: str) -> bool:
    try:
        parsed = httpx.URL(url)
        host = (parsed.host or "").lower()
        if "linkedin.com" not in host:
            return False
        path = (parsed.path or "").lower()
        return "/posts/" in path or path.startswith("/feed/update/")
    except Exception:
        return False
