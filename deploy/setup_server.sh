#!/usr/bin/env bash
# AI 단타 트레이더 서버 설치 (Ubuntu 22.04/24.04, AWS Lightsail 서울 기준)
#   curl -fsSL https://raw.githubusercontent.com/leedohyang15-design/stock-briefing/claude/tender-hawking-ibcnvo/deploy/setup_server.sh | bash
# 다시 실행해도 안전합니다 (이미 있는 .env·비밀번호는 유지).
# 옵션: --no-systemd (서비스 등록 생략, 테스트용)
set -euo pipefail

REPO="https://github.com/leedohyang15-design/stock-briefing.git"
BRANCH="${TRADER_BRANCH:-claude/tender-hawking-ibcnvo}"
DIR="${TRADER_DIR:-$HOME/stock-briefing}"
NO_SYSTEMD=0
[ "${1:-}" = "--no-systemd" ] && NO_SYSTEMD=1
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "== 1/6 시간대·패키지 =="
if [ "$NO_SYSTEMD" -eq 0 ]; then
  $SUDO timedatectl set-timezone Asia/Seoul || true
fi
if ! command -v git >/dev/null || ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y -qq git python3-venv python3-pip >/dev/null
fi

echo "== 2/6 코드 받기 ($BRANCH) =="
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" pull -q --ff-only origin "$BRANCH"
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

echo "== 3/6 파이썬 환경 =="
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p data

echo "== 4/6 설정 파일(.env) =="
if [ ! -f .env ]; then
  cp .env.example .env
  NEW_ENV=1
else
  NEW_ENV=0
fi
if ! grep -q '^DASHBOARD_PASSWORD=.\+' .env; then
  PW="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(9))')"
  sed -i '/^DASHBOARD_PASSWORD=/d' .env
  printf '\n# 대시보드 비밀번호 (휴대폰 접속용)\nDASHBOARD_PASSWORD=%s\n' "$PW" >> .env
fi
chmod 600 .env

echo "== 5/6 자동 실행 등록 (systemd) =="
if [ "$NO_SYSTEMD" -eq 0 ]; then
  for f in deploy/systemd/*.service deploy/systemd/*.timer; do
    sed -e "s#__DIR__#$DIR#g" -e "s#__USER__#$(id -un)#g" "$f" | $SUDO tee "/etc/systemd/system/$(basename "$f")" >/dev/null
  done
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable -q --now ai-trader.timer ai-trader-weekly.timer ai-trader-web.service
  $SUDO systemctl restart ai-trader-web.service
else
  echo "(--no-systemd: 건너뜀)"
fi

echo "== 6/6 완료 =="
IP="$(curl -s --max-time 3 https://checkip.amazonaws.com || echo '<고정IP>')"
PW_NOW="$(grep '^DASHBOARD_PASSWORD=' .env | cut -d= -f2-)"
cat <<MSG

------------------------------------------------------------
설치가 끝났습니다.
$( [ "$NEW_ENV" -eq 1 ] && echo "▶ 먼저 키를 넣으세요:  nano $DIR/.env   (PC의 .env 내용을 붙여넣고 Ctrl+O, 엔터, Ctrl+X)" )
▶ 연결 확인:
    cd $DIR && .venv/bin/python -m src.trader.kis_client --check
    cd $DIR && .venv/bin/python -m src.trader.telegram_bot --test
▶ 대시보드(휴대폰):  http://$IP:8501
    비밀번호: $PW_NOW   (아이디 칸은 아무거나)
▶ 평일 07:55 모의투자, 토요일 10:00 주간 복기가 자동으로 돕니다.
▶ 오늘 바로 한 번 돌리기:  sudo systemctl start ai-trader.service
▶ 실행 기록 보기:          journalctl -u ai-trader -f
▶ 코드 업데이트:           bash $DIR/deploy/update.sh
------------------------------------------------------------
MSG
