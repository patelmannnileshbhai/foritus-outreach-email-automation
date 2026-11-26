"""Automated follow-ups: for leads whose last email was sent N days ago with no reply / opt-out, create a follow-up DRAFT
(still goes through the same review -> approve -> send gate)."""
from datetime import datetime, timezone

from . import config, db, generator


def schedule_days():
    out = []
    for x in str(config.get("FOLLOWUP_DAYS")).split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out


def due(force=False):
    days = schedule_days()
    result = []
    leads = db.rows("SELECT * FROM leads WHERE status='sent'")
    now = datetime.now(timezone.utc)
    for lead in leads:
        if db.one("SELECT 1 x FROM optouts WHERE email=?", (lead["email"],)):
            continue
        if db.one("SELECT 1 x FROM replies WHERE lead_id=? AND classification NOT IN ('out_of_office','bounce')", (lead["id"],)):
            continue
        sent = db.rows("SELECT step, sent_at, status FROM emails WHERE lead_id=? ORDER BY step", (lead["id"],))
        done = [e for e in sent if e["status"] == "sent"]
        if not done:
            continue
        # don't stack a new draft if one is already pending
        if any(e["status"] in ("draft", "approved", "sending") for e in sent):
            continue
        last = done[-1]
        next_step = last["step"] + 1
        if next_step > len(days):
            continue
        age = (now - datetime.fromisoformat(last["sent_at"])).total_seconds() / 86400
        # wait `days[next_step-1]` days after the *first* email (cumulative) - measured from the last send for simplicity
        wait = days[next_step - 1] - (days[next_step - 2] if next_step > 1 else 0)
        if force or age >= wait:
            result.append({"lead_id": lead["id"], "step": next_step, "company": lead["company"], "age_days": round(age, 1), "wait_days": wait})
    return result


def plan(force=False):
    created = []
    for d in due(force):
        try:
            eid = generator.generate_for_lead(d["lead_id"], step=d["step"], force=False)
            created.append({**d, "email_id": eid})
        except Exception as e:
            created.append({**d, "error": str(e)})
    return created
