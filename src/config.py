"""
Configuration management for GraphOne pipeline.
Loads settings from config.yaml and environment variables.
"""
from pathlib import Path
from typing import Any, Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HttpConfig(BaseModel):
    """HTTP client configuration."""
    timeout: int = 30
    max_retries: int = 3
    retry_backoff_factor: float = 2.0
    user_agents: list[str] = Field(default_factory=list)
    respect_robots_txt: bool = True
    conditional_requests: bool = True


class RateLimitingConfig(BaseModel):
    """Rate limiting configuration."""
    default_rpm: int = 60
    default_delay: float = 1.0
    domain_limits: dict[str, int] = Field(default_factory=dict)


class ConcurrencyConfig(BaseModel):
    """Concurrency settings."""
    max_concurrent_requests: int = 50
    max_concurrent_per_domain: int = 5
    semaphore_limit: int = 100


class BrowserConfig(BaseModel):
    """Browser (Playwright) configuration."""
    headless: bool = True
    timeout: int = 45000
    wait_until: str = "networkidle"
    block_resources: list[str] = Field(default_factory=list)
    viewport: dict[str, int] = Field(default_factory=dict)


class LLMProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""
    provider: str
    model: str
    max_tokens: int
    rpm_limit: int
    tpm_limit: int
    timeout: int = 30


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker configuration."""
    failure_threshold: int = 5
    recovery_timeout: int = 300
    half_open_attempts: int = 2


class LLMConfig(BaseModel):
    """LLM orchestration configuration."""
    fallback_chain: list[LLMProviderConfig] = Field(default_factory=list)
    max_retries_per_provider: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 60.0
    jitter: bool = True
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    reserve_tokens: int = 500
    chunk_overlap: int = 200


class GroundingConfig(BaseModel):
    """Grounding validator configuration."""
    enabled: bool = True
    fuzzy_threshold: int = 85
    required_fields: list[str] = Field(default_factory=list)


class EntityResolutionConfig(BaseModel):
    """Entity resolution configuration."""
    exact_match_threshold: int = 100
    fuzzy_match_threshold: int = 92
    space_insensitive: bool = True
    strip_legal_suffixes: bool = True
    legal_suffixes: list[str] = Field(default_factory=list)


class DatesConfig(BaseModel):
    """Date parsing configuration."""
    priority_order: list[str] = Field(default_factory=list)
    relative_base: str = "utc_now"
    confidence_levels: list[str] = Field(default_factory=list)


class FreshnessConfig(BaseModel):
    """Freshness filtering configuration."""
    news_max_age_hours: int = 24
    jobs_max_age_hours: int = 24
    use_first_seen_fallback: bool = True


class DataSourceConfig(BaseModel):
    """Configuration for a single data source."""
    name: str
    type: str
    enabled: bool = True
    url: Optional[str] = None
    url_pattern: Optional[str] = None
    rss_url: Optional[str] = None
    rate_limit: Optional[int] = None
    use_browser: bool = False
    note: Optional[str] = None
    categories: Optional[list[str]] = None
    max_results_per_category: Optional[int] = None
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None
    search_query: Optional[str] = None
    topics: Optional[list[str]] = None


class SourcesConfig(BaseModel):
    """All data sources configuration."""
    papers: list[DataSourceConfig] = Field(default_factory=list)
    startups: list[DataSourceConfig] = Field(default_factory=list)
    products: list[DataSourceConfig] = Field(default_factory=list)
    news: list[DataSourceConfig] = Field(default_factory=list)
    jobs: list[DataSourceConfig] = Field(default_factory=list)


class StorageConfig(BaseModel):
    """Storage configuration."""
    database: str = "sqlite"
    path: str = "data/graphone.db"
    backup_enabled: bool = True
    checkpoint_interval: int = 100


class GoogleSheetsConfig(BaseModel):
    """Google Sheets export configuration."""
    create_new: bool = True
    make_public: bool = True
    batch_size: int = 1000


class ExportConfig(BaseModel):
    """Export configuration."""
    formats: list[str] = Field(default_factory=list)
    google_sheets: GoogleSheetsConfig = Field(default_factory=GoogleSheetsConfig)
    csv_output_dir: str = "data/output"


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = ""
    file: str = "logs/graphone.log"
    rotation: str = "100 MB"
    retention: str = "10 days"
    colorize: bool = True


class Config(BaseModel):
    """Main configuration container."""
    http: HttpConfig = Field(default_factory=HttpConfig)
    rate_limiting: RateLimitingConfig = Field(default_factory=RateLimitingConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    grounding: GroundingConfig = Field(default_factory=GroundingConfig)
    entity_resolution: EntityResolutionConfig = Field(default_factory=EntityResolutionConfig)
    dates: DatesConfig = Field(default_factory=DatesConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    schema_version: str = "1.0"


class EnvSettings(BaseSettings):
    """Environment-based settings from .env file."""
    
    # LLM API Keys
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    
    # GitHub
    github_token: Optional[str] = None
    
    # Google Sheets
    google_service_account_json: Optional[str] = None
    google_sheet_id: Optional[str] = None
    
    # Database
    database_path: str = "data/graphone.db"
    
    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/graphone.log"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


def load_config(config_path: str = "config.yaml") -> Config:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to config YAML file
        
    Returns:
        Config object with all settings
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_file, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    
    return Config(**config_data)


def load_env_settings() -> EnvSettings:
    """
    Load environment settings from .env file.
    
    Returns:
        EnvSettings object with environment variables
    """
    return EnvSettings()


# Global config instances (lazy loaded)
_config: Optional[Config] = None
_env_settings: Optional[EnvSettings] = None


def get_config() -> Config:
    """Get or load the global configuration."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_env_settings() -> EnvSettings:
    """Get or load the global environment settings."""
    global _env_settings
    if _env_settings is None:
        _env_settings = load_env_settings()
    return _env_settings
