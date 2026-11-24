#!/usr/bin/env bash
# 코드 업데이트: 최신 코드 받기 → 패키지 갱신 → 대시보드 재시작 (매매 중이면 다음 실행부터 반영)
set -euo pipefail
DIR="${TRADER_DIR:-$HOME/stock-briefing}"
BRANCH="${TRADER_BRANCH:-claude/tender-hawking-ibcnvo}"
cd "$DIR"
git fetch -q origin "$BRANCH" && git checkout -q "$BRANCH" && git pull -q --ff-only origin "$BRANCH"
.venv/bin/pip install -q -r requirements.txt
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
for f in deploy/systemd/*.service deploy/systemd/*.timer; do
  sed -e "s#__DIR__#$DIR#g" -e "s#__USER__#$(id -un)#g" "$f" | $SUDO tee "/etc/systemd/system/$(basename "$f")" >/dev/null
done
$SUDO systemctl daemon-reload
$SUDO systemctl restart ai-trader-web.service
echo "업데이트 완료: $(git log --oneline -1)"
if systemctl is-active -q ai-trader.service; then
  echo "지금 매매가 돌고 있어서 트레이더는 내일부터 새 코드로 실행됩니다. (즉시 반영: sudo systemctl restart ai-trader.service)"
fi
