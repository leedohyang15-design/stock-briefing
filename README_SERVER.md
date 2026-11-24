# 서버에서 24시간 돌리기 (AWS Lightsail 서울)

PC를 꺼도 매일 자동으로 모의투자를 하고, 텔레그램 알림이 오고, 휴대폰으로 대시보드를 볼 수 있게 합니다.

> 💰 **무료로 하고 싶다면** → [README_ORACLE.md](README_ORACLE.md) (오라클 클라우드 Always Free). 서버만 다르고 4번부터는 이 문서와 같습니다.
처음 한 번만 30분 정도 걸립니다. 화면 메뉴 이름은 AWS 사정에 따라 조금 다를 수 있습니다.

---

## 1. AWS 가입
1. https://aws.amazon.com 에서 **AWS 계정 생성** (이메일, 카드 등록, 휴대폰 인증).
2. 가입이 끝나면 https://lightsail.aws.amazon.com 접속.

## 2. 서버(인스턴스) 만들기
1. **인스턴스 생성(Create instance)** 클릭.
2. **위치:** 서울 (`ap-northeast-2`). 다른 지역이면 "AWS 리전 변경"에서 서울 선택.
3. **플랫폼:** Linux/Unix → **블루프린트:** "OS 전용(OS Only)" → **Ubuntu 24.04 LTS**.
4. **플랜:** 가장 싼 **월 5달러 플랜(메모리 512MB)** 으로 충분합니다. 설치 스크립트가 메모리 부족에 대비해 스왑 2GB 를 자동으로 만듭니다 (설치만 몇 분 더 걸림). 여유를 원하면 1GB 플랜(월 약 7달러). 정확한 요금은 화면에서 확인.
5. 이름: `ai-trader` → **인스턴스 생성**. 1~2분 기다리면 "실행 중"이 됩니다.

## 3. 고정 IP와 방화벽
1. 인스턴스 클릭 → **네트워킹(Networking)** 탭.
2. **고정 IP 연결(Attach static IP)** → 새로 만들어 연결. (서버를 재시작해도 주소가 안 바뀝니다. 연결해 두면 무료)
3. 같은 탭의 **IPv4 방화벽** → **규칙 추가** → 애플리케이션 `사용자 지정`, 프로토콜 `TCP`, 포트 `8501` → 저장.
   (대시보드용. SSH 22번은 기본으로 열려 있음)

## 4. 설치 (명령 한 줄)
1. 인스턴스 화면에서 **SSH를 사용하여 연결(Connect using SSH)** → 브라우저에 검은 창이 열립니다.
2. 아래 한 줄을 복사해 검은 창에 붙여넣고 엔터 (붙여넣기: 마우스 오른쪽 클릭 또는 Ctrl+Shift+V).
```bash
curl -fsSL https://raw.githubusercontent.com/leedohyang15-design/stock-briefing/claude/tender-hawking-ibcnvo/deploy/setup_server.sh | bash
```
3. 3~5분 뒤 "설치가 끝났습니다" 와 **대시보드 주소·비밀번호**가 나옵니다. 비밀번호를 메모해 두세요.

## 5. 키 넣기 (.env)
1. PC에서 프로그램 폴더의 `.env` 를 메모장으로 열고 **전체 선택(Ctrl+A) → 복사(Ctrl+C)**.
2. 서버 검은 창에서:
```bash
nano ~/stock-briefing/.env
```
3. 파일 맨 끝의 `DASHBOARD_PASSWORD=...` 줄은 **남기고**, 나머지 내용을 지운 뒤 PC에서 복사한 내용을 붙여넣습니다.
   (붙여넣기가 안 되면 브라우저 SSH 창 오른쪽 아래 **클립보드** 아이콘에 먼저 붙여넣은 뒤 창에서 마우스 오른쪽 클릭)
4. 저장: **Ctrl+O → 엔터 → Ctrl+X**.

## 6. 연결 확인
```bash
cd ~/stock-briefing && .venv/bin/python -m src.trader.kis_client --check
```
```bash
cd ~/stock-briefing && .venv/bin/python -m src.trader.telegram_bot --test
```
둘 다 "모두 정상"·"✅ 테스트 메시지"가 나오면 끝입니다.
> 한국투자증권 API 신청 시 **접속 IP를 제한**해 두었다면 이 서버의 고정 IP를 KIS Developers 에 추가해야 합니다.

## 7. 휴대폰으로 대시보드 보기
- 주소: `http://<고정 IP>:8501` → 로그인 창에서 **아이디는 아무거나**, 비밀번호는 4번에서 메모한 것.
- 비밀번호를 잊었으면: `grep DASHBOARD_PASSWORD ~/stock-briefing/.env`
- 홈 화면에 추가해 두면 앱처럼 쓸 수 있습니다.

## 8. PC 자동실행 끄기 (중요)
PC와 서버가 동시에 돌면 텔레그램 알림이 두 번씩 옵니다. PC 프로그램 폴더의 `scripts\자동실행_해제.bat` 을 실행하세요.

---

## 자주 쓰는 명령

| 하고 싶은 것 | 명령 |
|---|---|
| 오늘 바로 시작 (평일 15:10 전) | `sudo systemctl start ai-trader.service` |
| 지금 돌고 있는지 | `systemctl status ai-trader --no-pager` |
| 실행 기록 실시간 보기 (끝: Ctrl+C) | `journalctl -u ai-trader -f` |
| 다음 실행 예정 시각 | `systemctl list-timers \| grep ai-trader` |
| 오늘 매매 중단 | 텔레그램 `/stop` (전량 청산은 `/flat`) |
| 코드 업데이트 (제가 고친 뒤) | `bash ~/stock-briefing/deploy/update.sh` |
| 한 달 뒤 분석용 DB 받기 | 브라우저에서 `http://<고정 IP>:8501/download/trader.db` |

## 자동으로 도는 것
- **평일 07:55** 모의투자 시작 → 15:40 일일 리포트 후 자동 종료 (휴장일은 바로 종료)
- **토요일 10:00** 주간 복기 → 텔레그램으로 변경안, `/apply` 또는 `/hold` 대기
- **대시보드**는 항상 켜져 있음 (서버가 재부팅돼도 자동 시작)
- 서버가 재부팅돼서 07:55 를 놓치면, 부팅 직후 바로 실행합니다.

## 비용·끄기
- 512MB 플랜 월 약 5달러 (1GB 는 약 7달러). 신규 가입 무료 혜택이 있을 수 있습니다 (화면에서 확인).
- Lightsail 은 **인스턴스를 '중지'해도 요금이 나갑니다.** 그만 쓰려면 인스턴스를 **삭제**하고, 고정 IP 도 **해제·삭제**하세요 (연결 안 된 고정 IP 는 요금이 붙습니다).

## 보안 참고
- 대시보드는 비밀번호로 막았지만 HTTP(암호화 없음) 연결입니다. 보이는 것은 모의투자 기록뿐이고, 키·계좌 비밀번호는 화면과 다운로드 어디에도 없습니다.
- 대시보드는 보기 전용입니다. 매매 조작은 텔레그램에서만 됩니다.
- 키가 든 `.env` 는 서버에서 본인만 읽을 수 있게(600) 설정됩니다. 서버 접속 키(SSH)는 AWS 계정으로만 열리니 AWS 계정에 2단계 인증을 켜 두세요.
