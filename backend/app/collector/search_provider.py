from datetime import UTC, datetime
from html import unescape
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import httpx
from tenacity import Retrying, stop_after_attempt, wait_exponential

from app.collector.company_extractor import CompanyExtractor
from app.config import Settings


class SearchProvider:
    """Collect LinkedIn hiring post candidates from DuckDuckGo web search."""

    BASE_URL = "https://html.duckduckgo.com/html/"
    LITE_URL = "https://lite.duckduckgo.com/lite/"

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

            if _contains_block_term(title, self.settings.blocked_terms):
                continue
            if "linkedin.com" not in urlparse(link).netloc.lower():
                continue

            # DDG results don't provide a reliable publish date per hit.
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
            netloc = urlparse(url).netloc.lower()
            items.append(
                {
                    "search_query": hit.get("search_query", ""),
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "is_linkedin": "linkedin.com" in netloc,
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
                payload = self._fetch_html(search_query, days_back=days_back)
                parsed = _parse_duckduckgo_results(payload)
            except Exception as exc:  # noqa: BLE001
                errors.append({"search_query": search_query, "error": str(exc)})
                continue
            for hit in parsed:
                link = hit["url"]
                if not link or link in seen_urls:
                    continue
                hit["search_query"] = search_query
                hits.append(hit)
                seen_urls.add(link)
        return hits, errors

    def _fetch_html(self, search_query: str, *, days_back: int | None = None) -> str:
        retries = max(1, self.settings.collector_max_retries)
        content = ""
        for attempt in Retrying(
            wait=wait_exponential(min=1, max=8),
            stop=stop_after_attempt(retries),
            reraise=True,
        ):
            with attempt:
                with httpx.Client(timeout=self.settings.collector_timeout_seconds) as client:
                    params = {
                        "q": search_query,
                        "kl": "us-en",
                        "df": _ddg_date_filter(days_back if days_back is not None else self.settings.collector_days_back),
                    }
                    response = client.get(
                        self.BASE_URL,
                        params=params,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/123.0.0.0 Safari/537.36"
                            )
                        },
                    )
                    response.raise_for_status()
                    content = response.text
                    if not _looks_like_search_results(content):
                        lite_response = client.get(
                            self.LITE_URL,
                            params={"q": search_query, "kl": "us-en"},
                            headers={
                                "User-Agent": (
                                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/123.0.0.0 Safari/537.36"
                                )
                            },
                        )
                        lite_response.raise_for_status()
                        content = lite_response.text
        return content

    def _build_search_queries(self, role_query: str, *, location: str | None = None) -> list[str]:
        queries: list[str] = []
        location_part = f' "{location.strip()}"' if location and location.strip() else ""
        # Keep searches broad enough to avoid empty result sets.
        queries.append(f'site:linkedin.com/posts "{role_query}" hiring{location_part}')
        queries.append(f'site:linkedin.com "{role_query}" hiring{location_part}')
        queries.append(f'site:linkedin.com/posts "{role_query}"{location_part}')
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


def _ddg_date_filter(days_back: int) -> str:
    if days_back <= 1:
        return "d"
    if days_back <= 7:
        return "w"
    if days_back <= 31:
        return "m"
    return "y"


def _parse_duckduckgo_results(payload: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    # Preferred selector when DDG serves classic markup.
    strict_pattern = re.compile(
        r'<a[^>]*class=(?:"[^"]*result__a[^"]*"|\'[^\']*result__a[^\']*\')[^>]*href=(?:"([^"]+)"|\'([^\']+)\')[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    # Fallback selector when class names/layout differ.
    loose_pattern = re.compile(
        r'<a[^>]*href=(?:"([^"]+)"|\'([^\']+)\')[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for pattern in (strict_pattern, loose_pattern):
        for match in pattern.finditer(payload):
            href_raw = unescape((match.group(1) or match.group(2) or "").strip())
            if not href_raw:
                continue
            title = _strip_tags(unescape(match.group(3))).strip()
            if not title or len(title) < 3:
                continue

            url = _resolve_duckduckgo_href(href_raw)
            if not url:
                continue

            snippet = ""
            tail = payload[match.end() : match.end() + 1400]
            snippet_match = re.search(
                r'class=(?:"[^"]*result__snippet[^"]*"|\'[^\']*result__snippet[^\']*\')[^>]*>(.*?)</',
                tail,
                re.IGNORECASE | re.DOTALL,
            )
            if snippet_match:
                snippet = _strip_tags(unescape(snippet_match.group(1))).strip()

            results.append({"url": url, "title": title, "snippet": snippet})
    return results


def _resolve_duckduckgo_href(href_raw: str) -> str | None:
    if not href_raw:
        return None
    href = href_raw.strip()
    if href.startswith("//"):
        href = f"https:{href}"
    if href.startswith("/"):
        href = f"https://duckduckgo.com{href}"

    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc.lower():
        params = parse_qs(parsed.query)
        for value in params.get("uddg", []):
            decoded = unquote(value).strip()
            if decoded:
                return decoded
        return None

    if parsed.scheme not in {"http", "https"}:
        return None
    return href


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)


def _contains_hiring_term(text: str, hiring_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in hiring_terms)


def _looks_like_search_results(payload: str) -> bool:
    return ("result__a" in payload) or ("result-link" in payload) or ("web-result" in payload)
