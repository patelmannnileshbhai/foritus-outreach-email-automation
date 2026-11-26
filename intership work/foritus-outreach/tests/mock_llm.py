"""Mock OpenAI-compatible server (offline testing of the LLM code path). Returns plausible grounded JSON."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(n))
        user = json.loads(req["messages"][1]["content"])
        if "forItus_services" in user:
            facts = user["facts"]
            ev = [f["id"] for f in facts[:2]] or []
            out = {"summary": "Mock summary: " + user["company"], "industry": "Mock Industry",
                   "opportunities": [{"service": "workflow_automation", "rationale": "Mock rationale for automation.", "evidence": ev},
                                     {"service": "bogus_service", "rationale": "x", "evidence": ev},
                                     {"service": "ai_docs", "rationale": "Invented evidence id.", "evidence": ["F999"]}]}
        else:
            r = user["recipient"]; facts = user["facts"]
            fid = facts[0]["id"] if facts else None
            if user.get("previous_email"):
                body = f"Hello {r['first_name']},\n\nA short follow-up on my earlier note about {r['company']}. Happy to share a concrete example if useful.\n\nWould a quick call help?"
            elif "NUMBER_TEST" in json.dumps(user):
                body = "x"
            else:
                body = (f"Hello {r['first_name']},\n\nI was reading about {r['company']} and {facts[0]['text'][:60] if facts else 'your work'} stood out. "
                        f"We help teams automate repetitive hand-offs and add practical AI. With our clients we typically see 40% faster turnaround.\n\n"
                        f"Would you be open to a short call next week?\n\nBest regards,\nSomebody")
            out = {"subject": f"An idea for {r['company']}", "body": body, "facts_used": [fid] if fid else []}
        resp = {"choices": [{"message": {"content": "```json\n" + json.dumps(out) + "\n```"}}]}
        data = json.dumps(resp).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8801), H).serve_forever()
