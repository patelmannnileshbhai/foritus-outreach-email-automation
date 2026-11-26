# ForITus Outreach Desk – AI-powered automated cold mailing system

Research → personalise → review/approve → send safely → track → follow up. 100 % free tools, no hard-coded credentials.

## Quick start
```bash
pip install -r requirements.txt
cp .env.example .env        # optional: add a free Gemini/Groq key and SMTP details
python app.py               # open http://127.0.0.1:5000
```
Works with **zero keys**: offline composer + `.eml` outbox. Add `GEMINI_API_KEY` (free) for LLM-written emails.

### Offline demo (no internet needed)
```bash
python demo/serve.py                              # fictional company sites on :8800
ALLOW_PRIVATE_FETCH=1 python app.py               # (Windows: set ALLOW_PRIVATE_FETCH=1)
```
Import `demo/sample_leads_demo.csv` (includes a duplicate, invalid email and unreachable site to show validation/failure handling).

## Requirement coverage
| Requirement | Where |
|---|---|
| CSV / Excel / Google Sheet input | `core/ingest.py` (auto column mapping, validation, dedupe) |
| Company research (industry, products, opportunities) | `core/research.py` – robots.txt-aware, SSRF-guarded; evidence ledger F1..Fn |
| Unique personalised emails, regional language/tone | `core/generator.py`, `core/regions.py` (US/UK/AU/IN/Middle-East English, DE/FR/ES) |
| No fabricated info | LLM sees only evidence facts; `core/quality.py` blocks invented numbers/claims; fallback to grounded composer |
| Sending with daily limit | `core/sender.py` (SMTP or .eml outbox) |
| Preview + approval | Review desk; send only `approved` emails |
| Duplicate prevention, failures, opt-out, history | DB unique(lead,step), atomic claim, retries/permanent-vs-temporary errors, `optouts`, history + CSV export |
| Bonus: follow-ups, reply detection, lead scoring, dashboard, quality verification | `followups.py`, `replies.py` (IMAP + manual), `scoring.py`, Overview page, `quality.py` |
| Tracking | open pixel `/t/o/<token>.gif`, one-click unsubscribe `/u/<token>` |

## Safety
- TEST_MODE (default on): in SMTP mode only `TEST_ALLOWLIST` addresses can receive mail. Sample leads use `example.com`, so replace with your own test inboxes.
- Admin UI/API is local-only; only `/t/` and `/u/` are public (use a free cloudflared/ngrok tunnel + `BASE_URL` for real opens).
- Secrets only in `.env`.

## Suggested video flow
1 Settings/.env wiring → 2 Import leads → 3 Research (evidence ledger) → 4 Draft → 5 Review desk (quality, edit, test-copy) → 6 Approve & Send (limit, outbox/SMTP) → 7 "Open as recipient" (logs open), unsubscribe link, log a reply → 8 Draft follow-ups → Overview dashboard.

## Tests
`python tests/mock_llm.py` runs a mock OpenAI-compatible server (:8801) to exercise the LLM path offline
(`LLM_PROVIDER=openai OPENAI_API_KEY=x OPENAI_BASE_URL=http://127.0.0.1:8801/v1`).
