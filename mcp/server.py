"""Pipeline Doctor UI: web view of the evidence log and the agent's (LLM) reports, grouped by DAG, plus a chat with Gemini.
Standard library only.

  GET  /              the page (index.html)
  GET  /api/entries   {"evidence": [...], "agent": [...]}  newest first, each with dag/run/failed fields
  GET  /api/status    proxy to the agent: what it is investigating now and what is queued
  POST /api/chat      proxy to the agent: {"messages": [...], "dag_id": "..."} -> {"reply", "tools", "model"}
Env: EVIDENCE_FILE, AGENT_FILE, AGENT_URL (default http://doctor-agent:8001), AGENT_AUTH_TOKEN
"""
import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FILES = {
    "evidence": os.environ.get("EVIDENCE_FILE", "/evidence/pipeline_doctor_notifications.log"),
    "agent": os.environ.get("AGENT_FILE", "/notifications/pipeline_doctor.log"),
}
AGENT_URL = os.environ.get("AGENT_URL", "http://doctor-agent:8001").rstrip("/")
AGENT_TOKEN = os.environ.get("AGENT_AUTH_TOKEN", "")
HEADER = re.compile(r"^==== (\S+)(?: \| (.*?))? ====$", re.M)
AGENT_TITLE = re.compile(r"^Pipeline Doctor agent \| DAG (\S+) \| run (.+)$")
EVIDENCE_TITLE = re.compile(r"^DAG (\S+) FAILED \(run (.+)\)$")
MAX_BYTES = 2_000_000  # only the tail of very large files
MAX_CHAT_BYTES = 400_000


def parse(kind: str, path: str) -> list[dict]:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - MAX_BYTES))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    marks = list(HEADER.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        title, body = m.group(2) or "", text[m.end():end].strip()
        first, _, rest = body.partition("\n")
        dag = run = ""
        if kind == "agent" and (t := AGENT_TITLE.match(first)):
            dag, run, body = t.group(1), t.group(2), rest.strip()
        elif kind == "evidence":
            dag = title.split(" | ")[0]
            if t := EVIDENCE_TITLE.match(first):
                dag, run = t.group(1), t.group(2)
        out.append({"time": m.group(1), "dag": dag or "(unknown)", "run": run, "body": body,
                    "failed": kind == "agent" and body.startswith("investigation failed")})
    return out[::-1]


def agent_call(path: str, payload: dict = None, timeout: int = 10):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {AGENT_TOKEN}"} if AGENT_TOKEN else {})}
    req = urllib.request.Request(AGENT_URL + path, json.dumps(payload).encode() if payload is not None else None, headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        msg = f"Cannot reach the agent at {AGENT_URL} ({type(e).__name__}). Start it with: docker compose --profile agent up -d"
        return 502, json.dumps({"error": msg}).encode()


PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), encoding="utf-8").read()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/entries":
            self._send(200, json.dumps({k: parse(k, p) for k, p in FILES.items()}).encode())
        elif path == "/api/status":
            code, body = agent_call("/status", timeout=5)
            self._send(200, body if code == 200 else json.dumps({"current": None, "queued": [], "error": "agent unreachable"}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/chat":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CHAT_BYTES:
            self._send(413, b'{"error":"message too large"}')
            return
        try:
            payload = json.loads(self.rfile.read(n))
        except ValueError:
            self._send(400, b'{"error":"invalid JSON"}')
            return
        code, body = agent_call("/chat", payload, timeout=300)
        self._send(code, body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("UI_PORT", "8002"))), Handler).serve_forever()
