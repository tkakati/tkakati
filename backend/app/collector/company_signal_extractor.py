import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass
class CompanyExtractionResult:
    company: str
    confidence: float
    source: str


class CompanySignalExtractor:
    DOMAIN_MAP = {
        "cvshealth": "CVS Health",
        "walgreens": "Walgreens",
        "microsoft": "Microsoft",
        "google": "Google",
        "amazon": "Amazon",
        "meta": "Meta",
        "apple": "Apple",
        "stripe": "Stripe",
        "crunchbase": "Crunchbase",
        "airbnb": "Airbnb",
        "uber": "Uber",
        "nvidia": "NVIDIA",
        "tesla": "Tesla",
        "netflix": "Netflix",
    }

    def extract_best(self, *, title: str, snippet: str, url: str, search_query: str = "") -> CompanyExtractionResult | None:
        candidates: list[CompanyExtractionResult] = []

        url_candidate = self._extract_from_url(url)
        if url_candidate is not None:
            candidates.append(url_candidate)

        domain_candidate = self._extract_from_domain_sources(title=title, snippet=snippet, url=url)
        if domain_candidate is not None:
            candidates.append(domain_candidate)

        regex_candidate = self._extract_from_text_patterns(f"{title} {snippet} {search_query}".strip())
        if regex_candidate is not None:
            candidates.append(regex_candidate)

        if not candidates:
            return None
        return max(candidates, key=lambda x: x.confidence)

    def _extract_from_url(self, url: str) -> CompanyExtractionResult | None:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            path = unquote(parsed.path or "")
        except Exception:
            return None
        if "linkedin.com" not in host:
            return None

        company_path_match = re.search(r"/company/([a-zA-Z0-9-]+)", path)
        if company_path_match:
            company = self._slug_to_company(company_path_match.group(1))
            if company:
                return CompanyExtractionResult(company=company, confidence=0.92, source="url")

        jobs_view_match = re.search(r"/jobs/view/[^/?#]*-at-([a-zA-Z0-9-]+)", path)
        if jobs_view_match:
            company = self._slug_to_company(jobs_view_match.group(1))
            if company:
                return CompanyExtractionResult(company=company, confidence=0.95, source="url")

        generic_at_match = re.search(r"-at-([a-zA-Z0-9-]+)", path)
        if generic_at_match:
            company = self._slug_to_company(generic_at_match.group(1))
            if company:
                return CompanyExtractionResult(company=company, confidence=0.86, source="url")

        return None

    def _extract_from_domain_sources(self, *, title: str, snippet: str, url: str) -> CompanyExtractionResult | None:
        text_urls = self._extract_urls_from_text(f"{title} {snippet}".strip())
        candidates: list[CompanyExtractionResult] = []
        for candidate_url in text_urls:
            domain_candidate = self._company_from_domain(candidate_url, source_confidence=0.82)
            if domain_candidate is not None:
                candidates.append(domain_candidate)

        source_domain_candidate = self._company_from_domain(url, source_confidence=0.78)
        if source_domain_candidate is not None:
            candidates.append(source_domain_candidate)

        if not candidates:
            return None
        return max(candidates, key=lambda x: x.confidence)

    def _extract_from_text_patterns(self, text: str) -> CompanyExtractionResult | None:
        if not text:
            return None
        patterns = [
            (r"\b([A-Z][A-Za-z0-9&.,' -]{1,80})\s+is\s+hiring\b", 0.79),
            (r"\bat\s+([A-Z][A-Za-z0-9&.,' -]{1,80})\b", 0.72),
            (r"\bjoin\s+([A-Z][A-Za-z0-9&.,' -]{1,80})\b", 0.7),
        ]
        best: CompanyExtractionResult | None = None
        for pattern, confidence in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            cleaned = self._clean_company(match.group(1))
            if not cleaned:
                continue
            candidate = CompanyExtractionResult(company=cleaned, confidence=confidence, source="regex")
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        return best

    def _extract_urls_from_text(self, text: str) -> list[str]:
        if not text:
            return []
        urls = re.findall(r"https?://[^\s<>\]\)\"']+", text)
        normalized = [u.strip(".,);]") for u in urls if u.strip()]
        return normalized

    def _company_from_domain(self, url: str, source_confidence: float) -> CompanyExtractionResult | None:
        if not url:
            return None
        try:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            if not host:
                return None
        except Exception:
            return None

        if "linkedin.com" in host or "lnkd.in" in host:
            return None
        if host.startswith("www."):
            host = host[4:]

        root = self._domain_root(host)
        if not root:
            return None
        company = self._domain_root_to_company(root)
        if not company:
            return None
        return CompanyExtractionResult(company=company, confidence=source_confidence, source="domain")

    def _domain_root(self, host: str) -> str:
        if not host:
            return ""
        parts = host.split(".")
        if len(parts) < 2:
            return ""
        common_subdomains = {"jobs", "job", "careers", "career", "apply", "myworkdayjobs", "boards"}
        while len(parts) > 2 and parts[0] in common_subdomains:
            parts = parts[1:]
        return parts[-2]

    def _domain_root_to_company(self, root: str) -> str:
        cleaned = root.strip().lower()
        if not cleaned:
            return ""
        if cleaned in self.DOMAIN_MAP:
            return self.DOMAIN_MAP[cleaned]
        return self._slug_to_company(cleaned)

    def _slug_to_company(self, slug: str) -> str:
        if not slug:
            return ""
        slug = slug.strip().lower()
        slug = re.sub(r"-\d+$", "", slug)
        if slug in self.DOMAIN_MAP:
            return self.DOMAIN_MAP[slug]
        tokens = [t for t in re.split(r"[-_]+", slug) if t]
        if not tokens:
            return ""
        upper_tokens = {"ai", "hr", "it", "us", "uk", "qa", "ml"}
        out = []
        for token in tokens:
            if token in upper_tokens:
                out.append(token.upper())
            elif len(token) <= 2 and token.isalpha():
                out.append(token.upper())
            else:
                out.append(token.capitalize())
        return self._clean_company(" ".join(out))

    def _clean_company(self, company: str) -> str:
        if not company:
            return ""
        candidate = company.strip(" -|:,.")
        for sep in [" for ", " as ", " to ", " in ", " with ", " - ", " | "]:
            idx = candidate.lower().find(sep)
            if idx > 0:
                candidate = candidate[:idx].strip()
                break
        blocked = {"team", "our team", "us", "we", "our", "this company"}
        if candidate.lower() in blocked:
            return ""
        return candidate[:120]
