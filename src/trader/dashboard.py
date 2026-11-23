"""한 화면 대시보드 (보기 전용). 매매 조작은 텔레그램에서만.

    python -m streamlit run src/trader/dashboard.py
    → http://localhost:8501 (같은 와이파이 휴대폰: http://<PC IP>:8501)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from src.trader.agents import NAMES  # noqa: E402
from src.trader.journal import Journal  # noqa: E402
from src.trader.models import now_kst  # noqa: E402

UP, DOWN, MUTED = "#FF7B72", "#3D8BFF", "#9DA7B3"

st.set_page_config(page_title="AI 단타 트레이딩", layout="wide")
st.markdown("""
<style>
.block-container{padding-top:3.5rem;max-width:1440px}
.card{background:#161B22;border:1px solid #30363D;border-radius:12px;padding:14px 16px;margin-bottom:10px}
.lbl{font-size:12px;color:#9DA7B3}.big{font-size:34px;font-weight:700;font-family:monospace}
.mid{font-size:20px;font-weight:700;font-family:monospace}
.chip{font-size:12px;padding:2px 8px;border-radius:999px;white-space:nowrap}
.pass{background:#12261A;color:#56D364}.reject{background:#2D1517;color:#FF7B72}.wait{background:#21262D;color:#9DA7B3}
.agent{background:#0D1117;border:1px solid #21262D;border-radius:8px;padding:8px 10px;margin-bottom:8px;min-height:72px}
</style>""", unsafe_allow_html=True)


DEMO = "--demo" in sys.argv


@st.cache_resource
def journal() -> Journal:
    if DEMO:
        from src.trader.demo import DEMO_DB
        return Journal(DEMO_DB)
    return Journal()


def color(v) -> str:
    return UP if (v or 0) > 0 else (DOWN if (v or 0) < 0 else MUTED)


def chip(decision: str) -> str:
    label = {"pass": "통과", "reject": "거부", "wait": "대기", "info": "참고"}.get(decision, decision)
    cls = "pass" if decision == "pass" else ("reject" if decision == "reject" else "wait")
    return f'<span class="chip {cls}">{label}</span>'


def today_tab(j: Journal) -> None:
    today = now_kst().strftime("%Y%m%d")
    s = j.get_snapshot("status", {}) or {}
    pre = j.get_snapshot("premarket", {}) or {}
    inplay = j.get_snapshot("inplay", []) or []
    if not s:
        st.info("아직 오늘 데이터가 없습니다. `python -m src.trader.run_day --dry-run` 을 실행하세요.")
    mode = "드라이런(가상 주문)" if s.get("mode") == "paper" else "실계좌"
    state = f"중단 · {s.get('stop_reason')}" if s.get("stopped") else "운영 중"
    st.caption(f"{mode} · {state} · 갱신 {str(s.get('ts', ''))[11:19]} · 공격성 {s.get('aggression', '-')}")

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    ret, pnl = s.get("ret_pct", 0.0), s.get("pnl", 0.0)
    c1.markdown(f'<div class="card"><div class="lbl">일 수익률 (수수료·세금 차감)</div>'
                f'<div class="big" style="color:{color(ret)}">{ret:+.2f}%</div>'
                f'<div class="mid" style="color:{color(pnl)}">{pnl:+,.0f}원</div>'
                f'<div class="lbl">시작 평가금 {s.get("start_equity", 0):,.0f}원 · 실현 {s.get("realized", 0):+,.0f} · '
                f'미실현 {s.get("unrealized", 0):+,.0f}</div></div>', unsafe_allow_html=True)
    room, lim = s.get("loss_room", 0.0), s.get("loss_limit_amt", 1.0) or 1.0
    used = max(0.0, min(100.0, (1 - room / lim) * 100)) if lim else 0
    c2.markdown(f'<div class="card"><div class="lbl">일 손실 한도까지</div><div class="mid">{room:,.0f}원 남음</div>'
                f'<div style="height:8px;background:#21262D;border-radius:4px;margin-top:8px">'
                f'<div style="width:{used:.0f}%;height:8px;background:#F2CC60;border-radius:4px"></div></div>'
                f'<div class="lbl">한도 -{lim:,.0f}원 도달 시 자동 중단</div></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="card"><div class="lbl">오늘 거래</div><div class="mid">{s.get("wins", 0)}승 {s.get("losses", 0)}패</div>'
                f'<div class="lbl">매수 {s.get("entries", 0)}/{s.get("max_entries", 0)}회 · 보유 {len(s.get("positions", []))}/'
                f'{s.get("max_positions", 0)}</div></div>', unsafe_allow_html=True)
    rg = s.get("regime") or {}
    c4.markdown(f'<div class="card"><div class="lbl">시장 분위기 (13)</div>'
                f'<div class="mid" style="color:{UP if rg.get("decision") == "pass" else DOWN}">'
                f'{"진입 허용" if rg.get("decision") == "pass" else ("진입 중단" if rg else "-")}</div>'
                f'<div class="lbl">{rg.get("reason", "")}</div></div>', unsafe_allow_html=True)

    left, right = st.columns([1, 2.2])
    with left:
        st.markdown("#### 오늘의 증시")
        idx = s.get("index") or {}
        rows = [("코스피 (실시간)", idx.get("KOSPI")), ("코스닥 (실시간)", idx.get("KOSDAQ"))]
        html = "".join(f'<div style="display:flex;justify-content:space-between;border-bottom:1px solid #21262D;padding:4px 0">'
                       f'<span>{n}</span><span style="color:{color(v)}">{(v or 0):+.2f}%</span></div>' for n, v in rows)
        html += "".join(f'<div style="font-size:13px;border-bottom:1px solid #21262D;padding:4px 0">{ln}</div>'
                        for ln in pre.get("market_lines", [])[:9])
        st.markdown(f'<div class="card">{html}</div>', unsafe_allow_html=True)
        st.markdown("**주도 테마**")
        st.markdown('<div class="card">' + "<br>".join(pre.get("themes", [])[:5] or ["-"]) + "</div>", unsafe_allow_html=True)
        st.markdown("**전일 거래대금 상위**")
        st.markdown('<div class="card">' + "<br>".join(
            f"{p['name']} · {p['value_krw'] / 1e8:,.0f}억 · {p['change_pct']:+.1f}%" for p in pre.get("pool", [])[:6]) + "</div>",
            unsafe_allow_html=True)

    codes = [i["code"] for i in inplay]
    names = {i["code"]: i["name"] for i in inplay}
    for p in s.get("positions", []):
        if p["code"] not in names:
            codes.append(p["code"])
            names[p["code"]] = p["name"]
    with right:
        st.markdown("#### 매매 화면 · 1분봉")
        if not codes:
            st.info("Stocks in Play 가 정해지면(09:05 이후) 차트가 나타납니다.")
            sel = None
        else:
            sel = st.radio("관심종목", codes, format_func=lambda c: names.get(c, c), horizontal=True, label_visibility="collapsed")
            ip = next((i for i in inplay if i["code"] == sel), {})
            bars = j.bars(sel, today)
            fig = go.Figure()
            if bars:
                xs = [f"{b.time[:2]}:{b.time[2:]}" for b in bars]
                fig.add_trace(go.Candlestick(x=xs, open=[b.open for b in bars], high=[b.high for b in bars],
                                             low=[b.low for b in bars], close=[b.close for b in bars],
                                             increasing_line_color=UP, decreasing_line_color=DOWN, name="1분봉"))
                fig.add_trace(go.Bar(x=xs, y=[b.volume for b in bars], yaxis="y2", marker_color="rgba(157,167,179,0.35)", name="거래량"))
                if ip:
                    fig.add_hline(y=ip["or_high"], line_dash="dash", line_color="#79B8FF", annotation_text="시가범위 상단")
                    fig.add_hline(y=ip["or_low"], line_dash="dot", line_color="#79B8FF", annotation_text="시가범위 하단")
                    fig.add_hline(y=ip["vi_upper"], line_dash="dot", line_color="#F2CC60", annotation_text="정적 VI")
                for p in s.get("positions", []):
                    if p["code"] == sel:
                        fig.add_hline(y=p["stop"], line_dash="dash", line_color=DOWN, annotation_text=f"손절 {p['stop']:,.0f}")
                        fig.add_hline(y=p["avg_price"], line_color="#F2CC60", annotation_text=f"매수 {p['avg_price']:,.0f}")
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), template="plotly_dark",
                              paper_bgcolor="#0D1117", plot_bgcolor="#0D1117", xaxis_rangeslider_visible=False,
                              yaxis2=dict(overlaying="y", side="right", showgrid=False, range=[0, max([b.volume for b in bars] or [1]) * 4]),
                              showlegend=False)
            st.plotly_chart(fig, width="stretch")
            if ip:
                st.caption(f"현재가 {ip.get('price') or 0:,.0f} ({(ip.get('change_pct') or 0):+.2f}%) · 상대거래량 {ip['relvol']:.1f}배 · "
                           f"ATR {ip['atr']:,.0f} · 상태 {ip['status']} {ip.get('note', '')}")

    if sel:
        st.markdown(f"#### 에이전트 의견 · {names.get(sel, sel)}")
        pre_res = {r["no"]: r for r in pre.get("results", [])}
        rows = j.query("SELECT * FROM agent_results WHERE date=? AND code=? ORDER BY id", (today, sel))
        latest = {}
        for r in rows:
            latest[r["no"]] = r
        groups = [("A. 장전 분석팀 · LLM", [1, 2, 3, 4, 5, 8]), ("B. 장중 실행팀", [9, 10, 11, 12, 13, 14, 18, 15, 16]),
                  ("C. 복기", [17])]
        bull = (pre.get("bull") or {}).get(sel, "")
        bear = (pre.get("bear") or {}).get(sel, "")
        for title, nos in groups:
            st.markdown(f"**{title}**")
            cols = st.columns(3)
            for k, no in enumerate(nos):
                r = latest.get(no) or pre_res.get(no)
                dec = r["decision"] if r else "wait"
                reason = r["reason"] if r else "아직 실행 전"
                cols[k % 3].markdown(f'<div class="agent"><div style="display:flex;justify-content:space-between">'
                                     f'<b>{no} {NAMES[no]}</b>{chip(dec)}</div><div style="font-size:12px">{reason}</div></div>',
                                     unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        b1.markdown(f'<div class="card" style="border-color:#4B2226"><div class="lbl">6 강세론자</div>{bull or "-"}</div>', unsafe_allow_html=True)
        b2.markdown(f'<div class="card" style="border-color:#1F3A60"><div class="lbl">7 약세론자</div>{bear or "-"}</div>', unsafe_allow_html=True)

        sig = j.query("SELECT * FROM signals WHERE date=? AND code=? ORDER BY id DESC LIMIT 1", (today, sel))
        st.markdown("#### 최종 판단")
        if sig:
            g = sig[0]
            label = {"pending": "승인 대기", "filled": "매수 · 체결 완료", "rejected": "거부 · 매수 안 함",
                     "expired": "취소", "unfilled": "미체결", "checking": "검사 중"}.get(g["status"], g["status"])
            tm = latest.get(18)
            tmd = json.loads(tm["data"]) if tm and tm.get("data") else {}
            tm_html = ""
            if tmd.get("p_stop") is not None:
                tm_html = (f'<div style="display:flex;height:20px;border-radius:6px;overflow:hidden;font-size:11px;margin-top:6px">'
                           f'<div style="width:{tmd["p_eod_profit"]}%;background:{UP}">마감수익 {tmd["p_eod_profit"]:.0f}%</div>'
                           f'<div style="width:{tmd["p_stop"]}%;background:{DOWN}">손절 {tmd["p_stop"]:.0f}%</div>'
                           f'<div style="flex:1;background:#30363D">마감손실 {tmd["p_eod_loss"]:.0f}%</div></div>'
                           f'<div class="lbl">18 타임머신 기대수익 {tmd["ev_pct"]:+.2f}% (비용 차감)</div>')
            st.markdown(f'<div class="card"><div class="mid">{label}</div><div>{g["reason"]}</div>'
                        f'<div class="lbl">{g["ts"][11:19]} 신호 · 가격 {g["price"]:,.0f} · 손절 {g["stop"]:,.0f} · 수량 {g["qty"] or 0}</div>'
                        f'{tm_html}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="card">대기 · 아직 신호 없음 (시가범위 돌파 시 에이전트들이 순서대로 검사)</div>', unsafe_allow_html=True)

    st.markdown("#### 타임라인 · 매매일지")
    ev = j.query("SELECT ts, kind, text FROM events WHERE date=? ORDER BY id DESC LIMIT 40", (today,))
    st.markdown('<div class="card">' + "".join(
        f'<div style="border-bottom:1px solid #21262D;padding:4px 0;font-size:13px"><span style="color:#8B949E;font-family:monospace">'
        f'{e["ts"][11:19]}</span> <b>{e["kind"]}</b> {e["text"]}</div>' for e in ev) + "</div>", unsafe_allow_html=True)


def week_tab(j: Journal) -> None:
    rep = j.get_snapshot("weekly", {}) or {}
    days = j.query("SELECT * FROM daily ORDER BY date DESC LIMIT 5")[::-1]
    m = rep.get("metrics", {})
    c = st.columns(4)
    c[0].metric("주간 누적 수익률", f"{m.get('cum_ret_pct', 0):+.2f}%")
    c[1].metric(f"승률 ({m.get('trades', 0)}건)", f"{m.get('win_rate', 0):.0f}%" if m.get("trades") else "-")
    c[2].metric("평균 손익비", f"{m['payoff']:.2f}" if m.get("payoff") else "-")
    c[3].metric("최대 손실일", f"{m.get('worst_day', 0):+.2f}%")
    if days:
        fig = go.Figure(go.Bar(x=[d["date"][4:] for d in days], y=[d["ret_pct"] for d in days],
                               marker_color=[color(d["ret_pct"]) for d in days], text=[f"{d['ret_pct']:+.2f}%" for d in days]))
        fig.update_layout(height=260, template="plotly_dark", paper_bgcolor="#0D1117", plot_bgcolor="#0D1117",
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    st.markdown("#### 손실 거래 원인 분석 → 수정 → 재시험")
    st.markdown('<div class="card">' + "<br>".join(rep.get("log", ["토요일 run_weekly 실행 후 표시됩니다."])) + "</div>",
                unsafe_allow_html=True)
    st.markdown("#### 에이전트 성적표")
    sc = rep.get("scorecard", [])
    if sc:
        st.dataframe([{"에이전트": r["name"], "거부": r["rejects"], "채점": r["scored"],
                       "거부가 옳았던 비율": f"{r['right_rate']:.0f}%" if r.get("right_rate") is not None else "-",
                       "피한 손실(합, %)": round(r["avoided_pct"], 2)} for r in sc], width="stretch")
    else:
        st.caption("이번 주 거부된 신호 없음")
    st.markdown("#### 다음 주 설정 변경안")
    props = j.query("SELECT * FROM proposals ORDER BY id DESC LIMIT 3")
    for p in props:
        st.markdown(f'<div class="card"><b>변경안 {p["id"]}번</b> · {p["status"]} · {p["ts"][:10]}<br>'
                    f'<code>{p["changes"]}</code><div class="lbl">텔레그램 /apply {p["id"]} 또는 /hold {p["id"]}</div></div>',
                    unsafe_allow_html=True)
    if not props:
        st.caption("변경안 없음 (과최적화 방지 규칙: 표본 30건 이상, 과거·최근 구간 모두 개선될 때만 제안)")
    if rep.get("panel"):
        st.markdown("#### 투자 대가 패널 (참고용 · 단타 판단에 쓰지 않음)")
        st.markdown('<div class="card">' + "<br>".join(f"{x.get('name')}: {x.get('view')}" for x in rep["panel"]) + "</div>",
                    unsafe_allow_html=True)


j = journal()
st.markdown("### AI 단타 트레이딩 · 에이전트 18개" + (" · 데모 데이터" if DEMO else ""))
tab1, tab2 = st.tabs(["오늘", "주간 복기"])
with tab1:
    if hasattr(st, "fragment"):
        st.fragment(run_every=5)(today_tab)(j)
    else:
        today_tab(j)
with tab2:
    week_tab(j)
