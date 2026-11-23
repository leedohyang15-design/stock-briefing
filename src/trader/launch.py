"""원클릭 실행: 필요한 패키지 확인 → 대시보드(브라우저 자동 열림) + 트레이더를 한 번에.

    python -m src.trader.launch                  # 모의투자 (가상 10만원, 실제 주문 없음)
    python -m src.trader.launch --paper-cash 300000
    python -m src.trader.launch --live           # 실계좌 (확인 문구 입력 필요)
    python -m src.trader.launch --live --yes     # 실계좌, 작업 스케줄러용 (확인 생략)

창을 닫거나 Ctrl+C 를 누르면 대시보드도 같이 꺼진다.
"""
from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEEDED = ["numpy", "yfinance", "yaml", "dotenv", "bs4", "lxml", "holidays", "google.genai"]


def ensure_packages() -> None:
    missing = []
    for m in NEEDED:
        try:
            importlib.import_module(m)
        except ImportError:
            missing.append(m)
    if missing:
        print(f"[준비] 필요한 패키지 설치 중... ({', '.join(missing)}) 처음 한 번만 몇 분 걸립니다.")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])


def start_dashboard(port: int = 8501):
    """대시보드 서버를 같은 프로세스의 스레드로 띄우고 브라우저를 연다 (트레이더를 끄면 같이 꺼짐)."""
    from .web.server import serve
    try:
        httpd = serve(port=port, block=False)
    except OSError:
        print(f"[대시보드] {port} 포트가 이미 사용 중입니다 (이미 켜져 있을 수 있음). 브라우저만 엽니다.")
        httpd = None
    url = f"http://localhost:{port}"
    webbrowser.open(url)
    print(f"[대시보드] {url}")
    return httpd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI 단타 트레이더 원클릭 실행")
    ap.add_argument("--live", action="store_true", help="실계좌 (기본은 모의투자)")
    ap.add_argument("--yes", action="store_true", help="실계좌 확인 문구 생략 (작업 스케줄러용)")
    ap.add_argument("--paper-cash", type=float, default=100_000.0, help="모의투자 가상 예수금 (기본 10만원)")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--force", action="store_true", help="휴장일에도 실행 (연결 확인용)")
    args = ap.parse_args(argv)

    (ROOT / "data").mkdir(exist_ok=True)
    ensure_packages()

    from ..holidays_kr import is_market_holiday
    from .models import now_kst
    from .run_day import build

    if is_market_holiday(now_kst().date()) and not args.force:
        print("오늘은 휴장일입니다. 창을 닫으셔도 됩니다.")
        if not args.yes:
            input("엔터를 누르면 종료합니다...")
        return 0
    if args.live and not args.yes:
        print("⚠️ 실계좌 모드입니다. 실제 돈으로 주문이 나갑니다 (매수는 텔레그램 승인 후).")
        if input("계속하려면 '실계좌' 라고 입력하세요: ").strip() != "실계좌":
            print("취소했습니다.")
            return 1

    dash = None if args.no_dashboard else start_dashboard()
    mode = "실계좌" if args.live else f"모의투자 (가상 {args.paper_cash:,.0f}원, 실제 주문 없음)"
    print(f"[트레이더] {mode} 시작. 이 창을 닫으면 멈춥니다. 장 마감 후 15:40 리포트까지 켜 두세요.")
    try:
        build(dry_run=not args.live, paper_cash=args.paper_cash).run(args.paper_cash)
    except KeyboardInterrupt:
        print("\n사용자가 중지했습니다.")
    finally:
        if dash:
            dash.shutdown()
    print("오늘 일정이 끝났습니다.")
    if not args.yes:
        input("엔터를 누르면 창이 닫힙니다...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
