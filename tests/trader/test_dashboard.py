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
    assert narrator.current_phase({}, NOW.replace(hour=16)) == "done"
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
