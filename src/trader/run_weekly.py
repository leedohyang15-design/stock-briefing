"""토요일 주간 복기 → 다음 주 설정 변경안 → 사용자 승인(/apply) 시 config/trader.yaml 갱신.

    python -m src.trader.run_weekly                 # 리포트·변경안 생성, 텔레그램 전송 후 승인 대기(최대 36시간)
    python -m src.trader.run_weekly --no-listen     # 승인 대기 없이 종료
    python -m src.trader.run_weekly --apply 3       # 변경안 3번 적용 (텔레그램 대신 직접)
    python -m src.trader.run_weekly --rollback 2    # 설정을 버전 2로 되돌림
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Optional

from .agents.review import weekly_report
from .journal import Journal
from .llm import get_llm
from .models import now_kst
from .settings import Settings
from .telegram_bot import NullTelegram, Telegram


def save_proposal(j: Journal, rep: dict) -> Optional[int]:
    best = (rep.get("search") or {}).get("best")
    changes = dict(best["changes"]) if best else {}
    changes.update(rep.get("calibration") or {})
    if not changes:
        return None
    return j._exec("INSERT INTO proposals (ts,changes,report,status) VALUES (?,?,?,?)",
                   (now_kst().isoformat(timespec="seconds"), json.dumps(changes, ensure_ascii=False),
                    json.dumps(rep, ensure_ascii=False, default=str), "pending"))


def apply_proposal(j: Journal, s: Settings, pid: int) -> str:
    rows = j.query("SELECT * FROM proposals WHERE id=?", (pid,))
    if not rows:
        return f"변경안 {pid}번이 없습니다."
    p = rows[0]
    if p["status"] != "pending":
        return f"변경안 {pid}번은 이미 처리됨 ({p['status']})."
    changes = json.loads(p["changes"])
    j._exec("INSERT OR REPLACE INTO config_versions (version,ts,yaml,note,status) VALUES (?,?,?,?,?)",
            (s.version, now_kst().isoformat(timespec="seconds"), s.to_yaml(), "변경 전 백업", "archived"))
    new = s.with_params(changes)
    new.data["version"] = s.version + 1
    new.save()
    j._exec("INSERT OR REPLACE INTO config_versions (version,ts,yaml,note,status) VALUES (?,?,?,?,?)",
            (new.version, now_kst().isoformat(timespec="seconds"), new.to_yaml(), f"변경안 {pid}: {changes}", "active"))
    j._exec("UPDATE proposals SET status='applied' WHERE id=?", (pid,))
    return f"✅ 적용 완료: 설정 v{s.version} → v{new.version}\n{changes}\n월요일부터 새 설정으로 매매합니다."


def hold_proposal(j: Journal, pid: int) -> str:
    j._exec("UPDATE proposals SET status='held' WHERE id=? AND status='pending'", (pid,))
    return f"변경안 {pid}번을 보류했습니다. 설정은 그대로입니다."


def rollback(j: Journal, s: Settings, version: int) -> str:
    rows = j.query("SELECT yaml FROM config_versions WHERE version=?", (version,))
    if not rows:
        return f"버전 {version} 기록이 없습니다."
    import yaml
    data = yaml.safe_load(rows[0]["yaml"])
    data["version"] = s.version + 1
    Settings(data, s.path).save()
    return f"설정을 v{version} 내용으로 되돌렸습니다 (새 버전 v{data['version']})."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-listen", action="store_true")
    ap.add_argument("--no-panel", action="store_true", help="투자 대가 패널 생략")
    ap.add_argument("--apply", type=int)
    ap.add_argument("--hold", type=int)
    ap.add_argument("--rollback", type=int)
    ap.add_argument("--listen-hours", type=float, default=36.0)
    ap.add_argument("--market", choices=["kr", "us"], default="kr")
    args = ap.parse_args()
    from . import market as mk
    m = mk.activate(args.market)
    s, j = Settings.load(m.config_path), Journal(m.db_path)
    if args.apply:
        print(apply_proposal(j, s, args.apply))
        return
    if args.hold:
        print(hold_proposal(j, args.hold))
        return
    if args.rollback:
        print(rollback(j, s, args.rollback))
        return

    rep = weekly_report(j, s, get_llm(), panel=not args.no_panel)
    j.snapshot("weekly", rep)
    pid = save_proposal(j, rep)
    sec = s.secrets
    tg = Telegram(sec.telegram_token, sec.telegram_chat_id) if sec.has_telegram else NullTelegram()
    if m.tg_prefix:
        from .run_day import PrefixTelegram
        tg = PrefixTelegram(tg, m.tg_prefix)
    msg = rep["text"]
    if pid:
        prop = j.query("SELECT changes FROM proposals WHERE id=?", (pid,))[0]["changes"]
        msg += f"\n\n[변경안 {pid}번] {prop}\n적용: /apply {pid}   보류: /hold {pid}"
    else:
        msg += "\n\n이번 주 변경안 없음 (설정 유지)."
    tg.send(msg)
    print(msg)
    if not pid or args.no_listen or not sec.has_telegram:
        return
    done = {"v": False}

    def _apply(a):
        done["v"] = True
        return apply_proposal(j, Settings.load(m.config_path), int(a or pid))

    def _hold(a):
        done["v"] = True
        return hold_proposal(j, int(a or pid))

    tg.on("apply", _apply)
    tg.on("hold", _hold)
    tg.on("status", lambda a: f"변경안 {pid}번 승인 대기 중")
    tg.start()
    t0 = time.monotonic()
    while not done["v"] and time.monotonic() - t0 < args.listen_hours * 3600:
        time.sleep(5)
    time.sleep(3)
    tg.stop()


if __name__ == "__main__":
    main()
