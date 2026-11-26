"""Email quality verification: deliverability, personalisation, grounding (anti-fabrication), language, uniqueness."""
import re

from . import db

SIGNOFF_RE = re.compile(
    r"^(best regards|kind regards|warm regards|regards|sincerely|cheers|best|thanks|thank you|"
    r"mit freundlichen gr[uü](ß|ss)en|beste gr[uü](ß|ss)e|viele gr[uü](ß|ss)e|freundliche gr[uü](ß|ss)e|"
    r"cordialement|bien cordialement|salutations|cordialement vôtre|"
    r"saludos|un saludo|atentamente|cordiales saludos|saludos cordiales),?\s*$", re.I | re.M)

SPAM_WORDS = ["free", "guarantee", "act now", "limited time", "buy now", "click here", "100%", "winner", "urgent",
              "cheap", "no obligation", "risk-free", "risk free", "$$$", "make money", "once in a lifetime", "exclusive deal"]
FABRICATION = [
    "congratulations on", "congrats on", "i saw you recently", "recently launched", "recently raised",
    "your recent", "just announced", "i read your recent", "your latest", "saw your post", "your linkedin",
    "your podcast", "your article", "i came across your profile", "noticed your recent",
    "we helped", "we have helped", "our clients", "case study", "trusted by", "we've worked with",
    "we have worked with", "we worked with", "proven", "roi of", "increase of", "% increase", "% more", "% faster",
]
STOPWORDS = {
    "en": {"the", "and", "to", "of", "a", "in", "for", "is", "with", "your", "you", "we"},
    "de": {"und", "der", "die", "das", "ihr", "ihre", "sie", "mit", "für", "ist", "wir", "ein", "eine"},
    "fr": {"le", "la", "les", "et", "vous", "votre", "pour", "avec", "nous", "une", "un", "des", "est"},
    "es": {"el", "la", "los", "y", "usted", "su", "para", "con", "nosotros", "una", "un", "es", "de"},
}


def split_body(body):
    """Return (core_text, tail). Core is everything before the sign-off line."""
    ms = list(SIGNOFF_RE.finditer(body or ""))
    if not ms:
        return (body or "").strip(), ""
    m = ms[-1]
    return body[:m.start()].strip(), body[m.start():]


def _words(t):
    return re.findall(r"[\w'’\-]+", t, re.U)


def _shingles(t, n=3):
    w = [x.lower() for x in _words(t)]
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def _first_name(name):
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p.lower().strip(".") not in ("mr", "mrs", "ms", "dr", "prof", "miss", "mx")]
    return parts[0] if parts else ""


def verify(subject, body, lead, research, facts_used=None, language="en", step=0, email_id=None):
    issues = []

    def add(sev, code, msg):
        issues.append({"severity": sev, "code": code, "msg": msg})

    subject = (subject or "").strip()
    body = body or ""
    core, tail = split_body(body)
    facts = (research or {}).get("facts") or []
    fact_ids = {f["id"] for f in facts}
    facts_used = [f for f in (facts_used or []) if f in fact_ids]

    # ---- structure & deliverability
    if not subject:
        add("critical", "subject_missing", "Subject line is empty.")
    elif len(subject) > 65:
        add("warn", "subject_long", f"Subject is {len(subject)} characters; keep under ~60 so it isn't cut off on mobile.")
    if subject and subject.isupper() and len(subject) > 4:
        add("warn", "subject_caps", "Subject is ALL CAPS, which looks spammy.")
    if re.search(r"[!?]{2,}", subject + core):
        add("warn", "punctuation", "Repeated punctuation (!! / ??) looks spammy.")
    if (subject + " " + core).count("!") > 1:
        add("warn", "exclaim", "More than one exclamation mark.")
    low = (subject + " " + core).lower()
    spam = [w for w in SPAM_WORDS if w in low]
    if spam:
        add("warn", "spam_words", "Spam-trigger words: " + ", ".join(spam))
    wc = len(_words(core))
    if wc < 45:
        add("warn", "too_short", f"Body is only {wc} words; add one concrete, relevant point.")
    elif wc > 170:
        add("warn", "too_long", f"Body is {wc} words; cold emails work best at ~70–130 words.")
    if re.search(r"https?://", core):
        add("info", "links", "Contains a link; plain text with no links usually lands better in cold outreach.")
    if "{{UNSUB_URL}}" not in body and "unsubscribe" not in body.lower() and "opt out" not in body.lower() \
            and "abmelden" not in body.lower() and "désinscri" not in body.lower() and "baja" not in body.lower():
        add("critical", "no_optout", "No opt-out line found.")
    if step == 0 and subject.lower().startswith(("re:", "fwd:", "fw:")):
        add("critical", "fake_reply", "Subject pretends to be a reply/forward.")

    # ---- placeholders
    ph = re.findall(r"\{\{(?!UNSUB_URL)[^}]*\}\}|\[[^\]]*(?:name|company|your|insert)[^\]]*\]|(?<!\{)\{[a-z_]+\}(?!\})", subject + "\n" + body, re.I)
    if ph:
        add("critical", "placeholder", "Unresolved placeholder(s): " + ", ".join(ph[:3]))

    # ---- personalisation
    fn = _first_name(lead.get("name"))
    if fn and fn.lower() not in core.lower():
        add("warn", "no_first_name", f"Does not address the recipient by name ({fn}).")
    company = (lead.get("company") or "").strip()
    if company and company.lower() not in (core + " " + subject).lower():
        add("warn", "no_company", f"Does not mention the company ({company}).")
    r_status = (research or {}).get("status")
    if r_status in ("ok", "partial"):
        if not facts_used:
            add("warn", "no_fact", "References no researched fact, so it reads generic.")
    else:
        add("info", "unverified", "Company website could not be analysed; email is intentionally light and makes no site-specific claims.")

    # ---- grounding / anti-fabrication
    for ph_ in FABRICATION:
        if ph_ in low:
            add("critical", "fabrication", f'Possible unsupported claim: "{ph_}". Only state things found in the research evidence.')
            break
    evidence_blob = " ".join(f["text"] for f in facts) + " " + " ".join(str(lead.get(k) or "") for k in ("name", "company", "designation", "website", "country"))
    scrub = re.sub(r"\b\d+\s*[-–]?\s*(?:minutes?|mins?|min|minuten|minutos?)\b|\b24\s*/\s*7\b", "", core, flags=re.I)
    scrub = re.sub(r"https?://\S+", "", scrub)
    for num in re.findall(r"\d[\d,.]*%?", scrub):
        n = num.strip(".,")
        if n and n not in evidence_blob:
            add("critical", "number", f'Number "{n}" is not backed by the research evidence (possible fabricated statistic).')
            break

    # ---- language
    lang = language if language in STOPWORDS else "en"
    ws = [w.lower() for w in _words(core)]
    if ws:
        ratio = sum(1 for w in ws if w in STOPWORDS[lang]) / len(ws)
        if ratio < 0.06 and wc > 30:
            add("warn", "language", f"Text doesn't look like natural {lang.upper()} (check language/region fit).")

    # ---- uniqueness vs other drafts
    try:
        others = db.rows("SELECT id, body FROM emails WHERE step=? AND id IS NOT ? ORDER BY id DESC LIMIT 300", (step, email_id))
        mine = _shingles(core)
        best = 0.0
        for o in others:
            oc, _ = split_body(o["body"] or "")
            sh = _shingles(oc)
            if not sh or not mine:
                continue
            j = len(mine & sh) / len(mine | sh)
            best = max(best, j)
        if best > 0.55:
            add("warn", "similar", f"Very similar to another draft ({int(best*100)}% overlap) — personalise further.")
    except Exception:
        pass

    penalty = {"critical": 35, "warn": 9, "info": 0}
    score = max(0, 100 - sum(penalty[i["severity"]] for i in issues))
    return {
        "score": score,
        "blocking": any(i["severity"] == "critical" for i in issues),
        "issues": issues,
        "stats": {"words": wc, "subject_chars": len(subject), "facts_used": len(facts_used)},
    }
