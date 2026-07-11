# 📈 개인 투자자 맞춤형 데일리 주식 브리핑 자동화

개인(개미) 투자자가 **매일 아침 9시(KST)** 출근길에 1분 만에 시장을 파악할 수 있도록,
핵심 정보만 요약한 데일리 주식 브리핑을 **이메일로 자동 발송**하는 프로그램입니다.

- **실행 환경:** GitHub Actions (무료, 서버·PC 불필요)
- **발송 채널:** 이메일 (SMTP / Gmail) — 카카오톡 연동 코드도 있으나 **현재 비활성화** (푸시 알림 미표시로 확인이 어려움)
- **데이터:** 무료 소스만 사용 (yfinance, 네이버 금융 — 로그인·API 키 불필요)
- **요약:** Google Gemini (무료) 또는 Claude 중 선택. 키가 없어도 원본 데이터로 발송됩니다.

## 브리핑 4개 섹션

| 섹션 | 내용 | 데이터 소스 |
|------|------|-------------|
| 🌐 [1] 마켓 뷰 | 코스피·코스닥·다우·나스닥·S&P500·원/달러 + 💡관전 포인트 | yfinance |
| 🔥 [2] 주도 섹터 & 주목 종목 | 🌟기타 급등 테마(동적) + 고정 테마별 우량주 시세 + 💬흐름 요약 | 네이버 테마시세 + yfinance + `config/watchlist.yaml` |
| 📰 [3] 전일 주요 이슈 | 주요 뉴스 2~3개 (클릭 가능한 링크) | 네이버 금융 주요뉴스 |
| 🚨 [4] 오늘의 일정 & 리스크 | 경제지표 발표·만기일 등 주의 사항 | `config/macro_calendar.yaml` |

> **섹션 2 = 고정 테마 + 동적 슬롯 하이브리드**
> - **고정 테마 7개** (`config/watchlist.yaml`): AI·반도체 / 우주·방산 / 2차전지 / 바이오·제약 / 원자력·전력 / 자율주행·로봇 / 가상자산·핀테크 — 매일 그날 강한 섹터 순으로 정렬.
> - **🌟 기타 급등 테마 (동적)**: 네이버 테마시세에서 고정 테마에 없는 낯선 테마가 당일 **+5% 이상** 급등하면 자동으로 섹션 맨 위에 노출 (초전도체·맥신·K-푸드 등 단기 테마 포착). 임계치·제외 키워드는 `src/collectors/themes.py` 에서 조정.

---

## 프로젝트 구조

```
economic report/
├── .github/workflows/daily_briefing.yml   # 매일 09:00 KST 자동 실행
├── src/
│   ├── main.py            # 오케스트레이터 (수집→요약→포맷→발송)
│   ├── config.py          # 환경변수 로드
│   ├── holidays_kr.py     # 한국 증시 휴장일 판정
│   ├── collectors/        # 수집기 (indices, watchlist, issues, calendar)
│   ├── summarizer.py      # LLM 요약 + 폴백
│   ├── formatter.py       # 이메일 본문 조립 (4개 섹션)
│   └── sender.py          # SMTP 발송
├── config/watchlist.yaml        # 관심 테마·종목 (직접 관리)
├── config/macro_calendar.yaml   # 매크로 일정 (직접 관리)
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🚀 셋업 가이드 (단계별)

### 1단계 — 준비물 3가지

1. **Gmail 앱 비밀번호** (이메일 발송용)
   - Google 계정 → 보안 → **2단계 인증 활성화** → **앱 비밀번호** 생성
   - 16자리 비밀번호를 복사해 둡니다. (일반 로그인 비밀번호가 아닙니다!)
2. **LLM API 키** *(선택 — 없으면 요약 없이 원본 데이터로 발송)*
   - **[추천] Google Gemini (무료·신용카드 불필요):** https://aistudio.google.com/apikey
   - (선택) Claude (크레딧 필요): https://console.anthropic.com/settings/keys
   - 둘 다 설정되면 무료인 **Gemini를 우선** 사용합니다.
3. **GitHub 계정** (무료 자동 실행용)

### 2단계 — 로컬에서 먼저 테스트

```bash
# 1) 의존성 설치
pip install -r requirements.txt

# 2) 환경변수 파일 생성 후 값 채우기
cp .env.example .env
#   → .env 를 열어 SMTP_USER, SMTP_PASSWORD, MAIL_TO 등을 입력

# 3) 개별 데이터 수집기 스모크 테스트 (각각 데이터가 나오는지 확인)
python -m src.collectors.indices       # 지수·환율
python -m src.collectors.watchlist     # 주도 섹터·주목 종목 시세
python -m src.collectors.issues        # 주요 뉴스+링크
python -m src.collectors.calendar      # 오늘 일정
python -m src.holidays_kr              # 휴장일 판정

# 4) 엔드투엔드 실행 → 본인 이메일로 브리핑 1통 수신 확인
#    (오늘이 휴장일이어도 강제로 보내려면 --force)
python -m src.main --force
```

> **API 키 폴백 확인:** `.env` 에서 `ANTHROPIC_API_KEY` 를 비워두고 실행해도
> LLM 요약 없이 원본 수치로 브리핑이 정상 발송되어야 합니다.

### 3단계 — GitHub Actions 로 자동화

1. 이 폴더를 GitHub 저장소로 push 합니다. (`.env` 는 `.gitignore` 로 제외됨)
2. 저장소 → **Settings → Secrets and variables → Actions** 에서 값 등록:

   **Secrets** (민감 정보):
   | 이름 | 값 |
   |------|-----|
   | `GEMINI_API_KEY` | Gemini API 키 (무료, 없으면 생략 가능) |
   | `ANTHROPIC_API_KEY` | Claude API 키 (없으면 생략 가능) |
   | `SMTP_USER` | Gmail 주소 |
   | `SMTP_PASSWORD` | Gmail 앱 비밀번호 |
   | `MAIL_TO` | 받을 이메일 (쉼표로 여러 명) |
   | `KAKAO_REST_KEY` | 카카오 REST API 키 (카톡 알림 쓸 때만) |
   | `KAKAO_CLIENT_SECRET` | 카카오 Client Secret (Client Secret 을 켠 경우만) |
   | `KAKAO_REFRESH_TOKEN` | `kakao_auth.py` 로 발급한 값 (카톡 알림 쓸 때만) |

   **Variables** (비민감 설정, 선택 — 미설정 시 기본값 사용):
   | 이름 | 예시 값 |
   |------|--------|
   | `SMTP_HOST` | `smtp.gmail.com` |
   | `SMTP_PORT` | `587` |
   | `GEMINI_MODEL` | `gemini-2.5-flash` |
   | `MAIL_FROM_NAME` | `데일리 주식 브리핑` |
   | `KAKAO_REDIRECT_URI` | `https://localhost` (카톡 알림 쓸 때만) |

3. **Actions** 탭 → **Daily Stock Briefing** → **Run workflow** 로 수동 테스트
   (`force` 를 체크하면 휴장일에도 강제 발송 → 지금 바로 테스트 가능)
4. 이메일이 정상 수신되면 끝! 이후 매 평일 09:00 KST 에 자동 실행됩니다.

---

## 📱 카카오톡 '나에게 보내기' 알림 (현재 비활성화 · 참고용)

> ⚠️ **현재 비활성화 상태입니다.** 카톡 '나에게 보내기'는 푸시 알림이 뜨지 않아 확인이 어려워
> `src/main.py` 에서 발송을 꺼두었습니다. 다시 켜려면 `main.py` 의 발송 부분에서
> `kakao.send_kakao_memo(...)` 호출을 복구하세요. (아래는 재활성화 시 참고용 세팅 안내)


이메일과 **병행**해, 매일 아침 폰으로 **핵심 요약 + 전문 링크**를 카톡으로 받을 수 있습니다.
(카톡은 최대 200자·링크 1개만 지원 → 요약만. **상세 전문은 이메일**로 봅니다.)

> **본인에게만** 발송됩니다. 친구/타인 발송은 유료 알림톡(사업자 필요)이라 제외했습니다.

### 최초 세팅 (한 번만)

1. https://developers.kakao.com → **애플리케이션 추가**
2. **앱 키 → REST API 키** 복사
3. **[카카오 로그인] 활성화 ON**
4. **[카카오 로그인] → Redirect URI** 에 `https://localhost` 등록
   (다른 값을 쓰면 `.env` 의 `KAKAO_REDIRECT_URI` 도 동일하게 맞추세요)
5. **[카카오 로그인] → 동의항목** 에서 **'카카오톡 메시지 전송(talk_message)'** 사용 설정
6. `.env` 에 `KAKAO_REST_KEY` 를 넣고, 아래를 실행해 **refresh_token** 발급:

   ```bash
   python scripts/kakao_auth.py
   ```
   - 출력된 URL 을 브라우저에서 열고 → 카카오 로그인·동의
   - `localhost 연결 실패` 페이지가 떠도 정상 → 주소창 URL 의 `?code=XXXX` 에서 **code 복사**
   - 터미널에 붙여넣으면 → `KAKAO_REFRESH_TOKEN` 값이 출력됩니다
7. 출력된 `KAKAO_REST_KEY`, `KAKAO_REFRESH_TOKEN` 을 `.env`(로컬)와 GitHub Secret 에 저장
8. 테스트: `python -m src.kakao` → 카톡으로 테스트 메시지 수신 확인

### 토큰 관리 (알아둘 점)

- **access_token 은 6시간마다 만료** → 프로그램이 매 실행 시 refresh_token 으로 **자동 갱신**하므로 신경 쓸 필요 없습니다.
- **refresh_token 은 약 2개월 유효**하고, 갱신 때마다 연장되어 매일 실행하면 사실상 끊기지 않습니다.
  만약 새 refresh_token 이 발급되면 실행 로그에 안내가 출력되니, 그 값으로 `KAKAO_REFRESH_TOKEN` 을 갱신하세요.
- 카카오 키가 **없거나 실패해도 이메일 발송은 정상 진행**됩니다 (채널 간 독립).

---

## ⏰ 스케줄 & 휴장일 처리

### ✅ 권장: 외부 스케줄러로 정시 발송 (cron-job.org, 무료)

> **GitHub Actions 무료 cron 은 러너 부하 시 수십 분~수 시간(때론 반나절)까지 지연됩니다.**
> 시각을 당겨도 지연 폭이 크면 소용이 없습니다. **정확한 시각 발송을 원하면 아래 외부 트리거를 쓰세요.**
> cron-job.org 가 매 평일 정해진 시각에 GitHub 를 깨우고, 워크플로우는 `repository_dispatch:
> run-briefing` 를 받아 **지연 없이 즉시** 실행됩니다.

**1) GitHub 토큰(PAT) 발급** — cron-job.org 가 내 리포지토리를 깨울 열쇠
  - GitHub → 우측 상단 프로필 → **Settings** → 맨 아래 **Developer settings**
    → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
  - **Repository access**: *Only select repositories* → `stock-briefing` 선택
  - **Permissions** → *Repository permissions* → **Contents: Read and write** (이거 하나면 충분)
  - Expiration 은 *No expiration*(또는 1년) 권장. 생성된 `github_pat_...` 토큰을 복사해 둡니다.

**2) cron-job.org 에서 예약**
  - [cron-job.org](https://cron-job.org) 무료 가입 → **Create cronjob**
  - **URL**: `https://api.github.com/repos/leedohyang15-design/stock-briefing/dispatches`
  - **Request method**: `POST`
  - **Headers** (3줄 추가):
    - `Accept: application/vnd.github+json`
    - `Authorization: Bearer github_pat_...` ← 1)에서 복사한 토큰
    - `X-GitHub-Api-Version: 2022-11-28`
  - **Request body**: `{"event_type":"run-briefing"}`
  - **Schedule**: *Custom* → 시간대를 **Asia/Seoul** 로 두고 **월~금 07:00** 지정
    (요일 Mon–Fri, 시 7, 분 0). ※ cron-job.org 은 **KST 그대로** 입력하면 됩니다(UTC 환산 불필요).
  - 저장 후 **TEST RUN** 버튼으로 즉시 한 번 쏴서 메일이 오는지 확인하세요.
  - 응답이 `204 No Content` 면 정상입니다. `404` 면 URL·토큰 권한을, `401` 이면 토큰을 다시 확인하세요.

### (보조) GitHub 자체 cron

- 워크플로우엔 `cron: 5 22 * * 0-4` (월~금 07:05 KST 목표)도 그대로 남아 있어,
  외부 스케줄러를 안 쓰더라도 **지연은 있지만 언젠가는** 발송됩니다(백업용).
  정시 발송이 중요하면 위 외부 스케줄러를 주 방식으로 쓰세요.

### 휴장일

- **한국 공휴일 휴장일**은 `src/holidays_kr.py` 가 판정해 자동으로 발송을 건너뜁니다.
  임시 공휴일·대체휴일 등 일회성 휴장일이 생기면 `holidays_kr.py` 의
  `_KRX_EXTRA_DATES` 에 추가하세요.

---

## 🔧 유지보수 포인트

- **관심 테마·종목**은 `config/watchlist.yaml` 에서 직접 관리합니다. 종목/테마 추가·삭제,
  이모지 변경 모두 이 파일만 수정하면 됩니다. (ticker 형식: KOSPI=`6자리.KS`, KOSDAQ=`6자리.KQ`)
  섹션 2는 매일 이 테마들을 그날 등락률 강한 순으로 정렬해 보여줍니다.
- **매크로 일정**(CPI·FOMC 등)은 `config/macro_calendar.yaml` 에서 직접 관리합니다.
  무료·무키 정책상 안정적 자동 소스가 없어, 월초에 확정 일정을 확인해 갱신하는 방식입니다.
- **락업(보호예수) 해제**는 현재 자리표시(placeholder)로 비어 있습니다.
  안정적 소스 확보 시 `src/collectors/calendar.py` 의 `fetch_lockup_releases()` 만 교체하면 됩니다.
- 각 수집기·차트는 실패해도 나머지 섹션 발송을 막지 않습니다 (부분 실패 허용).

---

## ⚠️ 면책

본 프로그램이 생성하는 브리핑은 **정보 제공용**이며 특정 종목의 매수/매도를 권유하지 않습니다.
모든 투자 판단과 책임은 이용자 본인에게 있습니다.
