"""Lead scoring (0-100): fit + opportunity + seniority + data quality + engagement."""
import json
import re

from . import config, db

ROLE_LOCALPARTS = {"info", "contact", "hello", "sales", "support", "admin", "office", "enquiries", "inquiries", "mail", "team", "noreply", "no-reply"}
FREE_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "proton.me", "protonmail.com"}


def seniority(designation):
    d = (designation or "").lower()
    if re.search(r"\b(ceo|cto|cio|coo|cfo|founder|co-founder|owner|president|managing director|chief|partner|principal)\b", d):
        return 15, "C-level / founder"
    if re.search(r"\b(vp|vice president|director|head)\b", d):
        return 12, "Director / head"
    if re.search(r"\b(manager|lead|senior)\b", d):
        return 8, "Manager / lead"
    return (4, "Individual contributor") if d else (2, "Unknown role")


def rescore(lead_id):
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        return None
    from .research import get_research
    res = get_research(lead_id)
    parts = []
    # --- industry fit (25)
    fit = 0
    if res and res.get("industry_detail"):
        key = (res["industry_detail"] or {}).get("key")
        targets = config.company_profile().get("target_industries", [])
        if key in targets:
            fit = 25
            parts.append(("Target industry", 25, res["industry"]))
        elif key:
            fit = 12
            parts.append(("Adjacent industry", 12, res["industry"]))
    # --- opportunities (30)
    opp = 0
    if res and res.get("opportunities"):
        ops = res["opportunities"]
        opp = min(30, sum(o["strength"] * 4 for o in ops[:3]) + (4 if len(ops) >= 2 else 0))
        parts.append(("Service opportunities", opp, f"{len(ops)} found"))
    # --- seniority (15)
    sen, sen_label = seniority(lead.get("designation"))
    parts.append(("Decision-maker level", sen, sen_label))
    # --- data quality (15)
    dq = 0
    conf = (res or {}).get("confidence") or 0
    dq += int(10 * conf)
    local, _, domain = lead["email"].partition("@")
    if local.lower() in ROLE_LOCALPARTS:
        dq -= 3
    elif domain.lower() not in FREE_DOMAINS:
        dq += 3
    if lead.get("name"):
        dq += 2
    dq = max(0, min(15, dq))
    parts.append(("Research & contact quality", dq, f"confidence {conf:.0%}"))
    # --- engagement (15)
    ev = db.rows("SELECT type, COUNT(*) c FROM events WHERE lead_id=? GROUP BY type", (lead_id,))
    cnt = {e["type"]: e["c"] for e in ev}
    eng = min(6, 2 * cnt.get("open", 0)) + min(4, 2 * cnt.get("click", 0))
    rep = db.one("SELECT classification FROM replies WHERE lead_id=? ORDER BY id DESC LIMIT 1", (lead_id,))
    if rep:
        eng = {"positive": 15, "question": 12, "neutral": 8, "negative": 0, "out_of_office": 4, "unsubscribe": 0, "bounce": 0}.get(rep["classification"], 5)
    if eng:
        parts.append(("Engagement", eng, ("replied: " + rep["classification"]) if rep else f"{cnt.get('open',0)} open(s)"))
    total = fit + opp + sen + dq + eng
    if rep and rep["classification"] in ("unsubscribe", "negative", "bounce"):
        total = min(total, 20)
    total = max(0, min(100, total))
    label = "hot" if total >= 70 else "warm" if total >= 45 else "cold"
    detail = [{"factor": f, "points": p, "note": n} for f, p, n in parts]
    db.execute("UPDATE leads SET score=?, score_label=?, score_detail=? WHERE id=?", (total, label, json.dumps(detail), lead_id))
    return total
