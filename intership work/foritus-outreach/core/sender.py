"""Sending engine: daily limits, approval gate, duplicate prevention, opt-out check,
test-mode allowlist, retries with failure classification, and delivery via SMTP or an .eml outbox."""
import html
import re
import smtplib
import socket
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, formataddr

from . import config, db, scoring
from .ingest import EMAIL_RE

MAX_ATTEMPTS = 3


class FatalSendError(Exception):
    """Authentication / configuration problem: abort the whole batch."""


def local_day():
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def sent_today():
    return db.one("SELECT COUNT(*) c FROM emails WHERE status='sent' AND sent_day=?", (local_day(),))["c"]


def remaining_today():
    return max(0, config.get("DAILY_LIMIT") - sent_today())


def is_allowed_test_recipient(addr):
    addr = addr.lower()
    for rule in config.test_allowlist():
        if rule.startswith("@") and addr.endswith(rule):
            return True
        if addr == rule:
            return True
    return False


def from_address():
    cfg = config.smtp_config()
    return cfg["from_addr"] or "outreach@localhost"


def render(email, lead, preview=False):
    """Return (text, html) with the unsubscribe URL and (unless preview) the tracking pixel."""
    base = config.get("BASE_URL").rstrip("/")
    unsub = f"{base}/u/{email['token']}"
    text = (email["body"] or "").replace("{{UNSUB_URL}}", unsub)
    paras = [p for p in re.split(r"\n{2,}", text.strip())]
    body_html = "".join(
        "<p style=\"margin:0 0 14px;line-height:1.55\">" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paras)
    body_html = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', body_html)
    pixel = ""
    if config.get("TRACK_OPENS") and not preview:
        pixel = f'<img src="{base}/t/o/{email["token"]}.gif" width="1" height="1" alt="" style="display:none">'
    doc = ("<html><body style=\"font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:15px;color:#222\">"
           + body_html + pixel + "</body></html>")
    return text, doc


def build_message(email, lead, to_addr=None, subject_prefix=""):
    base = config.get("BASE_URL").rstrip("/")
    text, doc = render(email, lead)
    msg = EmailMessage()
    sender = from_address()
    msg["From"] = formataddr((config.get("SENDER_NAME"), sender))
    msg["To"] = to_addr or lead["email"]
    msg["Subject"] = subject_prefix + email["subject"]
    msg["Date"] = formatdate(localtime=True)
    mid = email.get("message_id") or make_msgid(domain=(sender.split("@")[-1] or "localhost"))
    msg["Message-ID"] = mid
    msg["List-Unsubscribe"] = f"<{base}/u/{email['token']}>, <mailto:{sender}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    if email["step"] > 0:
        first = db.one("SELECT message_id FROM emails WHERE lead_id=? AND step=0", (lead["id"],))
        if first and first["message_id"]:
            msg["In-Reply-To"] = first["message_id"]
            msg["References"] = first["message_id"]
    msg.set_content(text)
    msg.add_alternative(doc, subtype="html")
    return msg, mid


def _deliver(msg):
    mode = config.get("SEND_MODE")
    if mode == "outbox":
        from .config import OUTBOX_DIR
        slug = re.sub(r"[^a-z0-9]+", "-", msg["To"].lower()).strip("-")[:40]
        path = OUTBOX_DIR / f"{int(time.time()*1000)}-{slug}.eml"
        path.write_bytes(bytes(msg))
        return f"outbox:{path.name}"
    cfg = config.smtp_config()
    if not cfg["host"] or not cfg["from_addr"]:
        raise FatalSendError("SMTP is not configured (set SMTP_HOST, SMTP_USER, SMTP_PASS in .env) or switch SEND_MODE to 'outbox'.")
    try:
        if cfg["security"] == "ssl":
            s = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
            s.ehlo()
            if cfg["security"] == "starttls":
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
        with s:
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return "smtp"
    except smtplib.SMTPAuthenticationError as e:
        raise FatalSendError(f"SMTP authentication failed: {e.smtp_code}. Check SMTP_USER / SMTP_PASS (use an app password).")
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentError(f"Recipient refused: {list(e.recipients.values())[0][1].decode(errors='ignore') if e.recipients else e}")
    except smtplib.SMTPResponseException as e:
        if 500 <= e.smtp_code < 600:
            raise PermanentError(f"SMTP {e.smtp_code}: {e.smtp_error.decode(errors='ignore')[:150]}")
        raise TransientError(f"SMTP {e.smtp_code}: {e.smtp_error.decode(errors='ignore')[:150]}")
    except (smtplib.SMTPException, socket.timeout, ConnectionError, OSError) as e:
        raise TransientError(str(e)[:200])


class PermanentError(Exception):
    pass


class TransientError(Exception):
    pass


def precheck(email, lead):
    """Return None if OK, else (status, reason). Every guard lives here."""
    if lead["status"] in ("opted_out", "bounced"):
        return "blocked", f"lead is {lead['status']}"
    if db.one("SELECT 1 x FROM optouts WHERE email=?", (lead["email"],)):
        return "blocked", "address is on the opt-out list"
    if not EMAIL_RE.match(lead["email"]):
        return "blocked", "invalid email address"
    if email["status"] not in ("approved", "sending"):
        return "skip", "not approved"
    dup = db.one("SELECT id FROM emails WHERE lead_id=? AND step=? AND status='sent' AND id<>?", (lead["id"], email["step"], email["id"]))
    if dup:
        return "blocked", "duplicate: this step was already sent to this lead"
    if email["step"] > 0:
        if db.one("SELECT 1 x FROM replies WHERE lead_id=? AND classification NOT IN ('out_of_office','bounce')", (lead["id"],)):
            return "blocked", "lead already replied"
    if config.get("TEST_MODE") and config.get("SEND_MODE") == "smtp":
        if not config.test_allowlist():
            return "blocked", "TEST_MODE is on but TEST_ALLOWLIST is empty (add your authorised test addresses in .env)"
        if not is_allowed_test_recipient(lead["email"]):
            return "blocked", "TEST_MODE: recipient is not on the authorised test allowlist"
    return None


def send_one(email_id):
    """Atomically claim and send a single approved email. Returns (status, detail)."""
    _, claimed = db.execute("UPDATE emails SET status='sending' WHERE id=? AND status='approved'", (email_id,))
    if not claimed:
        return "skipped", "not in approved state (already processed?)"
    email = db.one("SELECT * FROM emails WHERE id=?", (email_id,))
    lead = db.one("SELECT * FROM leads WHERE id=?", (email["lead_id"],))
    chk = precheck(email, lead)
    if chk:
        status, reason = chk
        db.execute("UPDATE emails SET status=?, error=? WHERE id=?", ("blocked" if status == "blocked" else "approved", reason, email_id))
        db.log_event(lead["id"], email_id, "blocked", reason)
        return "blocked", reason
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            msg, mid = build_message(email, lead)
            via = _deliver(msg)
            db.execute("UPDATE emails SET status='sent', sent_at=?, sent_day=?, message_id=?, attempts=?, error=NULL WHERE id=?",
                       (db.now(), local_day(), mid, attempt, email_id))
            db.execute("UPDATE leads SET status='sent' WHERE id=? AND status NOT IN ('replied','opted_out','bounced')", (lead["id"],))
            db.log_event(lead["id"], email_id, "sent", via)
            scoring.rescore(lead["id"])
            return "sent", via
        except FatalSendError:
            db.execute("UPDATE emails SET status='approved' WHERE id=?", (email_id,))
            raise
        except PermanentError as e:
            db.execute("UPDATE emails SET status='failed', error=?, attempts=? WHERE id=?", (str(e), attempt, email_id))
            db.log_event(lead["id"], email_id, "failed", str(e))
            return "failed", str(e)
        except TransientError as e:
            last = str(e)
            db.execute("UPDATE emails SET attempts=?, error=? WHERE id=?", (attempt, last, email_id))
            time.sleep(min(2 ** attempt, 8))
    db.execute("UPDATE emails SET status='failed', error=? WHERE id=?", (f"gave up after {MAX_ATTEMPTS} attempts: {last}", email_id))
    db.log_event(lead["id"], email_id, "failed", last)
    return "failed", last


def send_test_copy(email_id, to_addr):
    """Send a preview of a draft to an authorised test address; does NOT mark the email as sent."""
    to_addr = (to_addr or "").strip()
    if not EMAIL_RE.match(to_addr):
        raise ValueError("Invalid test address")
    if config.get("SEND_MODE") == "smtp" and not is_allowed_test_recipient(to_addr):
        raise ValueError("That address is not in TEST_ALLOWLIST (.env). Only authorised test addresses are allowed.")
    email = db.one("SELECT * FROM emails WHERE id=?", (email_id,))
    lead = db.one("SELECT * FROM leads WHERE id=?", (email["lead_id"],))
    msg, _ = build_message({**email, "message_id": None}, lead, to_addr=to_addr, subject_prefix="[TEST] ")
    try:
        via = _deliver(msg)
    except (PermanentError, TransientError) as e:
        raise ValueError(str(e))
    db.log_event(lead["id"], email_id, "test_sent", f"{to_addr} via {via}")
    return via


def run_batch(limit=None, progress=None, should_stop=lambda: False):
    """Send approved emails up to today's remaining quota."""
    quota = remaining_today()
    if limit:
        quota = min(quota, int(limit))
    queue = db.rows("SELECT id FROM emails WHERE status='approved' ORDER BY step, id LIMIT ?", (max(quota, 0),))
    result = {"quota_left_before": remaining_today(), "attempted": 0, "sent": 0, "failed": 0, "blocked": 0, "skipped": 0, "aborted": None}
    delay = config.get("SEND_DELAY_SECONDS")
    for i, row in enumerate(queue):
        if should_stop():
            result["aborted"] = "stopped"
            break
        try:
            status, detail = send_one(row["id"])
        except FatalSendError as e:
            result["aborted"] = str(e)
            break
        result["attempted"] += 1
        result[{"sent": "sent", "failed": "failed", "blocked": "blocked"}.get(status, "skipped")] += 1
        if progress:
            progress(i + 1, len(queue), f"{status}: {detail}")
        if status == "sent" and i < len(queue) - 1 and delay:
            time.sleep(delay)
    left_unsent = db.one("SELECT COUNT(*) c FROM emails WHERE status='approved'")["c"]
    result["still_queued"] = left_unsent
    result["quota_left_after"] = remaining_today()
    return result
