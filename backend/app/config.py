from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+psycopg://app_user:app_password@localhost:5432/job_posts"
    allowed_origins: str = "http://localhost:3000"

    clerk_issuer: str = ""
    clerk_audience: str = ""

    collector_queries: str = (
        "product manager,senior product manager,product marketing manager,program manager"
    )
    collector_hiring_terms: str = "we are hiring,hiring,looking to hire,hiring for,join our team"
    collector_block_terms: str = "careers,microsoft careers,job opening,vacancy"
    google_api_key: str = ""
    google_cse_id: str = ""
    google_results_per_query: int = 20
    openai_api_key: str = ""
    openai_company_model: str = "gpt-5.2"
    collector_days_back: int = 7
    collector_timeout_seconds: float = 15.0
    collector_max_retries: int = 3

    scheduler_interval_hours: int = 6

    default_page_size: int = 25
    max_page_size: int = 100

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def query_terms(self) -> list[str]:
        return [q.strip() for q in self.collector_queries.split(",") if q.strip()]

    @property
    def hiring_terms(self) -> list[str]:
        return [q.strip().lower() for q in self.collector_hiring_terms.split(",") if q.strip()]

    @property
    def blocked_terms(self) -> list[str]:
        return [q.strip().lower() for q in self.collector_block_terms.split(",") if q.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
