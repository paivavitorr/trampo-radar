"""Configurações da aplicação (Pydantic Settings + YAML)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScheduleConfig(BaseModel):
    enabled: bool = True
    daily_hour: int = Field(default=18, ge=0, le=23)
    daily_minute: int = Field(default=0, ge=0, le=59)
    run_on_startup: bool = False


class EmailConfig(BaseModel):
    enabled: bool = True
    folder: str = "INBOX"
    lookback_days: int = Field(default=1, ge=1)
    unseen_only: bool = True
    sender_filters: list[str] = Field(
        default_factory=lambda: [
            "linkedin.com",
            "gupy.com.br",
            "gupy.io",
            "indeed.com",
            "glassdoor.com",
            "programathor.com.br",
            "trampos.co",
        ]
    )
    subject_keywords: list[str] = Field(
        default_factory=lambda: ["vaga", "vagas", "job", "jobs", "oportunidade", "alerta"]
    )


class LinkedInConfig(BaseModel):
    enabled: bool = True
    keywords: list[str] = Field(default_factory=lambda: ["python"])
    location: str = "remote"
    max_results: int = Field(default=15, ge=1)
    post_time: str = "day"


class ProxyConfig(BaseModel):
    enabled: bool = False
    urls: list[str] = Field(default_factory=list)


class RateLimitConfig(BaseModel):
    requests_per_second: float = 0.5
    burst: int = 1


class FilterConfig(BaseModel):
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    include_companies: list[str] = Field(default_factory=list)
    include_locations: list[str] = Field(default_factory=list)
    exclude_locations: list[str] = Field(default_factory=list)
    min_description_length: int = 0
    max_job_age_days: int = 0


class TelegramChannelConfig(BaseModel):
    enabled: bool = True
    bot_token: str = ""
    chat_id: int = 0


class SmtpDigestConfig(BaseModel):
    enabled: bool = False


class AIConfig(BaseModel):
    enable: bool = True
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-120b"
    api_token: str = ""
    max_tokens: int = 8192
    batch_size: int = 3


class ContactConfig(BaseModel):
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""


class LanguageItem(BaseModel):
    language: str = ""
    level: str = ""


class EducationItem(BaseModel):
    course: str = ""
    institution: str = ""
    period: str = ""


class ExperienceItem(BaseModel):
    role: str = ""
    company: str = ""
    period: str = ""
    description: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str = ""
    link: str = ""
    description: str = ""


class ProfileConfig(BaseModel):
    name: str = ""
    job_title: str = ""
    contact: ContactConfig = Field(default_factory=ContactConfig)
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)


class AppYamlConfig(BaseModel):
    """Estrutura do arquivo config.yaml."""

    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    smtp_digest: SmtpDigestConfig = Field(default_factory=SmtpDigestConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)


class Settings(BaseSettings):
    """Configurações de ambiente (.env) + carregamento do config.yaml."""

    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: int = 0

    ai_api_key: str = ""

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_to: str = ""

    data_dir: Path = Path("./data")
    config_file: Path = Path("./config.yaml")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def load_yaml_config(self) -> AppYamlConfig:
        """Carrega o arquivo config.yaml e mescla com variáveis de ambiente."""
        raw: dict[str, Any] = {}
        if self.config_file.exists():
            content = self.config_file.read_text(encoding="utf-8")
            loaded = yaml.safe_load(content)
            if isinstance(loaded, dict):
                raw = self._normalize_none_lists(loaded)

        cfg = AppYamlConfig.model_validate(raw)

        if self.telegram_bot_token:
            cfg.telegram.bot_token = self.telegram_bot_token
        if self.telegram_chat_id != 0:
            cfg.telegram.chat_id = self.telegram_chat_id
        if self.ai_api_key:
            cfg.ai.api_token = self.ai_api_key

        return cfg

    @staticmethod
    def _normalize_none_lists(data: dict[str, Any]) -> dict[str, Any]:
        """Normaliza chaves de filtro vazias no YAML (None -> [])."""
        if "filters" in data and isinstance(data["filters"], dict):
            for key, val in list(data["filters"].items()):
                if val is None and key not in ("min_description_length", "max_job_age_days"):
                    data["filters"][key] = []
        return data


@lru_cache
def get_settings() -> Settings:
    """Retorna instância cacheada das configurações."""
    return Settings()
