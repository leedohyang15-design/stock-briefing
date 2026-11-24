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
NEEDED = (["webview"] if sys.platform == "win32" else []) + ["numpy", "yfinance", "yaml", "dotenv", "bs4", "lxml", "holidays", "google.genai"]


def ensure_packages() -> None:
    missing = []
    for m in NEEDED:
        try:
            importlib.import_module(m)
        except ImportError:
            missing.append(m)
    if missing:
        print(f"[준비] 필요한 패키지 설치 중... ({', '.join(missing)}) 처음 한 번만 몇 분 걸립니다.")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
        except subprocess.CalledProcessError:
            # 전용 창(pywebview)만 실패한 경우엔 브라우저로 대신 열 수 있으니 계속 진행
            print("[준비] 일부 패키지 설치에 실패했습니다. 전용 창 대신 브라우저로 열 수 있습니다.")
            if [m for m in missing if m != "webview"]:
                raise


def start_dashboard(port: int = 8501):
    """대시보드 서버를 같은 프로세스의 스레드로 띄운다. (서버, 주소) 반환."""
    from .web.server import serve
    try:
        httpd = serve(port=port, block=False)
    except OSError:
        print(f"[대시보드] {port} 포트가 이미 사용 중입니다 (이미 켜져 있을 수 있음).")
        httpd = None
    return httpd, f"http://localhost:{port}"


def open_app_window(url: str) -> bool:
    """브라우저 대신 전용 프로그램 창으로 연다 (윈도우 기본 Edge WebView2 사용). 창을 닫을 때까지 기다린다.
    pywebview 가 없거나 실패하면 False (그때는 브라우저로 연다)."""
    try:
        import webview
    except Exception:  # noqa: BLE001
        return False
    try:
        webview.create_window("AI 단타 트레이딩 사무실", url, width=1440, height=920, min_size=(900, 600),
                              confirm_close=True, background_color="#1a1c2c")
        webview.start(localization={"global.quitConfirmation": "창을 닫으면 오늘 매매(모의투자)가 멈춥니다. 닫을까요?",
                                    "global.ok": "닫기", "global.cancel": "계속 실행"})
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[창] 전용 창을 열지 못해 브라우저로 엽니다: {e}")
        return False


def run_with_restart(fn, max_restarts: int = 3, wait_sec: float = 10.0, sleep=None) -> int:
    """예상치 못한 오류로 멈추면 최대 max_restarts 번 다시 시작 (보유 종목은 재시작 시 복원됨). 재시작 횟수 반환."""
    import time
    import traceback
    sleep = sleep or time.sleep
    restarts = 0
    while True:
        try:
            fn()
            return restarts
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            if restarts >= max_restarts:
                print(f"[트레이더] {max_restarts}번 다시 시작했지만 계속 오류가 납니다. 멈춥니다 (보유 종목은 증권사 앱에서 확인하세요).")
                raise
            restarts += 1
            print(f"[트레이더] 오류로 멈춤 → {wait_sec:.0f}초 뒤 다시 시작 ({restarts}/{max_restarts})")
            sleep(wait_sec)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI 단타 트레이더 원클릭 실행")
    ap.add_argument("--live", action="store_true", help="실계좌 (기본은 모의투자)")
    ap.add_argument("--yes", action="store_true", help="실계좌 확인 문구 생략 (작업 스케줄러용)")
    ap.add_argument("--paper-cash", type=float, default=100_000.0, help="모의투자 가상 예수금 (기본 10만원)")
    ap.add_argument("--no-dashboard", action="store_true")
    ap.add_argument("--browser", action="store_true", help="전용 창 대신 브라우저로 화면 열기")
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

    if args.live:
        print("=" * 60)
        print("⚠️ 손절은 이 프로그램 안에서만 동작합니다. PC가 꺼지거나 절전·인터넷 끊김이면 손절이 안 걸립니다.")
        print("   매수 체결 알림이 오면 증권사 앱에서 손절 예약(스탑로스)을 함께 걸어 두세요.")
        print("=" * 60)
    dash, url = (None, None) if args.no_dashboard else start_dashboard()
    mode = "실계좌" if args.live else f"모의투자 (가상 {args.paper_cash:,.0f}원, 실제 주문 없음)"
    print(f"[트레이더] {mode} 시작. 창을 닫으면 멈춥니다. 장 마감 후 15:40 리포트까지 켜 두세요.")

    def trader():
        try:
            run_with_restart(lambda: build(dry_run=not args.live, paper_cash=args.paper_cash).run(args.paper_cash))
        except Exception as e:  # noqa: BLE001
            print(f"[트레이더] 멈춤: {e}")

    try:
        if url and not args.browser:
            import threading
            th = threading.Thread(target=trader, daemon=True)
            th.start()
            if open_app_window(url):          # 전용 창: 닫을 때까지 여기서 대기
                print("창을 닫아서 트레이더를 멈췄습니다.")
                return 0
            webbrowser.open(url)              # 전용 창을 못 열면 브라우저로
            while th.is_alive():
                th.join(1.0)
        else:
            if url:
                webbrowser.open(url)
            trader()
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
