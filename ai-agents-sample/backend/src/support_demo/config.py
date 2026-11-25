from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "postgresql+psycopg://support:support@localhost:5432/support"
    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    azure_openai_deployment: str = "gpt-5.4-mini"
    azure_openai_embedding_deployment: str = ""
    embedding_dimensions: int = Field(default=1536, ge=8, le=4096)
    max_group_turns: int = Field(default=12, ge=3, le=30)
    transient_retries: int = Field(default=2, ge=0, le=4)
    investigation_timeout_seconds: int = Field(default=120, ge=10, le=600)
    job_lease_seconds: int = Field(default=180, ge=30, le=900)
    worker_concurrency: int = Field(default=2, ge=1, le=8)
    telemetry_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    capture_synthetic_payloads: bool = False
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    data_directory: str = "../data"

    def require_azure(self) -> None:
        missing = [
            name
            for name in (
                "azure_openai_endpoint",
                "azure_openai_deployment",
                "azure_openai_embedding_deployment",
            )
            if not getattr(self, name)
        ]
        if not self.azure_openai_api_key.get_secret_value():
            missing.append("azure_openai_api_key")
        if missing:
            raise ValueError(f"Configure required Azure settings: {', '.join(missing)}")
        if not self.azure_openai_endpoint.startswith("https://"):
            raise ValueError("AZURE_OPENAI_ENDPOINT must be an HTTPS resource endpoint")

    @property
    def azure_base_url(self) -> str:
        endpoint = self.azure_openai_endpoint.rstrip("/")
        return endpoint + "/" if endpoint.endswith("/openai/v1") else endpoint + "/openai/v1/"


@lru_cache
def settings() -> Settings:
    return Settings()
