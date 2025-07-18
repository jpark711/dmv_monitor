"""
config.py
=========

Minimal configuration loader for the DMV appointment monitor.
Robust to YAML date types; loads environment overrides (including a .env file).
"""

from __future__ import annotations
import os
import yaml
from pathlib import Path
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import List, Set, Any

# Load .env early (NEW)
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "settings.yaml"
DATE_FMT = "%Y-%m-%d"


@dataclass
class AppConfig:
    refresh_minutes: int = 10
    default_cutoff_date: date = date(2025, 8, 15)
    target_dmvs: Set[str] = field(default_factory=set)
    enable_email: bool = True
    headless: bool = True
    scrape_timeout_ms: int = 25000


@dataclass
class EmailConfig:
    host: str = "smtp.gmail.com"
    port: int = 465
    user: str = ""
    password: str = ""  # from env only
    from_addr: str = ""
    to_addrs: List[str] = field(default_factory=list)
    use_tls: bool = True
    use_starttls: bool = False
    subject_prefix: str = "[NJ MVC]"

    def recipients(self) -> List[str]:
        base = self.to_addrs or ([self.from_addr] if self.from_addr else [])
        return [r for r in base if r]


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _coerce_date_value(value: Any, default: date) -> date:
    if value is None:
        return default
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), DATE_FMT).date()
        except ValueError:
            return default
    return default


def _date_env(name: str, default: date) -> date:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return datetime.strptime(val.strip(), DATE_FMT).date()
    except ValueError:
        return default


def load_yaml() -> dict:
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_config() -> tuple[AppConfig, EmailConfig]:
    data = load_yaml()
    app_yaml = data.get("app", {})
    email_yaml = data.get("email", {})

    refresh_minutes_yaml = app_yaml.get("refresh_minutes", 10)
    default_cutoff_yaml = app_yaml.get("default_cutoff_date", "2025-08-15")
    target_dmvs_yaml = app_yaml.get("target_dmvs", [])
    enable_email_yaml = app_yaml.get("enable_email", True)
    headless_yaml = app_yaml.get("headless", True)
    scrape_timeout_yaml = app_yaml.get("scrape_timeout_ms", 25000)

    default_cutoff_date = _coerce_date_value(default_cutoff_yaml, date(2025, 8, 15))
    default_cutoff_date = _date_env("DEFAULT_CUTOFF_DATE", default_cutoff_date)

    refresh_minutes = _int_env("REFRESH_MINUTES", refresh_minutes_yaml)
    enable_email = _bool_env("ENABLE_EMAIL", enable_email_yaml)
    headless = _bool_env("HEADLESS", headless_yaml)
    scrape_timeout_ms = _int_env("SCRAPE_TIMEOUT_MS", scrape_timeout_yaml)

    target_dmvs_env = os.getenv("TARGET_DMVS")
    if target_dmvs_env:
        target_dmvs = {x.strip() for x in target_dmvs_env.split(",") if x.strip()}
    else:
        target_dmvs = {
            x.strip() for x in target_dmvs_yaml if isinstance(x, str) and x.strip()
        }

    app_cfg = AppConfig(
        refresh_minutes=refresh_minutes,
        default_cutoff_date=default_cutoff_date,
        target_dmvs=target_dmvs,
        enable_email=enable_email,
        headless=headless,
        scrape_timeout_ms=scrape_timeout_ms,
    )

    email_cfg = EmailConfig(
        host=os.getenv("EMAIL_HOST", email_yaml.get("host", "smtp.gmail.com")),
        port=_int_env("EMAIL_PORT", email_yaml.get("port", 465)),
        user=os.getenv("EMAIL_USER", email_yaml.get("user", "")),
        password=os.getenv("EMAIL_PASS", ""),
        from_addr=os.getenv("EMAIL_FROM", email_yaml.get("from", "")),
        to_addrs=(
            [x.strip() for x in os.getenv("EMAIL_TO", "").split(",") if x.strip()]
            if os.getenv("EMAIL_TO")
            else [x for x in email_yaml.get("to", []) if x]
        ),
        use_tls=_bool_env("EMAIL_USE_TLS", email_yaml.get("use_tls", True)),
        use_starttls=_bool_env(
            "EMAIL_USE_STARTTLS", email_yaml.get("use_starttls", False)
        ),
        subject_prefix=os.getenv(
            "EMAIL_SUBJECT_PREFIX", email_yaml.get("subject_prefix", "[NJ MVC]")
        ),
    )

    if email_yaml.get("password"):
        print(
            "[SECURITY WARNING] Ignoring password in YAML. Use EMAIL_PASS env variable instead."
        )

    return app_cfg, email_cfg


APP_CONFIG, EMAIL_CONFIG = load_config()

STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(exist_ok=True, parents=True)
NOTIFICATION_STATE_FILE = STATE_DIR / "notification_state.json"
