#!/usr/bin/env bash
# AI 단타 트레이더 서버 설치 (Ubuntu 22.04/24.04 — 오라클 클라우드 무료 / AWS Lightsail)
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

# 무료 서버(오라클 AMD 1GB 등)는 메모리가 작아 pip 설치 중 멈출 수 있음 → 2GB 스왑
if [ "$NO_SYSTEMD" -eq 0 ]; then
  MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  if [ "$MEM_MB" -lt 2000 ] && [ -z "$(swapon --show 2>/dev/null)" ]; then
    echo "   메모리 ${MEM_MB}MB → 스왑 2GB 만드는 중"
    if $SUDO fallocate -l 2G /swapfile 2>/dev/null || $SUDO dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none; then
      $SUDO chmod 600 /swapfile && $SUDO mkswap /swapfile >/dev/null && $SUDO swapon /swapfile \
        && (grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | $SUDO tee -a /etc/fstab >/dev/null) \
        || echo "   (경고) 스왑을 켜지 못했습니다. 설치가 느리거나 멈추면 다시 실행하세요."
    fi
  fi
  # 오라클 Ubuntu 이미지는 서버 안 방화벽(iptables)이 기본으로 막음 → 대시보드 포트 8501 허용
  if command -v iptables >/dev/null && $SUDO iptables -S INPUT 2>/dev/null | grep -q -- '-j REJECT'; then
    if ! $SUDO iptables -C INPUT -p tcp --dport 8501 -j ACCEPT 2>/dev/null; then
      POS=$($SUDO iptables -L INPUT --line-numbers -n | awk '/REJECT/ {print $1; exit}')
      $SUDO iptables -I INPUT "${POS:-1}" -m state --state NEW -p tcp --dport 8501 -j ACCEPT
      echo "   서버 방화벽에서 8501 포트를 열었습니다."
    fi
    if command -v netfilter-persistent >/dev/null; then
      $SUDO netfilter-persistent save >/dev/null 2>&1 || true
    fi
  fi
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
IP="$(curl -s --max-time 3 https://checkip.amazonaws.com || curl -s --max-time 3 https://ifconfig.me || echo '<공인IP>')"
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
