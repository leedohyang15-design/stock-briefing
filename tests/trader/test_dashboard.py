"""대시보드: narrator 문장·단계, 서버 API."""
import datetime as dt
import json
import threading
import urllib.request

from src.trader import narrator
from src.trader.journal import Journal
from src.trader.models import KST
from src.trader.web.server import build_state, serve

NOW = dt.datetime(2026, 11, 23, 10, 30, tzinfo=KST)


def test_phase_and_alive():
    assert narrator.current_phase({}, NOW.replace(hour=7)) == "waiting"
    assert narrator.current_phase({}, NOW.replace(hour=16)) == "off"     # 오늘 한 번도 안 돎
    assert narrator.current_phase({"key": "intraday"}, NOW) == "intraday"
    age = narrator.heartbeat_age((NOW - dt.timedelta(seconds=30)).isoformat(), NOW)
    assert narrator.is_alive("intraday", age) and not narrator.is_alive("intraday", 300)
    assert narrator.is_alive("premarket", 300)                       # 장전 분석은 LLM 때문에 여유
    assert not narrator.is_alive("intraday", None)


def test_banner_texts():
    weak = {"regime": {"decision": "reject", "reason": "x"}, "index": {"KOSPI": -3.3, "KOSDAQ": -2.0}}
    ip = [{"name": "A", "status": "watch"}]
    b = narrator.now_text("intraday", True, weak, ip, NOW)
    assert "쉬는 중" in b["now"] and "-3.30%" in b["now"] and b["tone"] == "warn"
    b = narrator.now_text("intraday", True, {"regime": {"decision": "pass"}}, [{"name": "B", "status": "pending"}], NOW)
    assert "B 매수 승인" in b["now"]
    hold = {"regime": {"decision": "pass"}, "positions": [{"name": "C", "qty": 9}]}
    assert "보유 중: C 9주" in narrator.now_text("intraday", True, hold, ip, NOW)["now"]
    assert "꺼져" in narrator.now_text("intraday", False, {}, [], NOW)["now"]
    assert narrator.now_text("done", False, {}, [], NOW)["tone"] == "idle"
    assert "09:00" in narrator.now_text("ready", True, {}, [], NOW)["now"]
    assert narrator.agent_line(13, "reject", "코스피 약세").endswith("✋")
    assert "앞에서 막혀" in narrator.agent_line(12, "wait", "앞 단계 거부로 검사하지 않음")


def test_state_api(tmp_path):
    j = Journal(tmp_path / "t.db")
    j.now_fn = lambda: NOW
    j.snapshot("status", {"ts": NOW.isoformat(), "mode": "paper", "positions": [{"code": "111111", "name": "A", "qty": 9,
                          "avg_price": 100, "stop": 90}], "regime": {"decision": "pass"}})
    j.snapshot("phase", {"key": "intraday", "ts": NOW.isoformat(), "history": {}})
    j.snapshot("heartbeat", {"ts": NOW.isoformat()})
    j.snapshot("inplay", [{"code": "111111", "name": "A", "status": "done"}])
    from src.trader.models import AgentResult, Bar
    j.agent_result(AgentResult(13, "시장 분위기", "reject", "약세"), "111111", 1)
    j.save_bars("111111", [Bar("0901", 1, 2, 0.5, 1.5, 10, date=NOW.strftime("%Y%m%d"))])
    s = build_state(j, NOW)
    assert s["alive"] and s["inplay"][0]["label"] == "보유 중" and s["results"][0]["line"].endswith("✋")
    assert "보유 중: A 9주" in s["banner"]["now"]
    # 어제 상태는 오늘 화면에 쓰지 않음
    s2 = build_state(j, NOW + dt.timedelta(days=1))
    assert s2["status"] == {} and s2["inplay"] == [] and not s2["alive"]
    httpd = serve(j, port=0, block=False)
    port = httpd.server_address[1]
    try:
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
        assert "lightweight-charts" in html and "unpkg" not in html
        js = urllib.request.urlopen(f"http://127.0.0.1:{port}/vendor/lightweight-charts.standalone.production.js").read()
        assert b"TradingView" in js[:300]
        bars = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bars?code=111111&date={NOW.strftime('%Y%m%d')}").read())
        assert bars[0]["close"] == 1.5
        assert "report" in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/week").read())
    finally:
        httpd.shutdown()


def test_password_protection_and_db_download(tmp_path):
    import base64
    import sqlite3
    import urllib.error
    j = Journal(tmp_path / "t.db")
    j.event("정보", "hello")
    httpd = serve(j, port=0, block=False, host="127.0.0.1", password="s3cret")
    port = httpd.server_address[1]

    def get(path, pw=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
        if pw is not None:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"me:{pw}".encode()).decode())
        try:
            r = urllib.request.urlopen(req)
            return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
    try:
        assert get("/")[0] == 401 and get("/", "wrong")[0] == 401 and get("/download/trader.db")[0] == 401
        assert get("/", "s3cret")[0] == 200
        assert get("/_stcore/health")[0] == 200                      # 상태 확인은 인증 없이
        code, body = get("/download/trader.db", "s3cret")
        assert code == 200
        p = tmp_path / "dl.db"
        p.write_bytes(body)
        assert sqlite3.connect(p).execute("SELECT text FROM events").fetchone()[0] == "hello"
    finally:
        httpd.shutdown()
    open_srv = serve(j, port=0, block=False, password="")              # 비밀번호 없으면 기존처럼 열림
    try:
        assert urllib.request.urlopen(f"http://127.0.0.1:{open_srv.server_address[1]}/").status == 200
    finally:
        open_srv.shutdown()


def test_premarket_progress_shown_in_banner():
    b = narrator.now_text("premarket", True, {}, [], NOW, "과거 데이터 받는 중 3/40: A")
    assert b["now"].startswith("과거 데이터 받는 중 3/40")
    assert "장전 분석팀" in narrator.now_text("premarket", True, {}, [], NOW)["now"]


def test_premarket_writes_progress_and_heartbeat(tmp_path):
    from .test_day_flow import _trader
    t, j, kis = _trader(tmp_path, lambda h: 10100)
    t.start(1_000_000)
    seen = []
    orig = t.progress
    t.progress = lambda text: (seen.append(text), orig(text))
    t.premarket()
    assert any("과거 데이터 받는 중 1/" in x for x in seen) and seen[-1] == ""
    assert j.get_snapshot("heartbeat")["ts"]


def test_never_ran_today_is_off_not_done():
    late = NOW.replace(hour=23, minute=57)
    key = narrator.current_phase({}, late, "us")
    assert key == "off"
    b = narrator.now_text(key, False, {}, [], late, "", "us")
    assert "아직 실행되지 않았어요" in b["now"] and "미장_모의투자_시작.bat" in b["next"]
    assert narrator.current_phase({"key": "done"}, late, "us") == "done"
    early = NOW.replace(hour=7)
    assert "아직 켜지지 않았어요" in narrator.now_text(narrator.current_phase({}, early), False, {}, [], early)["now"]
