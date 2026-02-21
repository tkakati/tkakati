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

    def __init__(self, settings: Settings):
        self.settings = settings
        self.company_extractor = CompanyExtractor(settings)

    def fetch(self, role_query: str, *, days_back: int | None = None, location: str | None = None) -> list[dict]:
        search_query = self._build_search_query(role_query, location=location)
        payload = self._fetch_html(search_query, days_back=days_back)

        now = datetime.now(tz=UTC)
        max_days = days_back if days_back is not None else self.settings.collector_days_back
        results: list[dict] = []

        for hit in _parse_duckduckgo_results(payload):
            title = hit["title"]
            link = hit["url"]
            description = hit["snippet"]

            if _contains_block_term(title, self.settings.blocked_terms):
                continue
            if not _is_hiring_language(f"{title} {description}", self.settings.hiring_terms):
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
                    response = client.get(self.BASE_URL, params=params)
                    response.raise_for_status()
                    content = response.text
        return content

    def _build_search_query(self, role_query: str, *, location: str | None = None) -> str:
        hiring = " OR ".join(f'"{term}"' for term in self.settings.hiring_terms)
        if location and location.strip():
            return f'site:linkedin.com/posts ({hiring}) "{role_query}" "{location.strip()}"'
        return f'site:linkedin.com/posts ({hiring}) "{role_query}"'


def _strip_linkedin_suffix(title: str) -> str:
    suffix = " - LinkedIn"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def _contains_block_term(text: str, blocked_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in blocked_terms)


def _is_hiring_language(text: str, hiring_terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in hiring_terms)


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
    # DuckDuckGo HTML endpoint render.
    pattern = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(payload):
        href_raw = unescape(match.group(1)).strip()
        title_html = match.group(2)
        title = _strip_tags(unescape(title_html)).strip()
        if not title:
            continue
        url = _resolve_duckduckgo_href(href_raw)
        if not url:
            continue

        snippet = ""
        tail = payload[match.end() : match.end() + 1400]
        snippet_match = re.search(
            r'class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</',
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
    parsed = urlparse(href_raw)
    if "duckduckgo.com" in parsed.netloc.lower():
        params = parse_qs(parsed.query)
        for value in params.get("uddg", []):
            decoded = unquote(value).strip()
            if decoded:
                return decoded
    return href_raw


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value)
