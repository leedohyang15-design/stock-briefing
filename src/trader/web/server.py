"""새 대시보드 서버 (표준 라이브러리만 사용, 보기 전용).

    python -m src.trader.web.server            # http://localhost:8501
    python -m src.trader.web.server --demo     # 데모 데이터 (먼저 python -m src.trader.demo)
    python -m src.trader.web.server --lan      # 같은 와이파이 휴대폰에서도 접속
"""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .. import narrator
from ..agents import NAMES
from ..journal import Journal
from ..models import now_kst

HERE = Path(__file__).resolve().parent


def build_state(j: Journal, now=None) -> Dict[str, Any]:
    now = now or now_kst()
    today = now.strftime("%Y%m%d")
    iso_today = now.strftime("%Y-%m-%d")
    status = j.get_snapshot("status", {}) or {}
    if str(status.get("ts", ""))[:10] != iso_today:
        status = {}
    phase = j.get_snapshot("phase", {}) or {}
    if str(phase.get("ts", ""))[:10] != iso_today:
        phase = {}
    hb = (j.get_snapshot("heartbeat", {}) or {}).get("ts")
    key = narrator.current_phase(phase, now)
    alive = narrator.is_alive(key, narrator.heartbeat_age(hb, now))
    inplay = j.get_snapshot("inplay", []) or [] if status else []
    pre = j.get_snapshot("premarket", {}) or {}
    if not status and not phase:
        pre = {}
    positions = {p["code"]: p for p in status.get("positions", [])}
    for i in inplay:
        i["label"] = narrator.STATUS_LABEL.get(i.get("status"), i.get("status"))
        if i["code"] in positions:
            p = positions[i["code"]]
            i["label"] = "보유 중"
            i["position"] = p
    results = j.query("SELECT id, ts, signal_id, code, no, agent, decision, reason, data FROM agent_results "
                      "WHERE date=? ORDER BY id DESC LIMIT 600", (today,))
    for r in results:
        r["line"] = narrator.agent_line(r["no"], r["decision"], r["reason"])
        r["data"] = json.loads(r["data"]) if r.get("data") else {}
    events = j.query("SELECT ts, kind, code, text FROM events WHERE date=? ORDER BY id DESC LIMIT 80", (today,))
    for e in events:
        e["line"] = narrator.event_text(e["kind"], e["text"])
    return {
        "now": now.isoformat(timespec="seconds"),
        "phase": {"key": key, "history": phase.get("history", {}), "steps": narrator.PHASES},
        "alive": alive,
        "banner": narrator.now_text(key, alive, status, inplay, now),
        "status": status,
        "premarket": pre,
        "inplay": inplay,
        "signals": j.query("SELECT * FROM signals WHERE date=? ORDER BY id DESC LIMIT 100", (today,)),
        "results": results,
        "events": events,
        "trades": j.query("SELECT * FROM trades WHERE date=? ORDER BY id", (today,)),
        "names": NAMES,
    }


def build_week(j: Journal) -> Dict[str, Any]:
    return {
        "report": j.get_snapshot("weekly", {}) or {},
        "days": j.query("SELECT * FROM daily ORDER BY date DESC LIMIT 5")[::-1],
        "proposals": j.query("SELECT id, ts, changes, status FROM proposals ORDER BY id DESC LIMIT 3"),
    }


def make_handler(j: Journal, password: Optional[str] = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 콘솔 조용히
            pass

        def _authorized(self) -> bool:
            """DASHBOARD_PASSWORD 가 있으면 HTTP Basic 인증 (아이디는 아무거나, 비밀번호만 확인)."""
            if not password:
                return True
            h = self.headers.get("Authorization", "")
            if not h.startswith("Basic "):
                return False
            try:
                _, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
            except Exception:  # noqa: BLE001
                return False
            return hmac.compare_digest(pw.encode("utf-8"), password.encode("utf-8"))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any) -> None:
            self._send(200, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            if u.path != "/_stcore/health" and not self._authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="AI Trader", charset="UTF-8"')
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write("비밀번호가 필요합니다 (.env 의 DASHBOARD_PASSWORD)".encode("utf-8"))
                return
            try:
                if u.path in ("/", "/index.html"):
                    self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif u.path == "/vendor/lightweight-charts.standalone.production.js":
                    self._send(200, (HERE / "vendor" / "lightweight-charts.standalone.production.js").read_bytes(),
                               "application/javascript; charset=utf-8")
                elif u.path == "/api/state":
                    self._json(build_state(j))
                elif u.path == "/api/bars":
                    q = parse_qs(u.query)
                    code = (q.get("code") or [""])[0]
                    date = (q.get("date") or [now_kst().strftime("%Y%m%d")])[0]
                    self._json([b.__dict__ for b in j.bars(code, date)])
                elif u.path == "/api/week":
                    self._json(build_week(j))
                elif u.path == "/download/trader.db":
                    with j.lock:
                        data = j.conn.serialize()   # 쓰는 중이어도 일관된 스냅샷
                    self.send_response(200)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Disposition", f'attachment; filename="trader_{now_kst():%Y%m%d}.db"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif u.path == "/_stcore/health":
                    self._send(200, b"ok", "text/plain")
                else:
                    self._send(404, b"not found", "text/plain")
            except Exception as e:  # noqa: BLE001
                self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")

    return Handler


def serve(journal: Optional[Journal] = None, port: int = 8501, lan: bool = False, block: bool = True,
          host: Optional[str] = None, password: Optional[str] = None):
    j = journal or Journal()
    if password is None:
        password = os.getenv("DASHBOARD_PASSWORD", "").strip() or None
    host = host or ("0.0.0.0" if lan else "127.0.0.1")
    if host not in ("127.0.0.1", "localhost") and not password:
        print("⚠️ 외부 접속을 열었는데 DASHBOARD_PASSWORD 가 없습니다. 누구나 대시보드를 볼 수 있습니다.")
    httpd = ThreadingHTTPServer((host, port), make_handler(j, password))
    if block:
        httpd.serve_forever()
    else:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--lan", action="store_true", help="같은 와이파이 기기에서 접속 허용")
    ap.add_argument("--port", type=int, default=8501)
    ap.add_argument("--host", default=None, help="서버에서는 0.0.0.0 (DASHBOARD_PASSWORD 로 비밀번호 보호)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if args.demo:
        from ..demo import DEMO_DB
        j = Journal(DEMO_DB)
    else:
        j = Journal()
    url = f"http://localhost:{args.port}"
    where = f"이 서버의 공인 IP:{args.port}" if args.host and args.host not in ("127.0.0.1", "localhost") else url
    print(f"대시보드: {where}  (끄려면 Ctrl+C)")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        serve(j, args.port, args.lan, host=args.host)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
