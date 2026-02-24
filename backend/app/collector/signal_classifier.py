import asyncio
import json
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import Settings


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


class SignalClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )
        self._cache: dict[str, SignalClassification] = {}

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

        if self._client is None:
            fallback = _fallback_classification(title, designation, snippet)
            self._cache[cache_key] = fallback
            return fallback

        system_prompt = (
            "You are a hiring intelligence classifier. "
            "Extract hiring signals from LinkedIn-style posts and return strict JSON only. "
            "No markdown, no prose outside JSON."
        )
        user_prompt = f"""
Classify this search result.

Input:
- title: {title}
- snippet: {snippet}
- url: {url}
- designation: {designation}
- search_query: {search_query}

Return JSON with keys:
company (string),
role (string),
seniority (string),
is_hiring (boolean),
signal_strength (integer 0-5),
signal_type (one of: strong, weak, indirect, noise),
confidence (number 0-1),
reasoning (string, concise).

Scoring rubric:
5 = direct hiring post from recruiter/company with clear active role
4 = strong hiring language, actor less clear
3 = indirect hiring/expansion signal
2 = team or industry growth discussion
1 = weak signal
0 = noise / not hiring related
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
                parsed = _fallback_classification(title, designation, snippet)
        except Exception:
            parsed = _fallback_classification(title, designation, snippet)

        self._cache[cache_key] = parsed
        return parsed


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

    signal_strength = _clamp_int(payload.get("signal_strength"), 0, 5)
    confidence = _clamp_float(payload.get("confidence"), 0.0, 1.0)
    signal_type = str(payload.get("signal_type") or "").strip().lower()
    if signal_type not in {"strong", "weak", "indirect", "noise"}:
        signal_type = _default_signal_type(signal_strength)

    return SignalClassification(
        company=str(payload.get("company") or "").strip(),
        role=str(payload.get("role") or "").strip(),
        seniority=str(payload.get("seniority") or "").strip(),
        is_hiring=bool(payload.get("is_hiring")),
        signal_strength=signal_strength,
        signal_type=signal_type,
        confidence=confidence,
        reasoning=str(payload.get("reasoning") or "").strip()[:500],
    )


def _fallback_classification(title: str, designation: str, snippet: str) -> SignalClassification:
    text = f"{title} {snippet}".lower()
    hiring_markers = ["hiring", "looking to hire", "we are hiring", "join our team", "opening"]
    is_hiring = any(marker in text for marker in hiring_markers)
    strength = 4 if is_hiring else 1
    if not text.strip():
        strength = 0
    return SignalClassification(
        company="",
        role=designation,
        seniority=_infer_seniority(text),
        is_hiring=is_hiring,
        signal_strength=strength,
        signal_type=_default_signal_type(strength),
        confidence=0.45 if is_hiring else 0.2,
        reasoning="Fallback heuristic classification",
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
