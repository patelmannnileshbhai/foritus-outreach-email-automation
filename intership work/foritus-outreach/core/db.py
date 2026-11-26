import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS leads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  designation TEXT, company TEXT, website TEXT, country TEXT,
  status TEXT DEFAULT 'new',          -- new, researched, drafted, approved, sent, replied, opted_out, bounced
  score INTEGER DEFAULT 0, score_label TEXT DEFAULT 'cold', score_detail TEXT,
  source TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS research(
  lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
  status TEXT,                         -- ok, partial, failed
  confidence REAL DEFAULT 0,
  industry TEXT, industry_detail TEXT, summary TEXT,
  offerings TEXT, facts TEXT, signals TEXT, opportunities TEXT, pages TEXT,
  llm_used TEXT, error TEXT, fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS emails(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  step INTEGER NOT NULL DEFAULT 0,     -- 0 = first email, 1.. = follow-ups
  subject TEXT, body TEXT, language TEXT, region TEXT,
  facts_used TEXT, generator TEXT,     -- generator: llm:<provider> | composer
  status TEXT DEFAULT 'draft',         -- draft, approved, sending, sent, failed, rejected, blocked
  quality_score INTEGER DEFAULT 0, quality TEXT,
  token TEXT UNIQUE, message_id TEXT,
  attempts INTEGER DEFAULT 0, error TEXT,
  created_at TEXT, approved_at TEXT, sent_at TEXT, sent_day TEXT,
  UNIQUE(lead_id, step)                -- hard guarantee: never two emails for same lead+step
);

CREATE TABLE IF NOT EXISTS optouts(
  email TEXT PRIMARY KEY COLLATE NOCASE, reason TEXT, source TEXT, created_at TEXT
);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER, email_id INTEGER, type TEXT, meta TEXT, ts TEXT
);

CREATE TABLE IF NOT EXISTS replies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lead_id INTEGER, email_id INTEGER, from_addr TEXT, subject TEXT, body TEXT,
  classification TEXT, message_id TEXT UNIQUE, ts TEXT
);
CREATE INDEX IF NOT EXISTS idx_emails_status ON emails(status);
CREATE INDEX IF NOT EXISTS idx_events_lead ON events(lead_id);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextmanager
def conn():
    with _lock:
        c = _connect()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def rows(sql, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    with conn() as c:
        r = c.execute(sql, args).fetchone()
        return dict(r) if r else None


def execute(sql, args=()):
    """Returns (lastrowid, rowcount)."""
    with conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid, cur.rowcount


def log_event(lead_id, email_id, type_, meta=""):
    execute("INSERT INTO events(lead_id,email_id,type,meta,ts) VALUES(?,?,?,?,?)",
            (lead_id, email_id, type_, str(meta)[:500], now()))
