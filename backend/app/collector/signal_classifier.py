import asyncio
import difflib
import json
import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.collector.company_signal_extractor import CompanyExtractionResult, CompanySignalExtractor
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class SignalClassification:
    company: str
    role: str
    seniority: str
    is_hiring: bool
    signal_strength: int
    signal_type: str
    confidence: float
    reasoning: str
    hiring_confidence: float = 0.0
    role_match_score: float = 0.0
    company_confidence: float = 0.0
    company_source: str = "llm"


class SignalClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )
        self._cache: dict[str, SignalClassification] = {}
        self._company_extractor = CompanySignalExtractor()

    def classify_many_sync(self, rows: list[dict]) -> list[SignalClassification]:
        if not rows:
            return []
        return asyncio.run(self.classify_many(rows))

    async def classify_many(self, rows: list[dict]) -> list[SignalClassification]:
        semaphore = asyncio.Semaphore(max(1, self.settings.signal_classifier_concurrency))

        async def run_one(row: dict) -> SignalClassification:
            async with semaphore:
                return await self.classify_one(row)

        tasks = [run_one(row) for row in rows]
        return await asyncio.gather(*tasks)

    async def classify_one(self, row: dict) -> SignalClassification:
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        url = str(row.get("post_url") or row.get("url") or "").strip()
        designation = str(row.get("designation") or row.get("query_used") or "").strip()
        search_query = str(row.get("search_query") or row.get("query_used") or "").strip()
        cache_key = f"{title}::{url}::{designation}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        deterministic_company = self._company_extractor.extract_best(
            title=title,
            snippet=snippet,
            url=url,
            search_query=search_query,
        )

        if self._client is None:
            parsed = _fallback_classification(title, snippet)
            self._apply_company_selection(parsed, deterministic_company)
            parsed.role_match_score = _role_match_score(designation, parsed.role)
            self._log_company_selection(url=url, parsed=parsed)
            self._cache[cache_key] = parsed
            return parsed

        system_prompt = """
You are a hiring signal classifier.

Task 1: Determine whether the post signals ACTIVE hiring.
A post is hiring ONLY if:
1. It mentions an open role.
2. It invites applications or referrals.
3. It references a job link, recruiter, or hiring manager.

NOT hiring:
- hiring philosophy
- leadership
- career advice
- trends
- personal branding

Task 2: Extract job role ONLY from the post content.
Do not assume the role from the search query.

Task 3: Extract the company that is actively hiring.
If multiple companies are mentioned, choose the one actively hiring.

Examples:
- "We are hiring a product manager" -> hiring
- "Stop hiring animators" -> not hiring
- "CVS Health is hiring" -> company = CVS Health

Return strict JSON only. No markdown. No extra keys.
"""
        deterministic_hint = (
            f"{deterministic_company.company} (confidence={deterministic_company.confidence:.2f}, source={deterministic_company.source})"
            if deterministic_company is not None
            else "none"
        )
        user_prompt = f"""
Classify this search result.

Input:
- title: {title}
- snippet: {snippet}
- url: {url}
- designation: {designation}
- search_query: {search_query}
- deterministic_company_hint: {deterministic_hint}

Return JSON with keys exactly:
is_hiring (boolean),
hiring_confidence (number 0-1),
role (string),
seniority (string),
role_confidence (number 0-1),
company (string),
company_confidence (number 0-1),
reasoning (string, concise).

Use only the provided text fields for evidence.
"""
        try:
            response = await self._client.responses.create(
                model=self.settings.openai_signal_model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = _response_text(response)
            parsed = _parse_classification(text)
            if parsed is None:
                parsed = _fallback_classification(title, snippet)
        except Exception:
            parsed = _fallback_classification(title, snippet)

        self._apply_company_selection(parsed, deterministic_company)
        parsed.role_match_score = _role_match_score(designation, parsed.role)
        self._log_company_selection(url=url, parsed=parsed)
        self._cache[cache_key] = parsed
        return parsed

    def _apply_company_selection(
        self,
        parsed: SignalClassification,
        deterministic_company: CompanyExtractionResult | None,
    ) -> None:
        # Deterministic pipeline is preferred when confidence is high.
        if deterministic_company is not None and (
            deterministic_company.confidence >= self.settings.company_deterministic_min_confidence
        ):
            parsed.company = deterministic_company.company
            parsed.company_confidence = deterministic_company.confidence
            parsed.company_source = deterministic_company.source
        elif parsed.company:
            parsed.company_source = "llm"
            if parsed.company_confidence <= 0:
                parsed.company_confidence = 0.55
        elif deterministic_company is not None:
            parsed.company = deterministic_company.company
            parsed.company_confidence = deterministic_company.confidence
            parsed.company_source = deterministic_company.source

        if parsed.is_hiring:
            boosted = _derive_signal_strength(
                is_hiring=parsed.is_hiring,
                has_role=bool(parsed.role),
                has_company=bool(parsed.company),
                hiring_confidence=parsed.hiring_confidence or parsed.confidence,
            )
            if boosted > parsed.signal_strength:
                parsed.signal_strength = boosted
                parsed.signal_type = _default_signal_type(boosted)

    def _log_company_selection(self, *, url: str, parsed: SignalClassification) -> None:
        logger.info(
            "signal.company_extraction source=%s confidence=%.2f company=%s url=%s",
            parsed.company_source,
            parsed.company_confidence,
            parsed.company or "",
            url,
        )


def _response_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    return ""


def _parse_classification(raw: str) -> SignalClassification | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    is_hiring = _to_bool(payload.get("is_hiring"))
    role = str(payload.get("role") or "").strip()
    seniority = str(payload.get("seniority") or "").strip()
    company = str(payload.get("company") or "").strip()
    hiring_confidence = _clamp_float(payload.get("hiring_confidence"), 0.0, 1.0)
    role_confidence = _clamp_float(payload.get("role_confidence"), 0.0, 1.0)
    company_confidence = _clamp_float(payload.get("company_confidence"), 0.0, 1.0)
    confidence = _clamp_float(payload.get("confidence"), 0.0, 1.0)
    if confidence == 0.0:
        confidence = round((hiring_confidence + role_confidence + company_confidence) / 3, 4)

    signal_strength = _clamp_int(payload.get("signal_strength"), 0, 5)
    if signal_strength == 0 and is_hiring:
        signal_strength = _derive_signal_strength(
            is_hiring=is_hiring,
            has_role=bool(role),
            has_company=bool(company),
            hiring_confidence=hiring_confidence,
        )
    signal_type = str(payload.get("signal_type") or "").strip().lower()
    if signal_type not in {"strong", "weak", "indirect", "noise"}:
        signal_type = _default_signal_type(signal_strength)

    return SignalClassification(
        company=company,
        role=role,
        seniority=seniority,
        is_hiring=is_hiring,
        signal_strength=signal_strength,
        signal_type=signal_type,
        confidence=confidence,
        reasoning=str(payload.get("reasoning") or "").strip()[:500],
        hiring_confidence=hiring_confidence,
        role_match_score=0.0,
        company_confidence=company_confidence,
        company_source="llm",
    )


def _fallback_classification(title: str, snippet: str) -> SignalClassification:
    text = f"{title} {snippet}".lower()
    hiring_markers = ["hiring", "looking to hire", "we are hiring", "join our team", "opening"]
    is_hiring = any(marker in text for marker in hiring_markers)
    role = _infer_role(f"{title} {snippet}")
    strength = _derive_signal_strength(
        is_hiring=is_hiring,
        has_role=bool(role),
        has_company=False,
        hiring_confidence=0.45 if is_hiring else 0.2,
    )
    if not text.strip():
        strength = 0
    return SignalClassification(
        company="",
        role=role,
        seniority=_infer_seniority(text),
        is_hiring=is_hiring,
        signal_strength=strength,
        signal_type=_default_signal_type(strength),
        confidence=0.45 if is_hiring else 0.2,
        reasoning="Fallback heuristic classification",
        hiring_confidence=0.45 if is_hiring else 0.2,
        role_match_score=0.0,
        company_confidence=0.0,
        company_source="regex",
    )


def _infer_seniority(text: str) -> str:
    if "senior" in text:
        return "senior"
    if "staff" in text:
        return "staff"
    if "lead" in text:
        return "lead"
    if "principal" in text:
        return "principal"
    return ""


def _default_signal_type(signal_strength: int) -> str:
    if signal_strength >= 4:
        return "strong"
    if signal_strength >= 2:
        return "indirect"
    if signal_strength == 1:
        return "weak"
    return "noise"


def _derive_signal_strength(*, is_hiring: bool, has_role: bool, has_company: bool, hiring_confidence: float) -> int:
    if not is_hiring:
        return 0
    if has_role and has_company and hiring_confidence >= 0.75:
        return 5
    if has_role and (has_company or hiring_confidence >= 0.65):
        return 4
    if has_role or has_company:
        return 3
    return 2


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered in {"true", "yes", "1"}
    return False


def _infer_role(text: str) -> str:
    lowered = text.lower()
    role_map = [
        ("senior product marketing manager", "Senior Product Marketing Manager"),
        ("product marketing manager", "Product Marketing Manager"),
        ("senior product manager", "Senior Product Manager"),
        ("product manager", "Product Manager"),
        ("program manager", "Program Manager"),
        ("project manager", "Project Manager"),
    ]
    for needle, output in role_map:
        if needle in lowered:
            return output
    return ""


def _clamp_int(value: object, low: int, high: int) -> int:
    try:
        num = int(value)
    except Exception:
        return low
    return max(low, min(high, num))


def _clamp_float(value: object, low: float, high: float) -> float:
    try:
        num = float(value)
    except Exception:
        return low
    return max(low, min(high, num))


def _role_match_score(designation: str, role: str) -> float:
    if not designation or not role:
        return 0.0
    return round(difflib.SequenceMatcher(None, designation.lower().strip(), role.lower().strip()).ratio(), 4)
