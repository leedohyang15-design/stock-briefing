from src.trader import strategy as st
from src.trader.agents import intraday, premarket, timemachine
from src.trader.models import Bar, Candidate, Quote, Trade
from src.trader.risk import DayState, evaluate
from src.trader.settings import Settings

from .fakes import FakeLLM, minute_grid

S = Settings.load()


def _ip(bullish=True):
    rng = st.OpeningRange(high=10150, low=9990, open=10000, close=10100 if bullish else 9990, volume=1, end="0905")
    return intraday.InPlay("111111", "샘플", 4.0, 600, rng, 1e10, 10000)


def test_orb_check_states():
    assert intraday.orb_check(10200, _ip(), True).decision == "pass"
    assert intraday.orb_check(10100, _ip(), True).decision == "wait"
    assert intraday.orb_check(10200, _ip(False), True).decision == "reject"


def test_imbalance_check():
    up = [Trade("", 100 + i, 10) for i in range(10, 0, -1)]
    down = [Trade("", 100 - i, 10) for i in range(10, 0, -1)]
    assert intraday.imbalance_check(up, 30, 0.0).decision == "pass"
    assert intraday.imbalance_check(down, 30, 0.0).decision == "reject"
    assert intraday.imbalance_check([], 30, 0.0).decision == "reject"


def test_news_check_keyword_and_llm_fallbacks():
    kw = S.news["reject_keywords"]
    bad = intraday.news_check(FakeLLM(), "샘플", [], [{"title": "유상증자 결정", "date": ""}], kw, True)
    assert bad.decision == "reject" and "유상증자" in bad.reason
    news = [{"title": "실적 개선 기대", "date": ""}]
    assert intraday.news_check(FakeLLM(), "샘플", news, [], kw, True).decision == "reject"   # LLM 없음 → 보수적 거부
    assert intraday.news_check(FakeLLM(), "샘플", news, [], kw, False).decision == "pass"
    ok = intraday.news_check(FakeLLM([{"verdict": "pass", "reason": "악재 없음"}]), "샘플", news, [], kw, True)
    assert ok.decision == "pass"
    junk = intraday.news_check(FakeLLM([{"foo": 1}]), "샘플", news, [], kw, True)
    assert junk.decision == "reject"


def test_regime_rules():
    # 뚜렷한 약세(-1% 미만)일 때만 막는다 (예전: 오전에 0% 아래면 막음 → 너무 많은 날을 버림)
    assert intraday.regime_check(-1.5, -1.0).decision == "reject"
    assert intraday.regime_check(-0.5, -1.0).decision == "pass"
    assert intraday.regime_check(0.8, -1.0).decision == "pass"


def test_stop_floor_by_ticks_and_cost():
    cfg = {"stop_atr_mult": 0.1, "min_stop_ticks": 5, "min_stop_cost_mult": 2.0}
    # ATR 200 → 20원 vs 5호가 50원 vs 비용 2×0.23%=46원 → 50원
    assert st.stop_for(10_000, 200, cfg, 0.23) == 9_950
    # ATR 큰 종목은 논문 규칙(ATR×0.1)이 그대로
    assert st.stop_for(10_000, 2_000, cfg, 0.23) == 9_800


def test_measured_relative_volume_used_when_enough_days():
    cfg = dict(S.strategy)
    daily = [Bar(str(i), 10000, 10300, 9700, 10000, 1_000_000) for i in range(20)]
    orb = [Bar("0900", 10000, 10100, 9990, 10050, 60_000), Bar("0904", 10050, 10150, 10000, 10100, 60_000)]
    c = [Candidate("A", "a")]
    est, _ = intraday.scan_stocks_in_play(c, {"A": orb}, {"A": daily}, cfg)
    assert not est[0].relvol_measured and round(est[0].relvol, 1) == 2.4      # 120k / (1M×0.05)
    meas, r = intraday.scan_stocks_in_play(c, {"A": orb}, {"A": daily}, cfg, {"A": (40_000, 12)})
    assert meas[0].relvol_measured and meas[0].relvol == 3.0                 # 120k / 40k
    few, _ = intraday.scan_stocks_in_play(c, {"A": orb}, {"A": daily}, cfg, {"A": (40_000, 5)})
    assert not few[0].relvol_measured                                        # 10일 미만 → 추정
    days = [[Bar("0900", 1, 1, 1, 1, 10_000), Bar("0904", 1, 1, 1, 1, 30_000)], [Bar("0902", 1, 1, 1, 1, 20_000)], []]
    assert st.open_volume_avg(days, 5) == (30_000, 2)


def test_vi_check():
    q = Quote("1", "a", 10_950, 10_000, 10_950, 9_900, 10_000, 9.5, 1, upper_limit=13_000)
    assert intraday.vi_check(q, 10_000, 10.0, 1.0).decision == "reject"
    q.price = 10_300
    assert intraday.vi_check(q, 10_000, 10.0, 1.0).decision == "pass"
    q.vi_active = True
    assert intraday.vi_check(q, 10_000, 10.0, 1.0).decision == "reject"


def test_stocks_in_play_filters_and_ranking():
    cfg = dict(S.strategy)
    daily = [Bar(str(i), 10000, 10300, 9700, 10000, 1_000_000) for i in range(20)]
    def orb(vol):
        return [Bar("0900", 10000, 10100, 9990, 10050, vol / 2), Bar("0904", 10050, 10150, 10000, 10100, vol / 2)]
    cands = [Candidate("A", "a"), Candidate("B", "b"), Candidate("C", "c")]
    top, r = intraday.scan_stocks_in_play(cands, {"A": orb(200_000), "B": orb(400_000), "C": orb(10_000)},
                                          {"A": daily, "B": daily, "C": daily}, cfg)
    assert [t.code for t in top] == ["B", "A"]           # C 는 상대거래량 0.2 < 1
    assert "C" in r.data["skipped"]


def test_risk_limits():
    risk = S.risk
    s = DayState(start_equity=1_000_000, cash=1_000_000)
    ok = evaluate("X", 10_000, 9_940, "1000", s, risk)
    assert ok.decision == "pass" and ok.data["qty"] == 9 and ok.data["limit_price"] == 10_010
    assert evaluate("X", 10_000, 9_940, "1511", s, risk).decision == "reject"     # 진입 마감
    s.entries = 5
    assert evaluate("X", 10_000, 9_940, "1000", s, risk).decision == "reject"
    s.entries, s.realized_pnl = 0, -30_000
    r = evaluate("X", 10_000, 9_940, "1000", s, risk)
    assert r.decision == "reject" and s.stopped                                  # 일 손실 한도
    s2 = DayState(start_equity=1_000_000, cash=1_000_000, traded_codes={"X"})
    assert evaluate("X", 10_000, 9_940, "1000", s2, risk).decision == "reject"   # 같은 종목 재진입 금지
    s3 = DayState(start_equity=1_000_000, cash=1_000_000, aggression="low", entries=2)
    assert evaluate("Y", 10_000, 9_940, "1000", s3, risk).decision == "reject"   # 공격성 low → 한도 절반


def _hist(drift):
    out = {}
    for k in range(15):
        bars, p = [], 10000.0
        for t in minute_grid():
            nxt = p * (1 + drift)
            bars.append(Bar(t, p, max(p, nxt), min(p, nxt) * 0.9999, nxt, 1000, date=f"d{k}"))
            p = nxt
        out[f"d{k}"] = bars
    return out


def test_timemachine_pass_and_reject():
    tm, cfg = dict(S.timemachine), dict(S.strategy)
    tm["paths"] = 2000
    up = timemachine.check(_hist(0.0002), "1000", "1515", 10_000, 9_900, 600, tm, cfg, 0.23)
    assert up.decision == "pass" and up.data["p_eod_profit"] > 90
    down = timemachine.check(_hist(-0.0002), "1000", "1515", 10_000, 9_900, 600, tm, cfg, 0.23)
    assert down.decision == "reject" and down.data["p_stop"] > 90
    few = timemachine.check({"d": _hist(0.0)["d0"]}, "1000", "1515", 10_000, 9_900, 600, tm, cfg, 0.23)
    assert few.decision == "info"                                                # 데이터 부족 → 거부 안 함


def test_premarket_without_llm_falls_back_to_pool():
    pool = [{"code": "000001", "name": "가", "price": 1, "change_pct": 1.0, "value_krw": 5e10},
            {"code": "000002", "name": "나", "price": 1, "change_pct": 1.0, "value_krw": 4e10}]
    inputs = premarket.PremarketInputs(indices=lambda: ["나스닥 1 (+1.00%)"], headlines=lambda: ["뉴스"],
                                       themes=lambda: ["AI"], pool=lambda: pool,
                                       notices=lambda c: [{"title": "유상증자 결정", "date": ""}] if c == "000002" else [])
    rep = premarket.run_premarket(FakeLLM(), inputs, S.news["reject_keywords"])
    assert [c.code for c in rep.watchlist] == ["000001"]
    assert "000002" in rep.excluded
    assert [r.no for r in rep.results] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_premarket_pm_llm_choice_validated():
    pool = [{"code": "000001", "name": "가", "price": 1, "change_pct": 1.0, "value_krw": 5e10},
            {"code": "000002", "name": "나", "price": 1, "change_pct": 1.0, "value_krw": 4e10}]
    llm = FakeLLM([{"score": 1, "summary": "강세"}, {"positive": [], "negative": [], "summary": "s"},
                   {"items": [{"code": "2", "bull": "좋음", "bear": "급등 위험"}, {"code": "000001", "bull": "무난"}]},
                   {"watchlist": [{"code": "000002", "note": "n"}, {"code": "123456", "note": "없는 종목"}],
                    "exclude": [], "aggression": "high", "summary": "s"}])
    inputs = premarket.PremarketInputs(indices=lambda: ["나스닥"], headlines=lambda: ["뉴스"], themes=lambda: [],
                                       pool=lambda: pool, notices=lambda c: [])
    rep = premarket.run_premarket(llm, inputs, [])
    assert [c.code for c in rep.watchlist] == ["000002"] and rep.aggression == "high"
    assert rep.bull == {"000002": "좋음", "000001": "무난"}
    assert rep.bear["000002"] == "급등 위험" and "데이터 기반" in rep.bear["000001"]   # 빠진 약세론은 데이터로 보충
    from src.trader.agents.premarket import norm_code, rule_bear
    assert norm_code("aapl") == "AAPL" and norm_code(5930) == "005930"
    assert "차익 실현" in rule_bear({"change_pct": 29.9})


def test_llm_down_gives_data_debate_and_reasons(monkeypatch):
    from src.trader import llm as llm_mod
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    dead = llm_mod.LLM()
    assert not dead.available and "키 없음" in dead.status() and "키 없음" in dead.selftest()
    pool = [{"code": "000001", "name": "가", "price": 1, "change_pct": 12.0, "value_krw": 5e10},
            {"code": "000002", "name": "나", "price": 1, "change_pct": -4.0, "value_krw": 4e10}]
    r6, r7 = premarket.agent_debate(dead, "", pool)
    assert set(r6.data["items"]) == set(r7.data["items"]) == {"000001", "000002"}
    assert "데이터 기반" in r6.reason and "키 없음" in r6.reason
    news = [{"title": "실적 개선 기대", "date": ""}]
    assert intraday.news_check(dead, "샘플", news, [], [], False).decision == "pass"   # 모의: 키워드만 확인
    assert intraday.news_check(dead, "샘플", news, [], [], True).decision == "reject"  # 실계좌: 보수적


def test_llm_error_reason_and_quota_cooldown(monkeypatch):
    from src.trader import llm as llm_mod
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    m = llm_mod.LLM()
    tried = []
    def boom(p, model, *a):
        tried.append(model)
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
    m._call = boom
    assert m.json("s", "p") is None and "할당량" in m.status()
    assert len(tried) == len(m.gemini_models)            # 백업 모델까지 시도
    m.json("s", "p")
    assert len(tried) == len(m.gemini_models)            # 할당량 초과 모델은 잠시 건너뜀
    m._call = lambda *a: '{"ok": true}'
    m._cooldown.clear()
    assert m.json("s", "p") == {"ok": True} and m.status() == "LLM 정상"
