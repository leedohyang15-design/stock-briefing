"""키 없이 대시보드를 미리 보는 데모 데이터 생성 (가짜 시세·가짜 시계, 실제 주문·네트워크 없음).

    python -m src.trader.demo
    python -m streamlit run src/trader/dashboard.py -- --demo
"""
from __future__ import annotations

from .agents import premarket
from .agents.review import weekly_report
from .broker import PaperBroker
from .journal import Journal
from .models import AgentResult, Bar
from .run_day import DayTrader
from .settings import DATA_DIR, Settings
from .simulator import FakeClock, FakeKIS, FakeLLM, minute_grid, trading_days
from .telegram_bot import NullTelegram

DEMO_DB = DATA_DIR / "demo.db"


def _path_semi(t):
    if t < "0935":
        return 10100 - (int(t[2:]) % 3) * 10
    m = int(t[:2]) * 60 + int(t[2:]) - 575
    return 10300 + m * 2 + (m * 37 % 7) * 5


def _path_def(t):
    return 10050 + (int(t[2:]) % 4) * 15 if t < "1001" else 10250 + (int(t[2:]) % 5) * 10


def _path_bio(t):
    return 10060 - (int(t[2:]) % 5) * 12


def _seed_history(j: Journal, days):
    """주간 복기 탭용 과거 분봉 (이른 돌파 성공 / 늦은 돌파 실패)."""
    for code, pat in (("111111", "win"), ("222222", "late"), ("333333", "late")):
        j.save_daily_bars(code, [Bar(d, 10000, 10300, 9700, 10000, 1_000_000, date=d) for d in trading_days(len(days) + 30)])
        for d in days:
            bars = []
            for t in minute_grid():
                m = int(t[:2]) * 60 + int(t[2:])
                if t < "0905":
                    o = 10000 + int(t[2:]) * 20
                    bars.append(Bar(t, o, o + 30, o - 10, o + 20, 50_000, date=d))
                    continue
                p = 10150 + (m - 545) * 2 if pat == "win" else (10050 if t < "1300" else 10200 - (m - 781) * 3)
                bars.append(Bar(t, p, p + 5, p - 5, p, 5_000, date=d))
            j.save_bars(code, bars)


def main(until: str = "1020") -> None:
    DEMO_DB.unlink(missing_ok=True)
    j = Journal(DEMO_DB)
    days = trading_days(40)[-12:]
    _seed_history(j, days)
    for i, d in enumerate(days[-5:]):
        r = [0.62, -0.91, 1.18, 0.31, 0.84][i]
        j.save_daily(d, 1_000_000, r * 10_000, 4, 2 + (r > 0), 2 - (r > 0), "paper")
    s = Settings.load()
    s.data["weekly"]["min_samples"] = 10
    weekly = weekly_report(j, s, FakeLLM(), panel=False)
    weekly["panel"] = [{"name": "버핏 관점", "view": "샘플반도체 중립 · 해자 확인 필요 (데모)"},
                       {"name": "린치 관점", "view": "샘플방산 사자 · 성장 대비 저평가 (데모)"}]
    j.snapshot("weekly", weekly)
    from .run_weekly import save_proposal
    save_proposal(j, weekly)

    clock = FakeClock("0750")
    kis = FakeKIS(clock, {"111111": ("샘플반도체", _path_semi), "222222": ("샘플방산", _path_def),
                          "333333": ("샘플바이오", _path_bio)})
    pool = [{"code": c, "name": n, "price": 10000, "change_pct": 2.0 - k, "value_krw": (5 - k) * 1e10}
            for k, (c, (n, _)) in enumerate(kis.paths.items())]
    inputs = premarket.PremarketInputs(
        indices=lambda: ["나스닥 (데모) +1.10%", "S&P 500 (데모) +0.64%", "원/달러 (데모) -0.31%"],
        headlines=lambda: ["(데모) 반도체 장비 수주 기사"], themes=lambda: ["AI 반도체 +3.8% (데모)", "방산 +2.9% (데모)"],
        pool=lambda: pool, notices=lambda c: [])
    llm = FakeLLM([
        {"score": 1, "summary": "나스닥 강세, 원화 강세 (데모)"},
        {"positive": ["반도체"], "negative": [], "summary": "반도체 장비 수혜 기대 (데모)"},
        {"items": [{"code": "111111", "text": "거래량 급증과 수주 기사 (데모)"}, {"code": "222222", "text": "수출 기대 (데모)"}]},
        {"items": [{"code": "111111", "text": "전일 급등으로 차익 매물 우려 (데모)"}, {"code": "222222", "text": "증자 우려 (데모)"}]},
        {"watchlist": [{"code": c, "note": "데모 관심종목"} for c in kis.paths], "exclude": [], "aggression": "normal",
         "summary": "반도체 중심 (데모)"},
    ])
    t = DayTrader(s, kis, PaperBroker(lambda c: kis.quote(c).price, 1_000_000), j, llm, NullTelegram(),
                  now_fn=clock.now, sleep_fn=clock.sleep, premarket_inputs=inputs)
    t.ex.poll = 0
    t._news = lambda ip: (AgentResult(12, "실시간 뉴스·공시", "reject", "공시 악재 키워드 '유상증자': (데모) 유상증자 결정")
                          if ip.code == "222222" else AgentResult(12, "실시간 뉴스·공시", "pass", "신규 악재 없음 (데모)"))
    t.start(1_000_000)
    t.wait_until("0800")
    t.premarket()
    t.wait_until("0905")
    clock.sleep(10)
    t.scan()
    while t.hhmm() < until:
        t.tick()
        clock.sleep(5)
    print(f"데모 데이터 생성 완료: {DEMO_DB}\n실행: python -m streamlit run src/trader/dashboard.py -- --demo")


if __name__ == "__main__":
    main()
