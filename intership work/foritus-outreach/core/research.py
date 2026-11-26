"""Automated company research.

Pipeline: safe fetch (robots.txt respected, SSRF-guarded) -> extract text/signals ->
classify industry -> build EVIDENCE FACTS (each with source URL) -> map to ForITus
opportunities -> optional LLM refinement (strictly constrained to the evidence).

Everything that later ends up in an email must trace back to a fact id (F1, F2, ...)."""
import ipaddress
import json
import re
import socket
from collections import Counter
from datetime import datetime
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import db, llm
from .config import company_profile, env

UA = env("RESEARCH_USER_AGENT", "ForITusResearchBot/1.0 (company research for personalised outreach)")
MAX_BYTES = 1_500_000
TIMEOUT = 8
MAX_PAGES = 4

# --------------------------------------------------------------------------- safe fetching

def _allow_private():
    return env("ALLOW_PRIVATE_FETCH", "").lower() in ("1", "true", "yes")


def is_safe_url(url):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    if _allow_private():
        return True
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def safe_get(url, max_redirects=4):
    cur = url
    for _ in range(max_redirects + 1):
        if not is_safe_url(cur):
            raise ValueError("URL blocked (non-public address or bad scheme)")
        r = requests.get(cur, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.5"},
                         timeout=TIMEOUT, stream=True, allow_redirects=False)
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            cur = urljoin(cur, r.headers.get("location", ""))
            r.close()
            continue
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400:
            r.close()
            raise ValueError(f"HTTP {r.status_code}")
        if "html" not in ctype and "text" not in ctype and ctype:
            r.close()
            raise ValueError(f"Not an HTML page ({ctype})")
        buf = b""
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > MAX_BYTES:
                break
        r.close()
        enc = r.encoding or "utf-8"
        return cur, buf.decode(enc, errors="replace")
    raise ValueError("Too many redirects")


def robots_allows(base_url, path_url):
    rp = robotparser.RobotFileParser()
    try:
        root = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
        if not is_safe_url(root):
            return False
        r = requests.get(root + "/robots.txt", headers={"User-Agent": UA}, timeout=5)
        if r.status_code >= 400:
            return True  # no robots.txt => allowed
        rp.parse(r.text.splitlines())
        return rp.can_fetch(UA, path_url) or rp.can_fetch("*", path_url)
    except Exception:
        return True


# --------------------------------------------------------------------------- extraction

GENERIC_HEADINGS = {
    "home", "about", "about us", "contact", "contact us", "menu", "search", "login", "log in", "sign in",
    "sign up", "register", "blog", "news", "faq", "faqs", "careers", "jobs", "privacy policy", "terms",
    "terms of service", "cookie policy", "cookies", "read more", "learn more", "get started", "subscribe",
    "newsletter", "follow us", "our team", "team", "testimonials", "partners", "resources", "support",
    "services", "products", "solutions", "welcome", "overview", "skip to content", "view all", "all rights reserved",
}
LINK_HINTS = ["about", "service", "solution", "product", "what-we-do", "what we do", "company", "offering", "industr", "platform"]


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def extract_page(url, html):
    soup = BeautifulSoup(html, "lxml")
    raw_lower = html.lower()
    title = _clean(soup.title.string) if soup.title and soup.title.string else ""

    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"name": n}) or soup.find("meta", attrs={"property": n})
            if t and t.get("content"):
                return _clean(t["content"])
        return ""

    description = meta("description", "og:description", "twitter:description")
    site_name = meta("og:site_name")
    nav = []
    for n in soup.find_all("nav"):
        for a in n.find_all("a"):
            t = _clean(a.get_text())
            if 2 < len(t) < 40:
                nav.append(t)
    links = []
    for a in soup.find_all("a", href=True):
        t = _clean(a.get_text()).lower()
        h = a["href"]
        if h.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        full = urljoin(url, h).split("#")[0]
        links.append((t, full))
    for t in soup(["script", "style", "noscript", "svg", "iframe"]):
        t.decompose()
    headings, h1s = [], []
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = _clean(h.get_text())
        if 3 <= len(t) <= 90:
            (h1s if h.name == "h1" else headings).append(t)
    headings = headings + h1s  # h1 is usually a slogan; prefer h2/h3 as "offerings"
    list_items = [_clean(li.get_text()) for li in soup.find_all("li")]
    list_items = [x for x in list_items if 3 <= len(x) <= 60]
    paras = [_clean(p.get_text()) for p in soup.find_all("p")]
    paras = [p for p in paras if len(p) > 50][:40]
    text = _clean(soup.get_text(" "))[:8000]
    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d{2})", raw_lower.replace("&copy;", "©"))]
    sig = {
        "chat_widget": any(k in raw_lower for k in [
            "intercom", "drift.com", "tawk.to", "crisp.chat", "livechatinc", "zendesk", "freshchat", "tidio",
            "hubspot.com/conversations", "olark", "chatbot", "live chat", "whatsapp chat"]),
        "ecommerce": any(k in raw_lower for k in ["add to cart", "shopify", "woocommerce", "/cart", "checkout", "add to basket"]),
        "wordpress": "wp-content" in raw_lower,
        "portal": any(k in raw_lower for k in ["client portal", "customer portal", "patient portal", "member login", "my account"]),
        "contact_form": bool(soup.find("form")) and ("contact" in raw_lower or "enquiry" in raw_lower or "inquiry" in raw_lower),
        "blog": any(k in raw_lower for k in ["/blog", "latest articles", "our blog"]),
        "careers": any(k in raw_lower for k in ["/careers", "we're hiring", "we are hiring", "join our team", "open positions"]),
        "already_ai": bool(re.search(r"\b(artificial intelligence|machine learning|generative ai|ai-powered|ai powered)\b", raw_lower)),
        "mentions_automation": "automation" in raw_lower or "automated" in raw_lower,
        "mobile_app": any(k in raw_lower for k in ["app store", "google play", "download our app"]),
        "multi_language": raw_lower.count("hreflang") >= 2,
        "booking": any(k in raw_lower for k in ["book a demo", "schedule a call", "book an appointment", "book now", "request a quote"]),
        "copyright_year": max(years) if years else None,
    }
    return {
        "url": url, "title": title, "description": description, "site_name": site_name,
        "nav": nav[:25], "headings": headings[:40], "list_items": list_items[:60], "paragraphs": paras,
        "text": text, "signals": sig, "links": links,
    }


def pick_extra_pages(base_url, links):
    host = urlparse(base_url).netloc
    picked, seen = [], {base_url.rstrip("/")}
    for hint in LINK_HINTS:
        for t, full in links:
            u = urlparse(full)
            if u.netloc != host:
                continue
            key = full.rstrip("/")
            if key in seen:
                continue
            if hint in t or hint in u.path.lower():
                picked.append(full)
                seen.add(key)
                break
        if len(picked) >= MAX_PAGES - 1:
            break
    return picked


# --------------------------------------------------------------------------- classification

INDUSTRIES = {
    "ecommerce": ("E-commerce & Retail", ["shop", "store", "cart", "checkout", "retail", "products", "fashion", "apparel", "marketplace", "orders", "delivery", "brand", "collection"]),
    "healthcare": ("Healthcare", ["patient", "clinic", "hospital", "medical", "health", "doctor", "dental", "therapy", "pharma", "care", "wellness", "diagnostic"]),
    "finance": ("Finance & Insurance", ["bank", "loan", "insurance", "invest", "payment", "wealth", "fintech", "credit", "mortgage", "accounting", "lending", "trading"]),
    "logistics": ("Logistics & Supply Chain", ["logistics", "freight", "shipping", "cargo", "warehouse", "supply chain", "courier", "fleet", "transport", "delivery network", "tracking"]),
    "manufacturing": ("Manufacturing & Industrial", ["manufactur", "factory", "industrial", "machinery", "fabrication", "production", "assembly", "engineering", "components", "plant"]),
    "real_estate": ("Real Estate & Construction", ["real estate", "property", "properties", "realty", "listing", "apartment", "construction", "builder", "developer", "leasing", "homes"]),
    "education": ("Education & Training", ["student", "course", "learning", "university", "school", "training", "curriculum", "academy", "tutor", "edtech", "campus"]),
    "hospitality": ("Hospitality & Travel", ["hotel", "resort", "travel", "tour", "booking", "restaurant", "stay", "vacation", "hospitality", "cafe"]),
    "professional_services": ("Professional Services", ["consulting", "advisory", "law firm", "legal", "attorney", "audit", "tax", "recruit", "staffing", "agency", "marketing", "branding"]),
    "saas": ("Software & Technology", ["software", "platform", "saas", "api", "cloud", "developer", "app", "automation", "analytics", "dashboard", "integration"]),
    "energy": ("Energy & Utilities", ["energy", "solar", "power", "oil", "gas", "renewable", "utility", "electric", "wind", "grid"]),
    "nonprofit": ("Non-profit & Public", ["foundation", "ngo", "charity", "donate", "volunteer", "non-profit", "nonprofit", "community"]),
    "food_agri": ("Food & Agriculture", ["farm", "agri", "food", "organic", "harvest", "beverage", "produce", "crop"]),
    "media": ("Media & Entertainment", ["media", "studio", "film", "music", "publishing", "news", "entertainment", "gaming", "content creators"]),
}


def classify_industry(pages):
    blob = " ".join([p["title"] + " " + p["description"] + " " + " ".join(p["headings"]) + " " + p["text"][:3000] for p in pages]).lower()
    # weight title/description/headings 3x
    head = " ".join([p["title"] + " " + p["description"] + " " + " ".join(p["headings"]) for p in pages]).lower()
    scores = Counter()
    hits = {}
    for key, (_, kws) in INDUSTRIES.items():
        for kw in kws:
            c = len(re.findall(r"\b" + re.escape(kw), blob)) + 3 * len(re.findall(r"\b" + re.escape(kw), head))
            if c:
                scores[key] += min(c, 12)
                hits.setdefault(key, []).append(kw)
    if not scores:
        return None, 0.0, []
    ranked = scores.most_common(2)
    top, s = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    conf = round(min(1.0, (s / (s + second + 6))), 2)
    return top, conf, hits.get(top, [])[:5]


def extract_offerings(pages, company):
    cands = []
    for p in pages:
        for h in p["headings"] + p["list_items"] + p["nav"]:
            h2 = h.strip(" -–|:•")
            lw = h2.lower()
            words = h2.split()
            if lw in GENERIC_HEADINGS or not (1 <= len(words) <= 7) or len(h2) < 4:
                continue
            if company and company.lower() in lw and len(words) < 3:
                continue
            if re.search(r"[©@]|http|\d{4}|cookie|privacy|©", lw):
                continue
            if h2.endswith(("?", ".", "!")) and len(words) > 5:
                continue
            cands.append(h2)
    seen, out = set(), []
    for c in cands:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out[:8]


# --------------------------------------------------------------------------- opportunities

def _fid(facts, kind, text, source, **extra):
    fid = f"F{len(facts) + 1}"
    facts.append({"id": fid, "kind": kind, "text": text, "source": source, **extra})
    return fid


def build_facts(lead, pages, industry_key, industry_conf, kw_hits, offerings, signals, final_urls):
    facts = []
    home = pages[0] if pages else None
    src = home["url"] if home else lead.get("website", "")
    if home:
        desc = home["description"] or (home["paragraphs"][0] if home["paragraphs"] else "")
        if desc:
            d = desc if len(desc) <= 220 else desc[:217].rsplit(" ", 1)[0] + "…"
            _fid(facts, "description", f'Website describes the company as: "{d}"', src, quote=d)
        elif home["title"]:
            _fid(facts, "description", f'Website title: "{home["title"][:120]}"', src, quote=home["title"][:120])
    for o in offerings[:5]:
        _fid(facts, "offering", f'Website lists "{o}" among its products/services/topics', src, quote=o)
    if industry_key:
        _fid(facts, "industry", f"Appears to operate in {INDUSTRIES[industry_key][0]} (keywords seen: {', '.join(kw_hits)})", src,
             inferred=True, industry=industry_key)
    s = signals
    if s.get("ecommerce"):
        _fid(facts, "signal", "The site runs an online store / shopping cart", src, signal="ecommerce")
    if s.get("portal"):
        _fid(facts, "signal", "The site offers a customer/client portal or account area", src, signal="portal")
    if s.get("booking"):
        _fid(facts, "signal", "The site has a booking / demo / quote request flow", src, signal="booking")
    if s.get("multi_language"):
        _fid(facts, "signal", "The site is published in multiple languages", src, signal="multi_language")
    if s.get("mobile_app"):
        _fid(facts, "signal", "The company promotes a mobile app", src, signal="mobile_app")
    if s.get("careers"):
        _fid(facts, "signal", "The site has a careers / hiring section", src, signal="careers")
    if s.get("blog"):
        _fid(facts, "signal", "The company publishes a blog / articles", src, signal="blog")
    if not s.get("chat_widget") and pages:
        _fid(facts, "absence", "No live-chat or assistant widget was detected on the pages reviewed", src, signal="no_chat")
    if s.get("contact_form") and not s.get("chat_widget"):
        _fid(facts, "signal", "Enquiries seem to be handled through a contact form", src, signal="contact_form")
    if s.get("copyright_year") and s["copyright_year"] <= datetime.now().year - 3:
        _fid(facts, "signal", f"The site footer shows a copyright year of {s['copyright_year']} (site may not be recently updated)", src,
             signal="stale_site")
    if s.get("wordpress"):
        _fid(facts, "signal", "The site is built on WordPress", src, signal="wordpress")
    return facts


def _fact_ids(facts, **match):
    return [f["id"] for f in facts if all(f.get(k) == v for k, v in match.items())]


def derive_opportunities(industry_key, signals, facts, services):
    """Rule-based mapping from evidence -> ForITus services. Each opportunity cites fact ids."""
    ops = {}

    def add(service, strength, why, ev):
        if service not in services or not ev:
            return
        cur = ops.get(service)
        if not cur or strength > cur["strength"]:
            ops[service] = {"service": service, "strength": strength, "rationale": why, "evidence": ev,
                            "source": "rules"}

    no_chat = _fact_ids(facts, signal="no_chat")
    form = _fact_ids(facts, signal="contact_form")
    ind = _fact_ids(facts, kind="industry")
    off = _fact_ids(facts, kind="offering")[:2]
    desc = _fact_ids(facts, kind="description")
    anchor = ind or off or desc

    if no_chat and (form or industry_key in ("ecommerce", "healthcare", "real_estate", "education", "hospitality", "finance", "professional_services")):
        cust = industry_key in ("ecommerce", "healthcare", "real_estate", "education", "hospitality", "finance")
        add("ai_chatbot", 3 if cust else 2, "Visitors can't get instant answers; an AI assistant could handle common questions and capture leads 24/7.", no_chat + form)
    if _fact_ids(facts, signal="ecommerce") or industry_key == "ecommerce":
        add("ecommerce", 3, "An online store can lift conversion with better product discovery, order/inventory automation and integrations.",
            _fact_ids(facts, signal="ecommerce") or anchor)
        add("ai_analytics", 2, "Purchase data can power demand forecasting and personalised recommendations.", _fact_ids(facts, signal="ecommerce") or anchor)
    if industry_key == "logistics":
        add("workflow_automation", 3, "Dispatch, tracking updates and paperwork are repetitive and well suited to automation.", anchor)
        add("ai_analytics", 2, "Route and demand data can feed predictive planning.", anchor)
    if industry_key == "manufacturing":
        add("workflow_automation", 3, "Order-to-production handoffs and reporting can be automated across systems.", anchor)
        add("data_dash", 2, "Plant and sales data can be unified into live dashboards.", anchor)
    if industry_key == "healthcare":
        add("ai_docs", 3, "Intake forms, records and referrals involve heavy paperwork that AI extraction can streamline.", anchor)
        add("workflow_automation", 2, "Appointment reminders and follow-ups can be automated.", anchor)
    if industry_key == "finance":
        add("ai_docs", 3, "KYC, statements and invoices can be processed automatically with AI document extraction.", anchor)
        add("data_dash", 2, "Consolidated reporting dashboards reduce manual reconciliation.", anchor)
    if industry_key == "real_estate":
        if no_chat:
            add("ai_chatbot", 3, "Property enquiries can be qualified instantly by an AI assistant.", no_chat + anchor)
        add("crm_erp", 2, "Linking listings, leads and follow-ups in a CRM removes manual tracking.", anchor)
    if industry_key == "education":
        if no_chat:
            add("ai_chatbot", 3, "Prospective students' questions can be answered instantly around the clock.", no_chat + anchor)
        add("workflow_automation", 2, "Admissions and communication workflows can be automated.", anchor)
    if industry_key in ("professional_services", "media"):
        add("ai_docs", 2, "Proposals, contracts and reports can be drafted and processed faster with AI.", anchor)
        add("workflow_automation", 2, "Client onboarding and reporting can be automated.", anchor)
    if industry_key == "hospitality" and no_chat:
        add("ai_chatbot", 2, "Guests can get instant booking and FAQ answers via an AI assistant.", no_chat + anchor)
    if industry_key == "saas":
        add("cloud_devops", 2, "Scaling a product benefits from solid CI/CD and cloud cost/reliability practices.", anchor)
        if no_chat:
            add("ai_chatbot", 2, "AI support/onboarding assistants reduce ticket load.", no_chat + anchor)
    if industry_key in ("energy", "food_agri"):
        add("ai_analytics", 2, "Operational data can be turned into forecasts and alerts.", anchor)
        add("data_dash", 2, "Field and plant data can be consolidated into dashboards.", anchor)
    if _fact_ids(facts, signal="portal"):
        add("web_app", 2, "An existing customer portal can be extended with self-service features and integrations.", _fact_ids(facts, signal="portal"))
    if _fact_ids(facts, signal="stale_site"):
        add("web_app", 2, "A site that hasn't been refreshed in a while can be modernised for speed, UX and lead capture.", _fact_ids(facts, signal="stale_site"))
    if _fact_ids(facts, signal="booking"):
        add("workflow_automation", 2, "Booking/quote requests can be routed, confirmed and followed up automatically.", _fact_ids(facts, signal="booking"))
    if _fact_ids(facts, signal="wordpress"):
        add("web_app", 1, "Custom features and performance work beyond what plugins offer.", _fact_ids(facts, signal="wordpress"))
    if not ops and anchor:
        add("workflow_automation", 1, "Most growing teams have repetitive manual steps that can be automated.", anchor)
    out = sorted(ops.values(), key=lambda o: -o["strength"])
    return out[:4]


# --------------------------------------------------------------------------- LLM refinement

def llm_refine(lead, pages, facts, services, base_ops):
    svc_list = {k: v["label"] for k, v in services.items()}
    excerpt = "\n".join((p["title"] + " | " + p["description"] + " | " + " ".join(p["paragraphs"][:4]))[:900] for p in pages[:3])
    system = (
        "You are a B2B research analyst for ForITus Solutions (IT, AI and automation services). "
        "Use ONLY the evidence provided. Never invent facts, numbers, clients, news or technologies. "
        "Return strict JSON.")
    user = json.dumps({
        "company": lead["company"], "country": lead.get("country"), "website_text_excerpt": excerpt,
        "facts": [{"id": f["id"], "text": f["text"]} for f in facts],
        "forItus_services": svc_list,
        "task": "Return JSON: {\"summary\": <=35 words plain description of what the company does, grounded in facts>, "
                "\"industry\": short label, "
                "\"opportunities\": [up to 3 of {\"service\": <key from forItus_services>, \"rationale\": <=25 words explaining the concrete "
                "benefit for THIS company, \"evidence\": [fact ids that support it]}]}"
    }, ensure_ascii=False)
    data = llm.complete_json(system, user, temperature=0.3)
    valid_ids = {f["id"] for f in facts}
    ops = []
    for o in (data.get("opportunities") or [])[:3]:
        svc = o.get("service")
        ev = [e for e in (o.get("evidence") or []) if e in valid_ids]
        if svc in services and ev and o.get("rationale"):
            ops.append({"service": svc, "strength": 3, "rationale": str(o["rationale"])[:240], "evidence": ev, "source": "llm"})
    merged = {o["service"]: o for o in ops}
    for o in base_ops:
        merged.setdefault(o["service"], o)
    return str(data.get("summary") or "")[:300], str(data.get("industry") or "")[:60], list(merged.values())[:4]


# --------------------------------------------------------------------------- main entry

def research_lead(lead_id, force=False):
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise KeyError(lead_id)
    existing = db.one("SELECT status FROM research WHERE lead_id=?", (lead_id,))
    if existing and not force and existing["status"] in ("ok", "partial"):
        return existing
    profile = company_profile()
    services = profile["services"]
    pages, final_urls, err = [], [], None
    site = lead.get("website") or ""
    try:
        if not site:
            raise ValueError("No website provided")
        if not robots_allows(site, site):
            raise ValueError("robots.txt disallows automated access")
        final, html = safe_get(site)
        home = extract_page(final, html)
        pages.append(home)
        final_urls.append(final)
        for extra in pick_extra_pages(final, home["links"]):
            try:
                if not robots_allows(final, extra):
                    continue
                u, h = safe_get(extra)
                pages.append(extract_page(u, h))
                final_urls.append(u)
            except Exception:
                continue
    except Exception as e:
        err = str(e)[:200]

    if not pages:
        facts = []
        if lead.get("website"):
            _fid(facts, "given", f"Company website provided: {lead['website']} (could not be analysed)", lead["website"])
        db.execute(
            "INSERT OR REPLACE INTO research(lead_id,status,confidence,industry,industry_detail,summary,offerings,facts,signals,opportunities,pages,llm_used,error,fetched_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lead_id, "failed", 0.0, "", "{}", "", "[]", json.dumps(facts), "{}", "[]", "[]", "", err, db.now()))
        _mark_lead(lead_id, "researched")
        return {"status": "failed", "error": err}

    for p in pages:
        p.pop("links", None)
    signals = {}
    for p in pages:
        for k, v in p["signals"].items():
            if k == "copyright_year":
                vals = [x for x in (signals.get(k), v) if x]
                signals[k] = max(vals) if vals else None
            else:
                signals[k] = signals.get(k) or v
    ind_key, ind_conf, hits = classify_industry(pages)
    offerings = extract_offerings(pages, lead["company"])
    facts = build_facts(lead, pages, ind_key, ind_conf, hits, offerings, signals, final_urls)
    ops = derive_opportunities(ind_key, signals, facts, services)
    summary = ""
    industry_label = INDUSTRIES[ind_key][0] if ind_key else ""
    llm_used = ""
    if llm.available():
        try:
            summary, ind_llm, ops = llm_refine(lead, pages, facts, services, ops)
            llm_used = llm.label()
            if ind_llm and not industry_label:
                industry_label = ind_llm
        except Exception as e:
            err = f"LLM refinement skipped: {e}"[:200]
    if not summary:
        d = pages[0]["description"] or (pages[0]["paragraphs"][0] if pages[0]["paragraphs"] else pages[0]["title"])
        summary = (d[:240] if d else f"{lead['company']} website analysed.")
    text_len = sum(len(p["text"]) for p in pages)
    conf = round(min(0.97, 0.15 + 0.1 * len(pages) + min(text_len, 8000) / 20000 + 0.2 * ind_conf + 0.015 * len(facts)), 2)
    status = "ok" if (len(facts) >= 3 and text_len > 400) else "partial"
    pages_meta = [{"url": p["url"], "title": p["title"][:120], "chars": len(p["text"])} for p in pages]
    db.execute(
        "INSERT OR REPLACE INTO research(lead_id,status,confidence,industry,industry_detail,summary,offerings,facts,signals,opportunities,pages,llm_used,error,fetched_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lead_id, status, conf, industry_label,
         json.dumps({"key": ind_key, "confidence": ind_conf, "keywords": hits}),
         summary, json.dumps(offerings), json.dumps(facts), json.dumps(signals), json.dumps(ops),
         json.dumps(pages_meta), llm_used, err, db.now()))
    _mark_lead(lead_id, "researched")
    from . import scoring
    scoring.rescore(lead_id)
    return {"status": status, "facts": len(facts)}


def _mark_lead(lead_id, status):
    db.execute("UPDATE leads SET status=? WHERE id=? AND status IN ('new','researched')", (status, lead_id))


def get_research(lead_id):
    r = db.one("SELECT * FROM research WHERE lead_id=?", (lead_id,))
    if not r:
        return None
    for k in ("industry_detail", "offerings", "facts", "signals", "opportunities", "pages"):
        try:
            r[k] = json.loads(r[k] or "null")
        except Exception:
            r[k] = None
    return r
