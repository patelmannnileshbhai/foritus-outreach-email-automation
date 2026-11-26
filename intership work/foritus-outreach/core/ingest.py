"""Lead import: CSV, XLSX or a (link-shared) Google Sheet. Validates, normalises, de-duplicates."""
import csv
import io
import re
from urllib.parse import urlparse

import requests

from . import db

MAX_ROWS = 5000
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")

SYNONYMS = {
    "name": ["name", "client name", "full name", "contact", "contact name", "client", "person"],
    "email": ["email", "email address", "e-mail", "mail", "email id"],
    "designation": ["designation", "title", "job title", "role", "position"],
    "company": ["company", "company name", "organization", "organisation", "business", "firm"],
    "website": ["website", "company website", "url", "site", "domain", "web", "web site"],
    "country": ["country", "location", "nation", "region"],
}

COUNTRY_ALIASES = {
    "usa": "United States", "us": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "united states of america": "United States", "america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom", "england": "United Kingdom", "great britain": "United Kingdom",
    "uae": "United Arab Emirates", "emirates": "United Arab Emirates",
    "deutschland": "Germany", "holland": "Netherlands", "the netherlands": "Netherlands",
    "south korea": "South Korea", "korea": "South Korea", "bharat": "India",
}


def _norm_header(h):
    return re.sub(r"[^a-z0-9 ]+", " ", str(h or "").lower()).strip()


def map_columns(headers):
    mapping = {}
    norm = {h: _norm_header(h) for h in headers}
    for field, syns in SYNONYMS.items():
        for h, n in norm.items():
            if n in syns and h not in mapping.values():
                mapping[field] = h
                break
    return mapping


def normalise_website(w):
    w = (w or "").strip()
    if not w:
        return ""
    if not re.match(r"^https?://", w, re.I):
        w = "https://" + w.lstrip("/")
    p = urlparse(w)
    if not p.netloc or "." not in p.netloc and "localhost" not in p.netloc and not re.match(r"^[\d.:]+$", p.netloc):
        return ""
    return w


def normalise_country(c):
    c = (c or "").strip()
    return COUNTRY_ALIASES.get(c.lower(), c.title() if c.islower() or c.isupper() else c)


def google_sheet_csv_url(url):
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_\-]+)", url)
    if not m:
        raise ValueError("That does not look like a Google Sheets link.")
    gid = re.search(r"[#&?]gid=(\d+)", url)
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid.group(1) if gid else 0}"


def read_table(filename, data):
    """Return list[dict] from raw bytes of a csv/xlsx file."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        headers = [str(h) if h is not None else "" for h in next(it, [])]
        out = []
        for r in it:
            if all(v is None or str(v).strip() == "" for v in r):
                continue
            out.append({headers[i]: ("" if v is None else str(v)) for i, v in enumerate(r) if i < len(headers)})
        return out
    text = data.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [dict(r) for r in csv.DictReader(io.StringIO(text), dialect=dialect)]


def fetch_google_sheet(url):
    csv_url = google_sheet_csv_url(url)
    r = requests.get(csv_url, timeout=20)
    if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
        raise ValueError("Could not read the sheet. Share it as 'Anyone with the link – Viewer' and try again.")
    return read_table("sheet.csv", r.content)


def import_rows(rows, source="upload"):
    report = {"total": len(rows), "added": 0, "duplicates": [], "invalid": [], "opted_out": [], "mapping": {}}
    if not rows:
        return report
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Too many rows (max {MAX_ROWS}).")
    mapping = map_columns(list(rows[0].keys()))
    report["mapping"] = mapping
    missing = [f for f in ("email", "company") if f not in mapping]
    if missing:
        raise ValueError(
            "Could not find required column(s): " + ", ".join(missing) +
            ". Expected headers like: Name, Email, Designation, Company, Website, Country.")
    seen = set()
    for i, r in enumerate(rows, start=2):  # row 1 is header
        get = lambda f: (r.get(mapping.get(f, ""), "") or "").strip()
        email = get("email").lower()
        if not EMAIL_RE.match(email):
            report["invalid"].append({"row": i, "email": email, "reason": "invalid email address"})
            continue
        if email in seen or db.one("SELECT 1 x FROM leads WHERE email=?", (email,)):
            report["duplicates"].append({"row": i, "email": email})
            continue
        seen.add(email)
        website_raw = get("website")
        website = normalise_website(website_raw)
        company = get("company") or email.split("@")[1].split(".")[0].title()
        status = "new"
        if db.one("SELECT 1 x FROM optouts WHERE email=?", (email,)):
            status = "opted_out"
            report["opted_out"].append({"row": i, "email": email})
        db.execute(
            "INSERT INTO leads(name,email,designation,company,website,country,status,source,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (get("name"), email, get("designation"), company, website, normalise_country(get("country")),
             status, source, db.now()))
        report["added"] += 1
        if website_raw and not website:
            report["invalid"].append({"row": i, "email": email, "reason": "imported, but website looks invalid"})
    return report
