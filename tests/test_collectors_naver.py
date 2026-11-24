"""네이버 증권 JSON 기반 collector 스모크 테스트 (네트워크 없음).

tests/fixtures/naver/*.json 은 2026-11-24 m.stock.naver.com/api 실제 응답을 저장한 것이다
(거래상위는 30종목으로 잘라 저장). _naver.get_json 을 fixture 로더로 바꿔 끼워
파싱·정렬 로직만 검증한다. API 형식이 바뀌면 fixture 를 새로 받아 갱신할 것.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from src.collectors import _naver, flows, hot_sectors, issues, themes

FIX = Path(__file__).parent / "fixtures" / "naver"


def _load(name: str):
    path = FIX / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _fake_get_json(path: str, params=None, **_kw):
    if path == "/news/list":
        return _load("mainnews")
    if m := re.fullmatch(r"/stocks/quantTop/(KOSPI|KOSDAQ)", path):
        return _load(f"quant_{m.group(1).lower()}")
    if path == "/stocks/theme":
        return _load("theme_list")
    if m := re.fullmatch(r"/stocks/theme/(\d+)", path):
        return _load(f"theme_{m.group(1)}")  # fixture 없는 테마는 None (요청 실패 취급)
    if m := re.fullmatch(r"/stock/(\d{6})/trend", path):
        return _load(f"trend_{m.group(1)}")
    raise AssertionError(f"예상치 못한 경로: {path}")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(_naver, "get_json", _fake_get_json)


def test_top_issues():
    got = issues.fetch_top_issues(3)
    assert len(got) == 3
    assert got[0].title == "엔비디아 하락에 베팅했다가 낭패…인버스·공매도 투자자 울상"
    assert got[0].url == "https://n.news.naver.com/article/277/0005846915"
    assert all(i.url.startswith("https://n.news.naver.com/article/") for i in got)
    assert len({i.title for i in got}) == 3


def test_trading_value_top():
    got = flows.fetch_trading_value_top(dt.date(2026, 11, 24), 5)
    assert len(got) == 5
    values = [s.trade_value for s in got]
    assert values == sorted(values, reverse=True)
    assert all(v and v > 1e10 for v in values)          # 원 단위 (상위권은 100억 이상)
    assert all(s.currency == "KRW" and s.close for s in got)
    assert len({s.name for s in got}) == 5


def test_investor_flows(monkeypatch):
    monkeypatch.setattr(flows, "_domestic_universe", lambda: [("삼성전자", "005930")])
    got = flows.fetch_investor_flows(dt.date(2026, 11, 24), 3)
    # fixture 최신행(2026-11-23): 종가 180,600 · 기관 +661,271 · 외국인 -45,179
    inst_buy = got["buy"]["기관"]
    assert [s.name for s in inst_buy] == ["삼성전자"]
    assert inst_buy[0].trade_value == pytest.approx(661_271 * 180_600)
    assert [s.name for s in got["sell"]["외국인"]] == ["삼성전자"]
    assert got["buy"]["외국인"] == [] and got["sell"]["기관"] == []
    assert got["retail_buy"] == []  # -(기관+외국인) < 0


def test_hot_extra_themes():
    got = themes.fetch_hot_extra_themes(top_n=2)
    assert got, "낯선 급등 테마가 1개 이상 나와야 함"
    assert got[0].name == "MLCC(적층세라믹콘덴서)"
    assert got[0].change_pct >= themes._MIN_PCT
    assert got[0].leaders == ["아모텍", "대주전자재료"]
    assert not any(themes._is_covered(t.name) for t in got)


def test_trending_themes():
    groups, movers = hot_sectors.fetch_trending(themes_n=3, per_sector=2)
    assert len(groups) == 3
    heads = [g.headline_pct for g in groups]
    assert heads == sorted(heads, reverse=True)
    assert all(g.stocks and len(g.stocks) <= 2 for g in groups)
    assert all(s.change_pct < hot_sectors._LIMITUP_PCT for g in groups for s in g.stocks)
    assert movers and all(s.change_pct >= hot_sectors._LIMITUP_PCT for s in movers)


def test_get_json_failure_is_soft(monkeypatch):
    monkeypatch.setattr(_naver, "get_json", lambda *a, **k: None)
    assert issues.fetch_top_issues() == []
    assert flows.fetch_trading_value_top(dt.date(2026, 11, 24)) == []
    assert themes.fetch_hot_extra_themes() == []
    assert hot_sectors.fetch_trending() == ([], [])
