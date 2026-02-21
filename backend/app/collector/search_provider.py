from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse
import xml.etree.ElementTree as ET

import httpx
from tenacity import Retrying, stop_after_attempt, wait_exponential

from app.collector.company_extractor import CompanyExtractor
from app.config import Settings


class SearchProvider:
    """Collect LinkedIn hiring post candidates from Google News RSS search."""

    BASE_URL = "https://news.google.com/rss/search"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.company_extractor = CompanyExtractor(settings)

    def fetch(self, role_query: str, *, days_back: int | None = None, location: str | None = None) -> list[dict]:
        search_query = self._build_search_query(role_query, location=location)
        payload = self._fetch_rss(search_query)

        now = datetime.now(tz=UTC)
        max_days = days_back if days_back is not None else self.settings.collector_days_back
        results: list[dict] = []
        root = ET.fromstring(payload)

        for item in root.findall("./channel/item"):
            source = (item.findtext("source") or "").strip().lower()
            if source != "linkedin":
                continue

            title = unescape((item.findtext("title") or "").strip())
            if not title:
                continue

            if not _matches_role(title, role_query):
                continue
            if not _is_hiring_language(title, self.settings.hiring_terms):
                continue
            if _contains_block_term(title, self.settings.blocked_terms):
                continue

            link = _extract_linkedin_url(item)
            if not link:
                continue
            description = _description_text(item)

            first_seen = _parse_pub_date(item.findtext("pubDate"))
            if first_seen is None:
                continue
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

    def _fetch_rss(self, search_query: str) -> str:
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
                        "hl": "en-US",
                        "gl": "US",
                        "ceid": "US:en",
                    }
                    url = f"{self.BASE_URL}?{urlencode(params)}"
                    response = client.get(url)
                    response.raise_for_status()
                    content = response.text
        return content

    def _build_search_query(self, role_query: str, *, location: str | None = None) -> str:
        hiring = " OR ".join(f'"{term}"' for term in self.settings.hiring_terms)
        if location and location.strip():
            return f'site:linkedin.com/posts ({hiring}) "{role_query}" "{location.strip()}"'
        return f'site:linkedin.com/posts ({hiring}) "{role_query}"'


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _strip_linkedin_suffix(title: str) -> str:
    suffix = " - LinkedIn"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def _matches_role(title: str, role_query: str) -> bool:
    return role_query.lower() in title.lower()


def _is_hiring_language(title: str, hiring_terms: list[str]) -> bool:
    lowered = title.lower()
    return any(term in lowered for term in hiring_terms)


def _contains_block_term(title: str, blocked_terms: list[str]) -> bool:
    lowered = title.lower()
    return any(term in lowered for term in blocked_terms)


LINKEDIN_URL_RE = re.compile(r"https?://(?:[\w-]+\.)?linkedin\.com/[^\s\"'<>]+", re.IGNORECASE)


def _extract_linkedin_url(item: ET.Element) -> str | None:
    direct_link = (item.findtext("link") or "").strip()
    candidate = _extract_linkedin_from_text(direct_link)
    if candidate:
        return candidate

    description = item.findtext("description") or ""
    candidate = _extract_linkedin_from_text(unescape(description))
    if candidate:
        return candidate

    guid = item.findtext("guid") or ""
    candidate = _extract_linkedin_from_text(guid)
    if candidate:
        return candidate
    return None


def _extract_linkedin_from_text(text: str) -> str | None:
    if not text:
        return None

    parsed = urlparse(text)
    if "linkedin.com" in parsed.netloc.lower():
        return text

    params = parse_qs(parsed.query)
    for key in ("url", "q"):
        for value in params.get(key, []):
            decoded = unquote(value).strip()
            parsed_decoded = urlparse(decoded)
            if "linkedin.com" in parsed_decoded.netloc.lower():
                return decoded

    match = LINKEDIN_URL_RE.search(text)
    if match:
        return unquote(match.group(0))
    return None


def _description_text(item: ET.Element) -> str:
    description = unescape(item.findtext("description") or "").strip()
    if not description:
        return ""
    return re.sub(r"<[^>]+>", " ", description)
