"""Configuration. Secrets come ONLY from environment / .env (never stored in the DB,
never returned by the API). Operational knobs can be overridden at runtime from the UI
(stored in the settings table)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "outreach.db"
OUTBOX_DIR = DATA_DIR / "outbox"
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

# Operational defaults (UI-editable). name -> (default, type)
TUNABLES = {
    "DAILY_LIMIT": ("25", int),
    "SEND_DELAY_SECONDS": ("3", float),
    "TEST_MODE": ("true", bool),
    "SEND_MODE": ("outbox", str),  # outbox | smtp
    "TRACK_OPENS": ("true", bool),
    "FOLLOWUP_DAYS": ("3,7", str),
    "MIN_QUALITY_TO_APPROVE": ("70", int),
    "SENDER_NAME": ("Alex from ForITus", str),
    "SENDER_TITLE": ("Business Development", str),
    "BASE_URL": ("http://127.0.0.1:5000", str),
}

SECRET_KEYS = [
    "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "SMTP_PASS", "IMAP_PASS",
]


def _to(v, t):
    if t is bool:
        return str(v).strip().lower() in ("1", "true", "yes", "on")
    if t is int:
        return int(float(v))
    if t is float:
        return float(v)
    return str(v)


def env(key, default=""):
    return os.environ.get(key, default)


def get(key):
    """Runtime value: DB override > environment > default."""
    from . import db  # late import to avoid cycle
    default, typ = TUNABLES[key]
    row = None
    try:
        row = db.one("SELECT value FROM settings WHERE key=?", (key,))
    except Exception:
        pass
    raw = row["value"] if row else os.environ.get(key, default)
    try:
        return _to(raw, typ)
    except Exception:
        return _to(default, typ)


def all_tunables():
    return {k: get(k) for k in TUNABLES}


def set_tunable(key, value):
    from . import db
    if key not in TUNABLES:
        raise KeyError(key)
    _to(value, TUNABLES[key][1])  # validate
    db.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def test_allowlist():
    """Comma separated list of authorised test addresses and/or @domains."""
    raw = env("TEST_ALLOWLIST", "")
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def smtp_config():
    return {
        "host": env("SMTP_HOST"), "port": int(env("SMTP_PORT", "587") or 587),
        "user": env("SMTP_USER"), "password": env("SMTP_PASS"),
        "from_addr": env("SMTP_FROM") or env("SMTP_USER"),
        "security": env("SMTP_SECURITY", "starttls").lower(),  # starttls | ssl | none
    }


def imap_config():
    return {
        "host": env("IMAP_HOST"), "port": int(env("IMAP_PORT", "993") or 993),
        "user": env("IMAP_USER") or env("SMTP_USER"),
        "password": env("IMAP_PASS") or env("SMTP_PASS"),
    }


def company_profile():
    import json
    p = BASE_DIR / "company_profile.json"
    return json.loads(p.read_text(encoding="utf-8"))
