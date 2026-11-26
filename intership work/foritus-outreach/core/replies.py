"""Reply detection (IMAP polling or manual log) + classification + automatic opt-out / bounce handling."""
import email as emaillib
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parseaddr

from . import config, db, scoring

RULES = [
    ("bounce", r"mailer-daemon|postmaster|delivery status notification|undeliverable|delivery has failed|address not found|550 5\.1\.1"),
    ("out_of_office", r"out of office|automatic reply|auto-reply|autoreply|on leave|i am away|vacation|currently away|abwesenheit"),
    ("unsubscribe", r"\b(unsubscribe|opt[- ]?out|remove me|stop (emailing|sending|contacting)|do not contact|don't contact|take me off|no more emails)\b"),
    ("negative", r"\b(not interested|no thanks|no thank you|not relevant|not a fit|don't need|do not need|already have|not looking|decline)\b"),
    ("positive", r"\b(interested|sounds good|let's talk|lets talk|schedule|book a call|set up a (call|meeting)|send (me )?(more )?(info|details|a proposal|pricing)|pricing|quote|demo|available (on|next)|happy to chat|tell me more|yes please)\b"),
    ("question", r"\?"),
]


def classify(subject, body):
    text = f"{subject}\n{body}".lower()
    for label, pat in RULES:
        if re.search(pat, text):
            return label
    return "neutral"


def _find_email_for(from_addr, in_reply_to=None, refs=""):
    ids = [x for x in re.findall(r"<[^>]+>", f"{in_reply_to or ''} {refs or ''}")]
    for mid in ids:
        e = db.one("SELECT id, lead_id FROM emails WHERE message_id=?", (mid,))
        if e:
            return e
    lead = db.one("SELECT id FROM leads WHERE email=?", (from_addr.lower(),))
    if lead:
        e = db.one("SELECT id, lead_id FROM emails WHERE lead_id=? AND status='sent' ORDER BY step DESC LIMIT 1", (lead["id"],))
        return e or {"id": None, "lead_id": lead["id"]}
    return None


def record_reply(from_addr, subject, body, message_id=None, in_reply_to=None, refs=""):
    from_addr = from_addr.strip().lower()
    match = _find_email_for(from_addr, in_reply_to, refs)
    if not match:
        return None
    if message_id and db.one("SELECT 1 x FROM replies WHERE message_id=?", (message_id,)):
        return None
    cls = classify(subject, body)
    db.execute("INSERT INTO replies(lead_id,email_id,from_addr,subject,body,classification,message_id,ts) VALUES(?,?,?,?,?,?,?,?)",
               (match["lead_id"], match["id"], from_addr, subject[:200], body[:5000], cls, message_id, db.now()))
    db.log_event(match["lead_id"], match["id"], "reply", cls)
    lead = db.one("SELECT * FROM leads WHERE id=?", (match["lead_id"],))
    if cls == "unsubscribe" or cls == "negative" and re.search(r"\b(stop|remove)\b", body.lower()):
        add_optout(lead["email"], "reply: " + cls, "reply")
    elif cls == "bounce":
        db.execute("UPDATE leads SET status='bounced' WHERE id=?", (lead["id"],))
    elif cls != "out_of_office":
        db.execute("UPDATE leads SET status='replied' WHERE id=?", (lead["id"],))
        # cancel any queued follow-ups
        db.execute("UPDATE emails SET status='rejected', error='lead replied' WHERE lead_id=? AND step>0 AND status IN ('draft','approved')", (lead["id"],))
    scoring.rescore(lead["id"])
    return cls


def add_optout(email_addr, reason="", source="manual"):
    email_addr = email_addr.strip().lower()
    db.execute("INSERT OR IGNORE INTO optouts(email,reason,source,created_at) VALUES(?,?,?,?)", (email_addr, reason, source, db.now()))
    lead = db.one("SELECT id FROM leads WHERE email=?", (email_addr,))
    if lead:
        db.execute("UPDATE leads SET status='opted_out' WHERE id=?", (lead["id"],))
        db.execute("UPDATE emails SET status='rejected', error='opted out' WHERE lead_id=? AND status IN ('draft','approved')", (lead["id"],))
        db.log_event(lead["id"], None, "optout", f"{source}: {reason}")
        scoring.rescore(lead["id"])


def remove_optout(email_addr):
    email_addr = email_addr.strip().lower()
    db.execute("DELETE FROM optouts WHERE email=?", (email_addr,))
    db.execute("UPDATE leads SET status='new' WHERE email=? AND status='opted_out'", (email_addr,))


def _text_of(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    p = msg.get_payload(decode=True)
    return p.decode(msg.get_content_charset() or "utf-8", errors="replace") if p else ""


def check_imap(max_messages=100):
    cfg = config.imap_config()
    if not cfg["host"] or not cfg["user"]:
        raise ValueError("IMAP is not configured (IMAP_HOST / IMAP_USER / IMAP_PASS in .env). You can still log replies manually.")
    found = 0
    classes = {}
    M = imaplib.IMAP4_SSL(cfg["host"], cfg["port"])
    try:
        M.login(cfg["user"], cfg["password"])
        M.select("INBOX")
        typ, data = M.search(None, "UNSEEN")
        ids = data[0].split()[-max_messages:]
        for i in ids:
            typ, md = M.fetch(i, "(BODY.PEEK[])")
            msg = emaillib.message_from_bytes(md[0][1])
            frm = parseaddr(msg.get("From", ""))[1]
            subj = str(make_header(decode_header(msg.get("Subject", ""))))
            cls = record_reply(frm, subj, _text_of(msg), msg.get("Message-ID"), msg.get("In-Reply-To"), msg.get("References", ""))
            if cls:
                found += 1
                classes[cls] = classes.get(cls, 0) + 1
                M.store(i, "+FLAGS", "\\Seen")
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return {"scanned": len(ids), "matched": found, "classes": classes}
