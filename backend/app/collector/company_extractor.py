import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from openai import OpenAI

from app.config import Settings


@dataclass
class JobMetadata:
    company: str
    seniority: str
    location: str
    remote: bool


BRAND_MAP = {
    "playstation": "PlayStation",
    "youtube": "YouTube",
    "instagram": "Instagram",
    "whatsapp": "WhatsApp",
    "prime": "Amazon",
    "aws": "Amazon",
    "meta": "Meta",
    "google": "Google",
    "microsoft": "Microsoft",
    "apple": "Apple",
    "netflix": "Netflix",
    "uber": "Uber",
    "airbnb": "Airbnb",
    "stripe": "Stripe",
    "nvidia": "NVIDIA",
    "tesla": "Tesla",
    "tiktok": "TikTok",
    "snapchat": "Snap",
}


@dataclass
class CompanyExtractor:
    settings: Settings

    def __post_init__(self) -> None:
        self._cache: dict[str, JobMetadata] = {}
        self._client: OpenAI | None = (
            OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None
        )

    def extract(self, title: str, url: str, description: str = "") -> str | None:
        metadata = self.extract_metadata(title, url, description)
        if metadata.company and metadata.company.lower() != "unknown":
            return metadata.company
        return None

    def extract_metadata(self, title: str, url: str, description: str = "") -> JobMetadata:
        key = f"{title.strip()}::{url.strip()}"
        if not key:
            return _fallback_metadata(title, url, description)
        if key in self._cache:
            return self._cache[key]

        # Fallback path when OpenAI is not configured.
        if self._client is None:
            value = _fallback_metadata(title, url, description)
            self._cache[key] = value
            return value

        value = self._extract_via_gpt(title, description, url)
        if value is None:
            value = _fallback_metadata(title, url, description)
        elif not value.company or value.company.lower() == "unknown":
            fallback = _fallback_metadata(title, url, description)
            value = JobMetadata(
                company=fallback.company,
                seniority=value.seniority,
                location=value.location,
                remote=value.remote,
            )
        self._cache[key] = value
        return value

    def _extract_via_gpt(self, title: str, description: str = "", url: str = "") -> JobMetadata | None:
        if self._client is None:
            return None
        try:
            company = _extract_company_best(self._client, self.settings.openai_company_model, title, description, url)
        except Exception:
            return None

        lowered = f"{title} {description}".lower()
        return JobMetadata(
            company=company if company != "Unknown" else "",
            seniority=_heuristic_seniority(lowered),
            location=_heuristic_location(title),
            remote=("remote" in lowered) or ("work from home" in lowered),
        )


def _extract_response_text(response: object) -> str | None:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return None

    parts: list[str] = []
    for block in output:
        content = getattr(block, "content", None)
        if not isinstance(content, list):
            continue
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip() or None


def _parse_metadata(text: str) -> JobMetadata | None:
    normalized = text.strip()
    if not normalized:
        return None

    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    company = str(payload.get("company") or "").strip()
    seniority = str(payload.get("seniority") or "").strip()
    location = str(payload.get("location") or "").strip()
    remote_raw = payload.get("remote")
    remote = _coerce_remote(remote_raw)
    return JobMetadata(
        company=company[:120],
        seniority=seniority[:120],
        location=location[:120],
        remote=remote,
    )


def _coerce_remote(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "remote", "hybrid"}:
            return True
        if lowered in {"false", "no", "onsite", "on-site"}:
            return False
    return False


def _heuristic_company(title: str) -> str | None:
    lowered = title.lower()
    at_match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&().,' -]{1,60})", title)
    if at_match:
        candidate = _normalize_company_candidate(at_match.group(1))
        if candidate:
            return candidate

    if title.lower().endswith("linkedin"):
        return None

    # Common structure: "<company> is hiring ..."
    for marker in [" is hiring", " hiring:", " we are hiring"]:
        idx = lowered.find(marker)
        if idx > 0:
            candidate = _normalize_company_candidate(title[:idx].strip(" -|:"))
            if candidate:
                return candidate

    return None


def _fallback_company_from_url(url: str) -> str | None:
    try:
        host = (urlparse(url).netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return None
        base = host.split(".")[0].strip()
        if not base:
            return None
        # Avoid returning news/google wrapper hosts as companies.
        if base in {"news", "google", "linkedin"}:
            return None
        return base.capitalize()
    except Exception:
        return None


def _fallback_metadata(title: str, url: str, description: str = "") -> JobMetadata:
    lowered = title.lower()
    return JobMetadata(
        company=(
            _rule_based_company(f"{title} {description}")
            or _heuristic_company(title)
            or _fallback_company_from_url(url)
            or ""
        ),
        seniority=_heuristic_seniority(lowered),
        location=_heuristic_location(title),
        remote=("remote" in lowered) or ("work from home" in lowered),
    )


def _heuristic_seniority(lowered_title: str) -> str:
    if "senior" in lowered_title:
        return "senior"
    if "lead" in lowered_title:
        return "lead"
    if "principal" in lowered_title:
        return "principal"
    if "staff" in lowered_title:
        return "staff"
    return ""


def _heuristic_location(title: str) -> str:
    # Keep location blank unless explicitly present in common form "(Location)".
    start = title.rfind("(")
    end = title.rfind(")")
    if 0 <= start < end:
        candidate = title[start + 1 : end].strip()
        if 2 <= len(candidate) <= 80:
            return candidate
    return ""


def _rule_based_company(text: str) -> str | None:
    text_lower = text.lower()
    for key, value in BRAND_MAP.items():
        if key in text_lower:
            return value
    return None


def _llm_extract_company(client: OpenAI, model: str, title: str, description: str = "") -> str:
    prompt = f"""
You are an expert recruiter and hiring intelligence system.

Extract the COMPANY or BRAND from the following LinkedIn hiring post.

Important:
1. The company may be implicit.
2. Use product names, brand names, or ecosystem clues.
3. Prefer the BRAND if that is what is referenced.
4. Examples:
   - PlayStation -> PlayStation
   - YouTube -> YouTube
   - Instagram -> Instagram
   - AWS -> Amazon
   - Prime Video -> Amazon
5. Do NOT explain.
6. Return ONLY the company or brand.
7. If unclear, return "Unknown".

Title:
{title}

Post:
{description}
"""

    response = client.responses.create(model=model, input=prompt)
    text = _extract_response_text(response)
    if not text:
        return "Unknown"
    value = text.strip().strip('"').strip("'")
    normalized = _normalize_company_candidate(value)
    return normalized or "Unknown"


def _domain_fallback(url: str) -> str:
    try:
        domain = urlparse(url).netloc or ""
        base = domain.replace("www.", "").split(".")[0].strip()
        return base.capitalize() if base else "Unknown"
    except Exception:
        return "Unknown"


def _extract_company_best(client: OpenAI, model: str, title: str, description: str = "", url: str = "") -> str:
    company = _rule_based_company(f"{title} {description}")
    if company:
        return company

    company = _llm_extract_company(client, model, title, description)
    if company and company != "Unknown":
        return company

    if url:
        return _domain_fallback(url)
    return "Unknown"


def _normalize_company_candidate(value: str) -> str | None:
    if not value:
        return None

    candidate = value.strip().splitlines()[0].strip().strip(" .,:;!-|")
    if not candidate:
        return None

    lowered = candidate.lower()
    if lowered in {"unknown", "n/a", "none", "na"}:
        return None

    banned_prefixes = (
        "we are",
        "we're",
        "hiring",
        "looking for",
        "join our",
        "urgent",
        "opportunity",
        "20+",
    )
    if lowered.startswith(banned_prefixes):
        return None

    banned_terms = (
        "product manager",
        "product marketing manager",
        "program manager",
        "senior product manager",
        "hiring list",
        "job opening",
        "vacancy",
        "careers",
    )
    if any(term in lowered for term in banned_terms):
        return None

    if "http://" in lowered or "https://" in lowered:
        return None

    words = candidate.split()
    if len(words) > 5:
        return None
    if len(candidate) > 48:
        return None

    if re.search(r"[!?]{2,}", candidate):
        return None

    alias = _rule_based_company(candidate)
    if alias:
        return alias
    return candidate
