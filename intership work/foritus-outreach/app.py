"""ForITus Outreach Desk – Flask app (API + UI)."""
import csv
import io
import ipaddress
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from flask import Flask, Response, abort, jsonify, render_template, request

from core import config, db, followups, generator, ingest, llm, quality, replies, research, scoring, sender
from core.config import BASE_DIR, env

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
db.init()

PUBLIC_PREFIXES = ("/t/", "/u/", "/static/")


# --------------------------------------------------------------------------- safety: admin is local-only
@app.before_request
def guard_admin():
    if request.path.startswith(PUBLIC_PREFIXES):
        return
    if env("ALLOW_REMOTE_ADMIN", "").lower() in ("1", "true"):
        return
    # Behind a tunnel (ngrok / cloudflared) requests carry forwarded headers: only /t and /u may be public.
    if request.headers.get("X-Forwarded-For") or request.headers.get("Forwarded") or request.headers.get("CF-Connecting-IP"):
        abort(403)
    try:
        if not ipaddress.ip_address(request.remote_addr or "127.0.0.1").is_loopback:
            abort(403)
    except ValueError:
        abort(403)


# --------------------------------------------------------------------------- background jobs
JOBS = {}
_job_lock = threading.Lock()
_running = {}


def start_job(kind, fn, total=0, exclusive=False):
    with _job_lock:
        if exclusive and _running.get(kind) and JOBS[_running[kind]]["status"] == "running":
            return JOBS[_running[kind]]
        jid = uuid.uuid4().hex[:10]
        job = {"id": jid, "kind": kind, "status": "running", "total": total, "done": 0, "log": [], "result": None, "started": time.time(), "stop": False}
        JOBS[jid] = job
        _running[kind] = jid

    def progress(done, tot=None, msg=""):
        job["done"] = done
        if tot is not None:
            job["total"] = tot
        if msg:
            job["log"].append(msg)
            job["log"] = job["log"][-60:]

    def runner():
        try:
            job["result"] = fn(job, progress)
            job["status"] = "done"
        except Exception as e:  # surface to UI
            job["status"] = "error"
            job["log"].append(f"ERROR: {e}")
            job["result"] = {"error": str(e)}

    threading.Thread(target=runner, daemon=True).start()
    return job


def job_view(j):
    return {k: j[k] for k in ("id", "kind", "status", "total", "done", "log", "result")}


@app.get("/api/jobs/<jid>")
def get_job(jid):
    j = JOBS.get(jid)
    return jsonify(job_view(j)) if j else (jsonify(error="unknown job"), 404)


@app.post("/api/jobs/<jid>/stop")
def stop_job(jid):
    j = JOBS.get(jid)
    if j:
        j["stop"] = True
    return jsonify(ok=True)


# --------------------------------------------------------------------------- helpers
def _jl(v, default=None):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def ser_email(e, full=True):
    e = dict(e)
    e["quality"] = _jl(e.get("quality"), {})
    e["facts_used"] = _jl(e.get("facts_used"), [])
    if not full:
        e.pop("body", None)
    return e


def ser_lead(l):
    l = dict(l)
    l["score_detail"] = _jl(l.get("score_detail"), [])
    return l


def ids_from_request(table="leads", default_status=None):
    data = request.get_json(silent=True) or {}
    if data.get("all"):
        sql = f"SELECT id FROM {table}"
        args = ()
        if default_status:
            sql += " WHERE status IN (%s)" % ",".join("?" * len(default_status))
            args = tuple(default_status)
        return [r["id"] for r in db.rows(sql, args)], data
    return [int(i) for i in data.get("ids", [])], data


# --------------------------------------------------------------------------- UI
@app.get("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------- state / dashboard
@app.get("/api/state")
def state():
    leads = db.rows("SELECT status, COUNT(*) c FROM leads GROUP BY status")
    lead_counts = {r["status"]: r["c"] for r in leads}
    emails = db.rows("SELECT status, COUNT(*) c FROM emails GROUP BY status")
    email_counts = {r["status"]: r["c"] for r in emails}
    researched = db.one("SELECT COUNT(*) c FROM research")["c"]
    total_leads = db.one("SELECT COUNT(*) c FROM leads")["c"]
    opens = db.one("SELECT COUNT(DISTINCT email_id) c FROM events WHERE type='open'")["c"]
    replied = db.one("SELECT COUNT(DISTINCT lead_id) c FROM replies WHERE classification NOT IN ('out_of_office','bounce')")["c"]
    pos = db.one("SELECT COUNT(DISTINCT lead_id) c FROM replies WHERE classification IN ('positive','question')")["c"]
    sent_total = email_counts.get("sent", 0)
    # 14-day series
    series = []
    for i in range(13, -1, -1):
        d = (datetime.now().astimezone() - timedelta(days=i)).strftime("%Y-%m-%d")
        s = db.one("SELECT COUNT(*) c FROM emails WHERE status='sent' AND sent_day=?", (d,))["c"]
        o = db.one("SELECT COUNT(DISTINCT email_id) c FROM events WHERE type='open' AND substr(ts,1,10)=?", (d,))["c"]
        r = db.one("SELECT COUNT(*) c FROM replies WHERE substr(ts,1,10)=?", (d,))["c"]
        series.append({"day": d, "sent": s, "opens": o, "replies": r})
    recent = db.rows(
        "SELECT ev.id, ev.type, ev.meta, ev.ts, l.company, l.name FROM events ev LEFT JOIN leads l ON l.id=ev.lead_id "
        "WHERE ev.type NOT IN ('llm_fallback') ORDER BY ev.id DESC LIMIT 14")
    scores = db.rows("SELECT score_label l, COUNT(*) c FROM leads GROUP BY score_label")
    smtp = config.smtp_config()
    imap = config.imap_config()
    return jsonify({
        "leads": {"total": total_leads, "by_status": lead_counts, "researched": researched,
                  "drafted": db.one("SELECT COUNT(DISTINCT lead_id) c FROM emails")["c"]},
        "emails": email_counts,
        "quota": {"limit": config.get("DAILY_LIMIT"), "sent_today": sender.sent_today(), "remaining": sender.remaining_today()},
        "tracking": {"sent": sent_total, "opened": opens, "open_rate": round(opens / sent_total, 3) if sent_total else 0,
                     "replied": replied, "positive": pos, "reply_rate": round(replied / sent_total, 3) if sent_total else 0,
                     "optouts": db.one("SELECT COUNT(*) c FROM optouts")["c"]},
        "scores": {r["l"]: r["c"] for r in scores},
        "series": series, "recent": recent,
        "config": {
            "llm": llm.label(), "llm_available": llm.available(),
            "send_mode": config.get("SEND_MODE"), "smtp_configured": bool(smtp["host"] and smtp["from_addr"]),
            "imap_configured": bool(imap["host"] and imap["user"]),
            "test_mode": config.get("TEST_MODE"), "test_allowlist": len(config.test_allowlist()),
            "followups": followups.schedule_days(), "tunables": config.all_tunables(),
            "services": {k: v["label"] for k, v in config.company_profile()["services"].items()},
        },
        "due_followups": len(followups.due()),
    })


# --------------------------------------------------------------------------- leads
@app.post("/api/leads/import")
def leads_import():
    try:
        if request.files.get("file"):
            f = request.files["file"]
            rows = ingest.read_table(f.filename, f.read())
            src = f.filename
        else:
            data = request.get_json(silent=True) or {}
            if data.get("sheet_url"):
                rows = ingest.fetch_google_sheet(data["sheet_url"])
                src = "google-sheet"
            elif data.get("sample"):
                rows = ingest.read_table("sample.csv", (BASE_DIR / "sample_leads.csv").read_bytes())
                src = "sample"
            else:
                return jsonify(error="Provide a CSV/XLSX file, a Google Sheet link, or sample=true"), 400
        return jsonify(ingest.import_rows(rows, src))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"Import failed: {e}"), 400


@app.get("/api/leads")
def leads_list():
    q = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status")
    sql = ("SELECT l.*, r.status AS research_status, r.industry AS industry, r.confidence AS confidence, "
           "(SELECT COUNT(*) FROM emails e WHERE e.lead_id=l.id) AS email_count, "
           "(SELECT status FROM emails e WHERE e.lead_id=l.id ORDER BY step DESC LIMIT 1) AS last_email_status "
           "FROM leads l LEFT JOIN research r ON r.lead_id=l.id WHERE 1=1")
    args = []
    if status:
        sql += " AND l.status=?"
        args.append(status)
    if q:
        sql += " AND (lower(l.name) LIKE ? OR lower(l.company) LIKE ? OR lower(l.email) LIKE ? OR lower(l.country) LIKE ?)"
        args += [f"%{q}%"] * 4
    sql += " ORDER BY l.score DESC, l.id DESC"
    return jsonify([ser_lead(r) for r in db.rows(sql, tuple(args))])


@app.get("/api/leads/<int:lid>")
def lead_detail(lid):
    l = db.one("SELECT * FROM leads WHERE id=?", (lid,))
    if not l:
        return jsonify(error="not found"), 404
    return jsonify({
        "lead": ser_lead(l), "research": research.get_research(lid),
        "emails": [ser_email(e) for e in db.rows("SELECT * FROM emails WHERE lead_id=? ORDER BY step", (lid,))],
        "events": db.rows("SELECT * FROM events WHERE lead_id=? ORDER BY id DESC LIMIT 40", (lid,)),
        "replies": db.rows("SELECT * FROM replies WHERE lead_id=? ORDER BY id DESC", (lid,)),
    })


@app.delete("/api/leads/<int:lid>")
def lead_delete(lid):
    db.execute("DELETE FROM events WHERE lead_id=?", (lid,))
    db.execute("DELETE FROM replies WHERE lead_id=?", (lid,))
    db.execute("DELETE FROM leads WHERE id=?", (lid,))
    return jsonify(ok=True)


@app.post("/api/leads/rescore")
def leads_rescore():
    for l in db.rows("SELECT id FROM leads"):
        scoring.rescore(l["id"])
    return jsonify(ok=True)


# --------------------------------------------------------------------------- research & generation jobs
@app.post("/api/research")
def api_research():
    ids, data = ids_from_request("leads")
    force = bool(data.get("force"))
    ids = [i for i in ids if (db.one("SELECT status FROM leads WHERE id=?", (i,)) or {}).get("status") not in ("opted_out", "bounced")]
    if not force:
        ids = [i for i in ids if not db.one("SELECT 1 x FROM research WHERE lead_id=? AND status IN ('ok','partial')", (i,))]

    def work(job, progress):
        stats = {"ok": 0, "partial": 0, "failed": 0}
        lock = threading.Lock()

        def one(i):
            if job["stop"]:
                return
            lead = db.one("SELECT company FROM leads WHERE id=?", (i,))
            try:
                r = research.research_lead(i, force=force)
                st = r["status"]
            except Exception as e:
                st = "failed"
            with lock:
                stats[st] = stats.get(st, 0) + 1
                progress(sum(stats.values()), len(ids), f"{lead['company'] if lead else i}: {st}")
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(one, ids))
        return stats
    return jsonify(job_view(start_job("research", work, len(ids))))


@app.post("/api/generate")
def api_generate():
    ids, data = ids_from_request("leads")
    step = int(data.get("step", 0))
    force = bool(data.get("force"))
    ids = [i for i in ids if (db.one("SELECT status FROM leads WHERE id=?", (i,)) or {}).get("status") not in ("opted_out", "bounced")]

    def work(job, progress):
        stats = {"drafted": 0, "errors": 0}
        for n, i in enumerate(ids, 1):
            if job["stop"]:
                break
            lead = db.one("SELECT company FROM leads WHERE id=?", (i,))
            try:
                generator.generate_for_lead(i, step=step, force=force)
                stats["drafted"] += 1
                progress(n, len(ids), f"{lead['company']}: drafted")
            except Exception as e:
                stats["errors"] += 1
                progress(n, len(ids), f"{lead['company']}: {e}")
        return stats
    return jsonify(job_view(start_job("generate", work, len(ids))))


# --------------------------------------------------------------------------- emails (review / approval)
@app.get("/api/emails")
def emails_list():
    status = request.args.get("status")
    sql = ("SELECT e.*, l.name, l.company, l.email AS to_email, l.country, l.designation, l.score FROM emails e "
           "JOIN leads l ON l.id=e.lead_id WHERE 1=1")
    args = []
    if status:
        sts = status.split(",")
        sql += " AND e.status IN (%s)" % ",".join("?" * len(sts))
        args += sts
    sql += " ORDER BY e.id DESC LIMIT 1000"
    return jsonify([ser_email(e, full=False) for e in db.rows(sql, tuple(args))])


@app.get("/api/emails/<int:eid>")
def email_detail(eid):
    e = db.one("SELECT e.*, l.name, l.company, l.email AS to_email, l.country, l.designation FROM emails e JOIN leads l ON l.id=e.lead_id WHERE e.id=?", (eid,))
    if not e:
        return jsonify(error="not found"), 404
    res = research.get_research(e["lead_id"])
    out = ser_email(e)
    out["facts"] = [f for f in (res or {}).get("facts", []) if f["id"] in out["facts_used"]]
    out["all_facts"] = (res or {}).get("facts", [])
    out["research_status"] = (res or {}).get("status")
    return jsonify(out)


@app.patch("/api/emails/<int:eid>")
def email_edit(eid):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e:
        return jsonify(error="not found"), 404
    if e["status"] in ("sent", "sending"):
        return jsonify(error="Already sent; cannot edit."), 400
    data = request.get_json(silent=True) or {}
    subj = (data.get("subject", e["subject"]) or "").strip()
    body = data.get("body", e["body"]) or ""
    db.execute("UPDATE emails SET subject=?, body=?, status='draft', approved_at=NULL WHERE id=?", (subj, body, eid))
    q = generator.reverify(eid)
    return jsonify(quality=q)


@app.post("/api/emails/<int:eid>/approve")
def email_approve(eid):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e:
        return jsonify(error="not found"), 404
    if e["status"] not in ("draft", "failed", "blocked"):
        return jsonify(error=f"Cannot approve an email that is {e['status']}."), 400
    lead = db.one("SELECT * FROM leads WHERE id=?", (e["lead_id"],))
    if lead["status"] in ("opted_out", "bounced"):
        return jsonify(error="Lead is opted out / bounced."), 400
    q = generator.reverify(eid)
    override = bool((request.get_json(silent=True) or {}).get("override"))
    if q["blocking"]:
        return jsonify(error="Blocked by critical quality issues: " + "; ".join(i["msg"] for i in q["issues"] if i["severity"] == "critical"), quality=q), 400
    if q["score"] < config.get("MIN_QUALITY_TO_APPROVE") and not override:
        return jsonify(error=f"Quality score {q['score']} is below the minimum ({config.get('MIN_QUALITY_TO_APPROVE')}). Edit the draft or approve with override.", quality=q, can_override=True), 400
    db.execute("UPDATE emails SET status='approved', approved_at=?, error=NULL, attempts=0 WHERE id=?", (db.now(), eid))
    db.execute("UPDATE leads SET status='approved' WHERE id=? AND status IN ('new','researched','drafted')", (lead["id"],))
    db.log_event(lead["id"], eid, "approved", "")
    return jsonify(ok=True)


@app.post("/api/emails/approve-all")
def email_approve_all():
    data = request.get_json(silent=True) or {}
    min_q = int(data.get("min_score", config.get("MIN_QUALITY_TO_APPROVE")))
    n = skipped = 0
    for e in db.rows("SELECT id FROM emails WHERE status='draft'"):
        q = generator.reverify(e["id"])
        unverified = any(i["code"] == "unverified" for i in q["issues"])  # no website research -> needs a human look
        if q["blocking"] or q["score"] < min_q or unverified:
            skipped += 1
            continue
        db.execute("UPDATE emails SET status='approved', approved_at=? WHERE id=?", (db.now(), e["id"]))
        em = db.one("SELECT lead_id FROM emails WHERE id=?", (e["id"],))
        db.execute("UPDATE leads SET status='approved' WHERE id=? AND status IN ('new','researched','drafted')", (em["lead_id"],))
        db.log_event(em["lead_id"], e["id"], "approved", "bulk")
        n += 1
    return jsonify(approved=n, skipped=skipped)


@app.post("/api/emails/<int:eid>/reject")
def email_reject(eid):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e or e["status"] in ("sent", "sending"):
        return jsonify(error="cannot reject"), 400
    db.execute("UPDATE emails SET status='rejected' WHERE id=?", (eid,))
    db.log_event(e["lead_id"], eid, "rejected", "")
    return jsonify(ok=True)


@app.post("/api/emails/<int:eid>/unapprove")
def email_unapprove(eid):
    db.execute("UPDATE emails SET status='draft', approved_at=NULL WHERE id=? AND status='approved'", (eid,))
    return jsonify(ok=True)


@app.post("/api/emails/<int:eid>/regenerate")
def email_regen(eid):
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e or e["status"] in ("sent", "sending"):
        return jsonify(error="cannot regenerate"), 400
    variant = int((request.get_json(silent=True) or {}).get("variant", int(time.time()) % 1000))
    try:
        generator.generate_for_lead(e["lead_id"], step=e["step"], force=True, variant=variant)
    except Exception as ex:
        return jsonify(error=str(ex)), 400
    return jsonify(ok=True)


@app.post("/api/emails/<int:eid>/test-send")
def email_test_send(eid):
    to = (request.get_json(silent=True) or {}).get("to", "")
    try:
        via = sender.send_test_copy(eid, to)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True, via=via)


@app.post("/api/emails/<int:eid>/retry")
def email_retry(eid):
    db.execute("UPDATE emails SET status='approved', error=NULL, attempts=0 WHERE id=? AND status IN ('failed','blocked')", (eid,))
    return jsonify(ok=True)


@app.get("/api/emails/<int:eid>/render")
def email_render(eid):
    """Rendered HTML. ?as=recipient includes the tracking pixel (simulates the recipient opening the delivered mail)."""
    e = db.one("SELECT * FROM emails WHERE id=?", (eid,))
    if not e:
        abort(404)
    lead = db.one("SELECT * FROM leads WHERE id=?", (e["lead_id"],))
    preview = request.args.get("as") != "recipient"
    _, doc = sender.render(e, lead, preview=preview)
    return Response(doc, mimetype="text/html")


# --------------------------------------------------------------------------- sending
@app.post("/api/send")
def api_send():
    data = request.get_json(silent=True) or {}
    limit = data.get("limit")

    def work(job, progress):
        return sender.run_batch(limit, progress, should_stop=lambda: job["stop"])
    return jsonify(job_view(start_job("send", work, 0, exclusive=True)))


@app.get("/api/history")
def history():
    rows = db.rows(
        "SELECT e.id, e.step, e.subject, e.status, e.error, e.attempts, e.sent_at, e.created_at, e.generator, e.region, e.quality_score, "
        "l.name, l.company, l.email AS to_email, l.country, "
        "(SELECT COUNT(*) FROM events ev WHERE ev.email_id=e.id AND ev.type='open') AS opens, "
        "(SELECT classification FROM replies r WHERE r.email_id=e.id ORDER BY r.id DESC LIMIT 1) AS reply "
        "FROM emails e JOIN leads l ON l.id=e.lead_id WHERE e.status IN ('sent','failed','blocked','sending') ORDER BY COALESCE(e.sent_at, e.created_at) DESC LIMIT 1000")
    return jsonify(rows)


@app.get("/api/history.csv")
def history_csv():
    rows = history().get_json()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sent_at", "status", "step", "name", "company", "email", "country", "subject", "opens", "reply", "attempts", "error"])
    for r in rows:
        w.writerow([r["sent_at"], r["status"], r["step"], r["name"], r["company"], r["to_email"], r["country"], r["subject"], r["opens"], r["reply"], r["attempts"], r["error"]])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=send_history.csv"})


# --------------------------------------------------------------------------- follow-ups
@app.get("/api/followups/due")
def fu_due():
    return jsonify(followups.due(force=request.args.get("force") == "1"))


@app.post("/api/followups/plan")
def fu_plan():
    force = bool((request.get_json(silent=True) or {}).get("force"))
    return jsonify(followups.plan(force))


# --------------------------------------------------------------------------- opt-outs
@app.get("/api/optouts")
def optouts_list():
    return jsonify(db.rows("SELECT * FROM optouts ORDER BY created_at DESC"))


@app.post("/api/optouts")
def optouts_add():
    data = request.get_json(silent=True) or {}
    em = (data.get("email") or "").strip().lower()
    if not ingest.EMAIL_RE.match(em):
        return jsonify(error="Invalid email"), 400
    replies.add_optout(em, data.get("reason", "added manually"), "manual")
    return jsonify(ok=True)


@app.delete("/api/optouts/<path:addr>")
def optouts_del(addr):
    replies.remove_optout(addr)
    return jsonify(ok=True)


# --------------------------------------------------------------------------- replies
@app.get("/api/replies")
def replies_list():
    return jsonify(db.rows(
        "SELECT r.*, l.company, l.name FROM replies r LEFT JOIN leads l ON l.id=r.lead_id ORDER BY r.id DESC LIMIT 200"))


@app.post("/api/replies/check")
def replies_check():
    try:
        return jsonify(replies.check_imap())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"IMAP check failed: {e}"), 400


@app.post("/api/replies/manual")
def replies_manual():
    d = request.get_json(silent=True) or {}
    cls = replies.record_reply(d.get("from", ""), d.get("subject", "Re:"), d.get("body", ""))
    if not cls:
        return jsonify(error="No lead with that address."), 400
    return jsonify(classification=cls)


# --------------------------------------------------------------------------- settings
@app.get("/api/settings")
def settings_get():
    return jsonify(config.all_tunables())


@app.put("/api/settings")
def settings_put():
    data = request.get_json(silent=True) or {}
    errs = {}
    for k, v in data.items():
        try:
            config.set_tunable(k, v)
        except Exception as e:
            errs[k] = str(e)
    if errs:
        return jsonify(error="Invalid value", fields=errs), 400
    return jsonify(config.all_tunables())


@app.post("/api/reset")
def reset():
    if (request.get_json(silent=True) or {}).get("confirm") != "RESET":
        return jsonify(error="confirm required"), 400
    for t in ("events", "replies", "emails", "research", "leads", "optouts"):
        db.execute(f"DELETE FROM {t}")
    return jsonify(ok=True)


# --------------------------------------------------------------------------- tracking (PUBLIC endpoints)
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,"
       b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


@app.get("/t/o/<token>.gif")
def track_open(token):
    e = db.one("SELECT id, lead_id, status FROM emails WHERE token=?", (token,))
    if e and e["status"] == "sent":
        db.log_event(e["lead_id"], e["id"], "open", request.headers.get("User-Agent", "")[:120])
        scoring.rescore(e["lead_id"])
    return Response(GIF, mimetype="image/gif", headers={"Cache-Control": "no-store, max-age=0"})


UNSUB_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Unsubscribe</title><body style="font-family:system-ui,sans-serif;max-width:460px;margin:12vh auto;padding:0 20px;color:#222">
<h2 style="margin:0 0 8px">{title}</h2><p style="color:#555;line-height:1.5">{text}</p>{form}</body>"""


@app.route("/u/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    e = db.one("SELECT e.id, e.lead_id, l.email FROM emails e JOIN leads l ON l.id=e.lead_id WHERE e.token=?", (token,))
    if not e:
        return Response(UNSUB_PAGE.format(title="Link not recognised", text="This unsubscribe link is invalid or expired.", form=""), 404)
    if request.method == "POST":  # confirmation click, or RFC 8058 one-click
        replies.add_optout(e["email"], "unsubscribe link", "link")
        return Response(UNSUB_PAGE.format(title="You're unsubscribed", text=f"{e['email']} will not receive further emails from us.", form=""))
    already = db.one("SELECT 1 x FROM optouts WHERE email=?", (e["email"],))
    if already:
        return Response(UNSUB_PAGE.format(title="Already unsubscribed", text=f"{e['email']} is on our do-not-contact list.", form=""))
    form = '<form method=post><button style="background:#111;color:#fff;border:0;padding:11px 18px;border-radius:8px;font-size:15px;cursor:pointer">Confirm unsubscribe</button></form>'
    return Response(UNSUB_PAGE.format(title="Unsubscribe", text=f"Stop emails to {e['email']}?", form=form))


if __name__ == "__main__":
    host = env("HOST", "127.0.0.1")
    port = int(env("PORT", "5000"))
    print(f"\n  ForITus Outreach Desk -> http://{host}:{port}\n")
    app.run(host=host, port=port, debug=False, threaded=True)
