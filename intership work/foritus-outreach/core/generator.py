"""Personalised email generation.

Mode A (LLM, recommended): the model receives ONLY the research evidence (fact ids) and must
cite which facts it used. Output is verified; on critical issues we retry once with feedback.
Mode B (composer, offline fallback): a grounded, seeded phrase composer (en/de/fr/es) so the
system still works with zero API keys. Signature and opt-out lines are appended by code."""
import hashlib
import json
import random
import re
import secrets

from . import config, db, llm, quality, research
from .regions import profile_for

TITLES = ("mr", "mrs", "ms", "dr", "prof", "miss", "mx")


def first_name(name):
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p.lower().strip(".") not in TITLES]
    return parts[0] if parts else ""


def last_name(name):
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p.lower().strip(".") not in TITLES]
    return parts[-1] if len(parts) > 1 else ""


SPELL_UK = {"optimize": "optimise", "optimization": "optimisation", "organization": "organisation",
            "personalized": "personalised", "customize": "customise", "customized": "customised", "automate ": "automate "}


def sp(text, spelling):
    if spelling == "UK":
        for a, b in SPELL_UK.items():
            text = text.replace(a, b)
    return text


# ------------------------------------------------------------------ phrase banks
TOPIC = {
    "ai_chatbot": {"en": "customer enquiries", "de": "Kundenanfragen", "fr": "demandes clients", "es": "consultas de clientes"},
    "ai_docs": {"en": "document handling", "de": "Dokumentenverarbeitung", "fr": "traitement des documents", "es": "gestión de documentos"},
    "ai_analytics": {"en": "forecasting", "de": "Prognosen", "fr": "prévisions", "es": "previsiones"},
    "workflow_automation": {"en": "day-to-day workflows", "de": "Arbeitsabläufe", "fr": "processus internes", "es": "procesos internos"},
    "web_app": {"en": "web presence", "de": "Webauftritt", "fr": "présence en ligne", "es": "presencia web"},
    "ecommerce": {"en": "online store", "de": "Onlineshop", "fr": "boutique en ligne", "es": "tienda online"},
    "cloud_devops": {"en": "release process", "de": "Release-Prozess", "fr": "déploiements", "es": "despliegues"},
    "data_dash": {"en": "reporting", "de": "Reporting", "fr": "reporting", "es": "informes"},
    "crm_erp": {"en": "CRM setup", "de": "CRM-Prozesse", "fr": "processus CRM", "es": "procesos de CRM"},
    "it_support": {"en": "IT operations", "de": "IT-Betrieb", "fr": "exploitation IT", "es": "operaciones de TI"},
}

PITCH = {
    "en": {
        "ai_chatbot": ["One idea: an AI assistant that answers common visitor questions instantly and hands warm leads to your team.",
                       "We build AI assistants that handle first-line questions around the clock and pass the genuinely interested ones to a person."],
        "ai_docs": ["We build AI tools that read documents such as forms, invoices and records and pull out the data automatically, so nobody retypes it.",
                    "One idea: AI-based document processing that turns paperwork into structured data, with a person reviewing only the exceptions."],
        "ai_analytics": ["We help teams turn the data they already collect into forecasts and alerts they can act on.",
                         "One idea: lightweight predictive models on your existing data, shown in a simple dashboard."],
        "workflow_automation": ["We automate repetitive hand-offs between tools (forms, spreadsheets, email, CRM) so the team spends time on real work.",
                                "One idea: connecting your existing tools with automated workflows to remove manual copy-paste and follow-up chasing."],
        "web_app": ["We build and modernise web and mobile applications, including portals and self-service features.",
                    "One idea: refreshing the site or portal so it is faster, easier to use and better at capturing enquiries."],
        "ecommerce": ["We help online stores with product discovery, order and inventory automation, and integrations that reduce manual work.",
                      "One idea: smarter product recommendations plus automated order and stock updates for your store."],
        "cloud_devops": ["We help product teams with cloud setup and automated release pipelines so shipping is faster and calmer.",
                         "One idea: a CI/CD and monitoring setup that makes releases routine rather than stressful."],
        "data_dash": ["We pull data from scattered tools into one live dashboard so reporting stops being a manual exercise.",
                      "One idea: a single reporting dashboard fed automatically from the systems you already use."],
        "crm_erp": ["We connect and customise CRM and ERP systems so leads, orders and follow-ups are tracked in one place.",
                    "One idea: tidying how your CRM connects to the rest of your tools so nothing slips through."],
        "it_support": ["We provide managed IT support and security so your team can focus on the business.",
                       "One idea: proactive IT support and basic security hardening handled for you."],
    },
    "de": {
        "ai_chatbot": ["Eine Idee: ein KI-Assistent, der häufige Fragen sofort beantwortet und interessierte Kontakte an Ihr Team weitergibt."],
        "ai_docs": ["Wir entwickeln KI-Lösungen, die Dokumente wie Formulare und Rechnungen automatisch auslesen, damit niemand Daten abtippen muss."],
        "ai_analytics": ["Wir helfen Teams, vorhandene Daten in Prognosen und Warnungen umzusetzen, mit denen sich arbeiten lässt."],
        "workflow_automation": ["Wir automatisieren wiederkehrende Übergaben zwischen Tools, damit Ihr Team Zeit für die eigentliche Arbeit hat."],
        "web_app": ["Wir entwickeln und modernisieren Web- und Mobile-Anwendungen, einschließlich Portalen und Self-Service-Funktionen."],
        "ecommerce": ["Wir unterstützen Onlineshops bei Produktempfehlungen, automatisierten Bestellprozessen und Integrationen."],
        "cloud_devops": ["Wir unterstützen Produktteams bei Cloud-Setup und automatisierten Release-Pipelines."],
        "data_dash": ["Wir führen Daten aus verschiedenen Tools in einem Live-Dashboard zusammen, damit Reporting nicht mehr manuell erfolgt."],
        "crm_erp": ["Wir verbinden und passen CRM- und ERP-Systeme an, damit Leads und Aufträge an einem Ort nachvollziehbar sind."],
        "it_support": ["Wir bieten Managed-IT-Support und Sicherheit, damit sich Ihr Team auf das Kerngeschäft konzentrieren kann."],
    },
    "fr": {
        "ai_chatbot": ["Une idée : un assistant IA qui répond instantanément aux questions courantes et transmet les contacts intéressés à votre équipe."],
        "ai_docs": ["Nous concevons des outils d'IA qui lisent les documents (formulaires, factures) et en extraient les données automatiquement."],
        "ai_analytics": ["Nous aidons les équipes à transformer leurs données existantes en prévisions et alertes exploitables."],
        "workflow_automation": ["Nous automatisons les tâches répétitives entre vos outils pour que votre équipe se concentre sur l'essentiel."],
        "web_app": ["Nous développons et modernisons des applications web et mobiles, y compris des portails et des fonctions en libre-service."],
        "ecommerce": ["Nous aidons les boutiques en ligne : recommandations produits, automatisation des commandes et intégrations."],
        "cloud_devops": ["Nous accompagnons les équipes produit sur le cloud et les pipelines de déploiement automatisés."],
        "data_dash": ["Nous regroupons vos données dispersées dans un tableau de bord en temps réel."],
        "crm_erp": ["Nous connectons et personnalisons les CRM et ERP pour suivre prospects et commandes au même endroit."],
        "it_support": ["Nous proposons un support informatique managé et la sécurité, pour que votre équipe reste concentrée sur son métier."],
    },
    "es": {
        "ai_chatbot": ["Una idea: un asistente de IA que responda al instante las preguntas frecuentes y pase los contactos interesados a su equipo."],
        "ai_docs": ["Creamos herramientas de IA que leen documentos (formularios, facturas) y extraen los datos automáticamente."],
        "ai_analytics": ["Ayudamos a convertir los datos que ya tienen en previsiones y alertas útiles."],
        "workflow_automation": ["Automatizamos tareas repetitivas entre herramientas para que su equipo se dedique a lo importante."],
        "web_app": ["Desarrollamos y modernizamos aplicaciones web y móviles, incluidos portales y funciones de autoservicio."],
        "ecommerce": ["Ayudamos a tiendas online con recomendaciones de producto, automatización de pedidos e integraciones."],
        "cloud_devops": ["Apoyamos a equipos de producto con la nube y pipelines de despliegue automatizados."],
        "data_dash": ["Unificamos datos dispersos en un panel en tiempo real."],
        "crm_erp": ["Conectamos y personalizamos CRM y ERP para seguir leads y pedidos en un solo lugar."],
        "it_support": ["Ofrecemos soporte informático gestionado y seguridad para que su equipo se centre en el negocio."],
    },
}

SIGNAL_OPENER_EN = {
    "ecommerce": "I noticed {company} sells online through its own store.",
    "portal": "I noticed {company} offers a customer portal.",
    "booking": "I saw that {company} takes bookings or quote requests through its website.",
    "multi_language": "I noticed {company}'s website is available in several languages.",
    "mobile_app": "I saw that {company} has its own mobile app.",
    "blog": "I noticed {company} publishes regular articles on its site.",
    "careers": "I noticed {company} has an open careers section, which usually means growth.",
    "no_chat": "While browsing {company}'s site I didn't spot a live chat or assistant (I may well have missed one).",
    "contact_form": "I noticed enquiries to {company} seem to come in through the contact form.",
}

BANK = {
    "en": {
        "greet": {"US": ["Hi {n},", "Hello {n},", "Hi {n} —"], "formal": ["Dear {n},", "Hello {n},"], "default": ["Hello {n},", "Hi {n},"]},
        "greet_anon": ["Hello,", "Hi there,"],
        "offering": ["I was looking through {company}'s website and \"{q}\" caught my eye.",
                     "While reading about {company}, I noticed you offer \"{q}\".",
                     "\"{q}\" on {company}'s site stood out to me, which is why I'm reaching out."],
        "description": ["I read how {company} describes itself (\"{q}\") and thought a note was worthwhile.",
                        "{company}'s website describes the business as \"{q}\", which is what prompted this message."],
        "light": ["I'm reaching out because {company} looks like the kind of team we work with.",
                  "I'm getting in touch as {company} may be a good fit for what we do."],
        "bridge": ["I'm with ForITus Solutions; we help businesses with IT, AI and automation.",
                   "At ForITus Solutions we build practical IT, AI and automation solutions for growing businesses.",
                   "I work with ForITus Solutions, where we help teams put IT, AI and automation to practical use."],
        "hedge": ["Of course, you know your operations far better than I do.", "I may be off the mark, but it seemed worth raising.", ""],
        "cta": {"US": ["Open to a quick 15-minute call this week or next?", "Worth a 15-minute chat to see if there's a fit?"],
                "formal": ["Would you be open to a brief introductory call at a time that suits you?", "May I suggest a short call at your convenience?"],
                "default": ["Would a short 15-minute call sometime next week make sense?", "Would you be open to a brief call to see if this is relevant?"]},
        "signoff": {"US": ["Best,", "Thanks,", "Best regards,"], "formal": ["Kind regards,", "Best regards,"], "default": ["Best regards,", "Kind regards,"]},
        "optout": "If this isn't relevant, just reply \"no thanks\" or opt out here: {{UNSUB_URL}}",
        "subjects": ["{company} and {short}", "A thought on {company}'s {topic}", "Quick idea for {company}",
                     "{n}, {short} for {company}?", "Question about {company}'s {topic}", "{short} at {company}"],
        "fu1": ["Following up on my note below in case it got buried.", "A quick nudge on my earlier message."],
        "fu1_body": ["If {short} isn't a priority right now, no problem at all. If it is, I'd be glad to share a concrete example for {company}.",
                     "Happy to send a short outline of how this could work for {company} if that's easier than a call."],
        "fu2": ["Closing the loop on my earlier emails.", "Last note from me on this."],
        "fu2_body": ["I won't keep emailing. If {short} ever becomes a priority for {company}, I'd be glad to help. Wishing you and the team all the best."],
    },
    "de": {
        "greet": {"default": ["Guten Tag {full},", "Hallo {full},"]}, "greet_anon": ["Guten Tag,"],
        "offering": ["Beim Besuch der Website von {company} ist mir \"{q}\" aufgefallen.", "Auf der Website von {company} hat mich \"{q}\" angesprochen."],
        "description": ["{company} beschreibt sich auf der Website als \"{q}\", und das hat mich zu dieser Nachricht bewogen."],
        "light": ["{company} wirkt wie ein Unternehmen, für das unsere Arbeit interessant sein könnte."],
        "bridge": ["Ich arbeite bei ForITus Solutions; wir unterstützen Unternehmen mit IT-, KI- und Automatisierungslösungen."],
        "hedge": ["Sie kennen Ihre Abläufe selbstverständlich am besten.", ""],
        "cta": {"default": ["Hätten Sie nächste Woche Zeit für ein kurzes Gespräch von etwa 15 Minuten?"]},
        "signoff": {"default": ["Mit freundlichen Grüßen"]},
        "optout": "Falls dies nicht relevant ist, antworten Sie einfach mit \"Nein danke\" oder melden Sie sich hier ab: {{UNSUB_URL}}",
        "subjects": ["{company} und {topic}", "Idee zum Thema {topic} bei {company}", "Kurze Frage zum Thema {topic}"],
        "fu1": ["Ich melde mich kurz zu meiner vorherigen Nachricht."], "fu1_body": ["Falls {topic} derzeit keine Priorität hat, ist das völlig in Ordnung. Andernfalls zeige ich Ihnen gern ein konkretes Beispiel für {company}."],
        "fu2": ["Abschließend zu meinen früheren Nachrichten."], "fu2_body": ["Ich werde nicht weiter schreiben. Sollte {topic} für {company} wichtig werden, helfe ich gern. Alles Gute für Sie und Ihr Team."],
    },
    "fr": {
        "greet": {"default": ["Bonjour {full},"]}, "greet_anon": ["Bonjour,"],
        "offering": ["En parcourant le site de {company}, « {q} » a retenu mon attention.", "Sur le site de {company}, « {q} » a attiré mon attention."],
        "description": ["{company} se décrit sur son site comme « {q} », ce qui m'a incité à vous écrire."],
        "light": ["{company} me semble correspondre au type d'entreprise que nous accompagnons."],
        "bridge": ["Je travaille chez ForITus Solutions, où nous aidons les entreprises sur l'IT, l'IA et l'automatisation."],
        "hedge": ["Vous connaissez bien sûr vos opérations bien mieux que moi.", ""],
        "cta": {"default": ["Auriez-vous 15 minutes la semaine prochaine pour un court échange ?"]},
        "signoff": {"default": ["Cordialement,"]},
        "optout": "Si ce message n'est pas pertinent, répondez simplement « non merci » ou désinscrivez-vous ici : {{UNSUB_URL}}",
        "subjects": ["{company} et {topic}", "Une idée sur {topic} chez {company}", "Question rapide sur {topic}"],
        "fu1": ["Je reviens brièvement vers vous au sujet de mon message précédent."], "fu1_body": ["Si {topic} n'est pas une priorité, aucun souci. Sinon, je vous montrerai volontiers un exemple concret pour {company}."],
        "fu2": ["Un dernier mot sur mes messages précédents."], "fu2_body": ["Je ne vous écrirai plus. Si {topic} devient une priorité pour {company}, je serai ravi d'aider. Bien cordialement à vous et à votre équipe."],
    },
    "es": {
        "greet": {"default": ["Estimado/a {full},", "Hola {full},"]}, "greet_anon": ["Hola,"],
        "offering": ["Al revisar el sitio web de {company}, me llamó la atención \"{q}\".", "En el sitio de {company}, \"{q}\" me pareció interesante."],
        "description": ["{company} se describe en su web como \"{q}\", y por eso le escribo."],
        "light": ["{company} parece el tipo de empresa con la que solemos trabajar."],
        "bridge": ["Trabajo en ForITus Solutions, donde ayudamos a las empresas con TI, IA y automatización."],
        "hedge": ["Usted conoce sus operaciones mucho mejor que yo.", ""],
        "cta": {"default": ["¿Tendría 15 minutos la próxima semana para una breve llamada?"]},
        "signoff": {"default": ["Saludos cordiales,"]},
        "optout": "Si no le resulta relevante, responda \"no gracias\" o dese de baja aquí: {{UNSUB_URL}}",
        "subjects": ["{company} y {topic}", "Una idea sobre {topic} en {company}", "Pregunta rápida sobre {topic}"],
        "fu1": ["Le escribo brevemente por mi mensaje anterior."], "fu1_body": ["Si {topic} no es una prioridad, no hay problema. Si lo es, con gusto le muestro un ejemplo concreto para {company}."],
        "fu2": ["Cierro el hilo de mis mensajes anteriores."], "fu2_body": ["No les escribiré más. Si {topic} se vuelve una prioridad para {company}, estaré encantado de ayudar. Un cordial saludo a usted y a su equipo."],
    },
}


def _fmt_bucket(profile):
    f = profile["formality"]
    if profile["code"] == "en-US" or f == "friendly-direct":
        return "US"
    if f in ("formal-relationship", "respectful-warm", "formal-concise", "formal-polite", "formal-warm"):
        return "formal"
    return "default"


def _pick(rng, bucket_dict, bucket):
    if isinstance(bucket_dict, dict):
        return rng.choice(bucket_dict.get(bucket) or bucket_dict["default"])
    return rng.choice(bucket_dict)


# ------------------------------------------------------------------ composer
def compose(lead, res, profile, step=0, prior=None, variant=0):
    rng = random.Random(hashlib.sha256(f"{lead['email']}|{step}|{variant}".encode()).hexdigest())
    lang = profile["lang"] if profile["lang"] in BANK else "en"
    b = BANK[lang]
    bucket = _fmt_bucket(profile)
    company = lead["company"]
    fn, full = first_name(lead.get("name")), (lead.get("name") or "").strip()
    facts = (res or {}).get("facts") or []
    ops = (res or {}).get("opportunities") or []
    services = config.company_profile()["services"]
    op = ops[0] if ops else None
    if step >= 2 and len(ops) > 1:
        op = ops[1]
    svc = op["service"] if op else "workflow_automation"
    short = services[svc]["short"]
    topic = TOPIC[svc][lang]
    n_for_greet = full if lang != "en" else fn
    if lang == "en":
        greet = rng.choice(b["greet_anon"]) if not fn else _pick(rng, b["greet"], bucket).format(n=fn)
    else:
        greet = rng.choice(b["greet_anon"]) if not full else _pick(rng, b["greet"], "default").format(full=full)
    used = []
    # ---- opener
    opener = ""
    by_kind = {}
    for f in facts:
        by_kind.setdefault(f["kind"] if f["kind"] != "signal" and f["kind"] != "absence" else f.get("signal"), []).append(f)
    op_ev = [e for e in (op["evidence"] if op else [])]
    cand = None
    for f in by_kind.get("offering", []):
        cand = f
        break
    if not cand:
        cand = (by_kind.get("description") or [None])[0]
    if lang == "en" and (not cand or rng.random() < 0.35):
        # prefer a signal that supports the chosen opportunity
        for f in facts:
            if f["id"] in op_ev and f.get("signal") in SIGNAL_OPENER_EN:
                cand = f
                break
    if cand and cand["kind"] == "offering":
        opener = _pick(rng, b["offering"], bucket).format(company=company, q=cand["quote"])
        used.append(cand["id"])
    elif cand and cand["kind"] == "description":
        opener = _pick(rng, b["description"], bucket).format(company=company, q=cand["quote"])
        used.append(cand["id"])
    elif cand and cand.get("signal") in SIGNAL_OPENER_EN:
        opener = SIGNAL_OPENER_EN[cand["signal"]].format(company=company)
        used.append(cand["id"])
    else:
        opener = _pick(rng, b["light"], bucket).format(company=company)
    # ---- pitch (grounded in opportunity)
    pitch = ""
    if op and res and res.get("status") in ("ok", "partial"):
        pitch = rng.choice(PITCH[lang].get(svc) or PITCH["en"][svc])
        used += [e for e in op["evidence"][:1] if e not in used]
    elif lang == "en":
        pitch = "We help teams save time by automating repetitive work and adding AI where it genuinely helps."
    else:
        pitch = rng.choice(PITCH[lang]["workflow_automation"])
    cta = _pick(rng, b["cta"], bucket)
    close = _pick(rng, b["signoff"], bucket)
    hedge = rng.choice(b["hedge"])
    if step == 0:
        pool = [x for x in b["subjects"] if fn or "{n}" not in x]
        subj = rng.choice(pool).format(company=company, short=short, topic=topic, n=fn)
        paras = [opener, f"{rng.choice(b['bridge'])} {pitch}" + (f" {hedge}" if hedge else ""), cta]
    else:
        base_subject = (prior or {}).get("subject", "") or f"{company}"
        subj = re.sub(r"^(re:\s*)+", "", base_subject, flags=re.I)
        subj = "Re: " + subj
        key = "fu1" if step == 1 else "fu2"
        paras = [rng.choice(b[key]) + " " + rng.choice(b[key + "_body"]).format(short=short, company=company, topic=topic)]
        if step == 1:
            paras.append(pitch)
            paras.append(cta)
        used = used[:1]
    subj = sp(subj, profile.get("spelling"))[:70]
    subj = subj[0].upper() + subj[1:]
    if lang == "en":
        subj = re.sub(r"(\w)s's\b", r"\1s'", subj)
        paras = [re.sub(r"(\w)s's\b", r"\1s'", p) for p in paras]
    body_core = "\n\n".join(sp(p, profile.get("spelling")) for p in paras)
    body = greet + "\n\n" + body_core
    body = _append_signature(body, close, lang)
    return {"subject": subj, "body": body, "facts_used": used, "generator": "composer"}


def _append_signature(core_text, close, lang):
    s = config.get("SENDER_NAME")
    t = config.get("SENDER_TITLE")
    sig = f"{close}\n{s}\n{t}, ForITus Solutions"
    return core_text.rstrip() + "\n\n" + sig + "\n\n" + BANK[lang]["optout"]


# ------------------------------------------------------------------ LLM mode
def _llm_prompt(lead, res, profile, step, prior, feedback=None):
    services = config.company_profile()["services"]
    facts = [{"id": f["id"], "text": f["text"]} for f in (res or {}).get("facts") or []]
    ops = [{"service": services[o["service"]]["label"], "why_for_this_company": o["rationale"], "evidence": o["evidence"]}
           for o in (res or {}).get("opportunities") or [] if o["service"] in services]
    system = (
        "You write cold outreach emails for ForITus Solutions, an IT, AI and automation services company. "
        "You write like a thoughtful human, never like a template. HARD RULES: (1) Use ONLY the provided facts about the "
        "recipient's company; never invent news, numbers, clients, results, funding, awards, tools or events. "
        "(2) Never claim past client work, case studies, statistics or guarantees about ForITus. "
        "(3) Reference at least one provided fact concretely and cite its id in facts_used. "
        "(4) No links, no signature, no unsubscribe text (added automatically). (5) No hype, no exclamation marks, no spam words. "
        "(6) Exactly one soft call to action. (7) Write the whole email in the requested language and regional style. "
        "(8) If facts are empty, write a short honest note that makes no claims about the company's website. "
        "Return strict JSON: {\"subject\": str, \"body\": str, \"facts_used\": [fact ids]}. "
        "The body starts with the greeting and ends BEFORE any sign-off.")
    task = {
        "initial": "Write the first email: 80-120 words, subject under 55 characters, curiosity-led not salesy.",
        1: "Write follow-up #1 (a gentle nudge): 50-80 words. Add ONE new angle that is different from the first email. Do not repeat its wording.",
        2: "Write follow-up #2 (polite final note): 40-60 words. Close the loop respectfully; no pressure.",
    }["initial" if step == 0 else min(step, 2)]
    payload = {
        "sender": {"name": config.get("SENDER_NAME"), "company": "ForITus Solutions"},
        "recipient": {"first_name": first_name(lead.get("name")) or None, "full_name": lead.get("name"),
                      "designation": lead.get("designation"), "company": lead["company"], "country": lead.get("country")},
        "language": profile["language"], "region_style": profile["tone"], "spelling": profile.get("spelling") or "",
        "facts": facts, "opportunities": ops, "task": task,
    }
    if prior:
        payload["previous_email"] = {"subject": prior.get("subject"), "body": quality.split_body(prior.get("body", ""))[0]}
    if feedback:
        payload["fix_these_problems_from_the_last_attempt"] = feedback
    return system, json.dumps(payload, ensure_ascii=False)


def _strip_signature(body):
    core, _ = quality.split_body(body)
    return core


def generate_llm(lead, res, profile, step=0, prior=None):
    feedback = None
    best = None
    for attempt in range(2):
        system, user = _llm_prompt(lead, res, profile, step, prior, feedback)
        data = llm.complete_json(system, user, temperature=0.85)
        subject = str(data.get("subject") or "").strip().strip('"')
        core = _strip_signature(str(data.get("body") or "").strip())
        used = [x for x in (data.get("facts_used") or []) if isinstance(x, str)]
        if step > 0 and subject and not subject.lower().startswith("re:"):
            subject = "Re: " + re.sub(r"^(re:\s*)+", "", (prior or {}).get("subject", subject), flags=re.I)
        lang = profile["lang"] if profile["lang"] in BANK else "en"
        close = _pick(random.Random(lead["email"] + str(step)), BANK[lang]["signoff"], _fmt_bucket(profile))
        body = _append_signature(core, close, lang)
        q = quality.verify(subject, body, lead, res, used, profile["lang"], step)
        cand = {"subject": subject, "body": body, "facts_used": used, "generator": "llm:" + llm.label(), "_q": q}
        if best is None or q["score"] > best["_q"]["score"]:
            best = cand
        if not q["blocking"]:
            break
        feedback = [i["msg"] for i in q["issues"] if i["severity"] == "critical"]
    best.pop("_q", None)
    return best


# ------------------------------------------------------------------ public API
def _row_to_res(lead_id):
    return research.get_research(lead_id)


def generate_for_lead(lead_id, step=0, force=False, variant=0):
    lead = db.one("SELECT * FROM leads WHERE id=?", (lead_id,))
    if not lead:
        raise KeyError(lead_id)
    if lead["status"] in ("opted_out", "bounced"):
        raise ValueError("lead is opted out / bounced")
    existing = db.one("SELECT * FROM emails WHERE lead_id=? AND step=?", (lead_id, step))
    if existing and existing["status"] in ("sent", "sending"):
        raise ValueError("an email for this step was already sent")
    if existing and not force and existing["status"] in ("draft", "approved"):
        return existing["id"]
    res = _row_to_res(lead_id)
    if not res:
        research.research_lead(lead_id)
        res = _row_to_res(lead_id)
    profile = profile_for(lead.get("country"))
    prior = None
    if step > 0:
        prior = db.one("SELECT subject, body FROM emails WHERE lead_id=? AND step=0", (lead_id,))
    result = None
    if llm.available():
        try:
            result = generate_llm(lead, res, profile, step, prior)
        except Exception as e:
            db.log_event(lead_id, None, "llm_fallback", str(e)[:200])
    if result is not None:
        qq = quality.verify(result["subject"], result["body"], lead, res, result["facts_used"], profile["lang"], step)
        if qq["blocking"]:  # never ship an LLM draft with fabricated claims / missing opt-out: fall back to the grounded composer
            db.log_event(lead_id, None, "llm_rejected", "; ".join(i["msg"] for i in qq["issues"] if i["severity"] == "critical")[:300])
            result = None
    if result is None:
        result = compose(lead, res, profile, step, prior, variant)
    q = quality.verify(result["subject"], result["body"], lead, res, result["facts_used"], profile["lang"], step,
                       email_id=existing["id"] if existing else None)
    token = existing["token"] if existing and existing.get("token") else secrets.token_urlsafe(12)
    if existing:
        db.execute(
            "UPDATE emails SET subject=?, body=?, language=?, region=?, facts_used=?, generator=?, status='draft', quality_score=?, quality=?, error=NULL, approved_at=NULL, attempts=0 WHERE id=?",
            (result["subject"], result["body"], profile["code"], profile["code"], json.dumps(result["facts_used"]), result["generator"],
             q["score"], json.dumps(q), existing["id"]))
        eid = existing["id"]
    else:
        eid, _ = db.execute(
            "INSERT INTO emails(lead_id,step,subject,body,language,region,facts_used,generator,status,quality_score,quality,token,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lead_id, step, result["subject"], result["body"], profile["code"], profile["code"], json.dumps(result["facts_used"]),
             result["generator"], "draft", q["score"], json.dumps(q), token, db.now()))
    db.execute("UPDATE leads SET status='drafted' WHERE id=? AND status IN ('new','researched','drafted')", (lead_id,))
    db.log_event(lead_id, eid, "drafted", result["generator"])
    return eid


def reverify(email_id):
    e = db.one("SELECT * FROM emails WHERE id=?", (email_id,))
    lead = db.one("SELECT * FROM leads WHERE id=?", (e["lead_id"],))
    res = _row_to_res(e["lead_id"])
    lang = (e.get("language") or "en")[:2]
    q = quality.verify(e["subject"], e["body"], lead, res, json.loads(e["facts_used"] or "[]"), lang, e["step"], email_id=email_id)
    db.execute("UPDATE emails SET quality_score=?, quality=? WHERE id=?", (q["score"], json.dumps(q), email_id))
    return q
