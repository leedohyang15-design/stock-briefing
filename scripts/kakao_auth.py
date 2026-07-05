"""카카오 '나에게 보내기' 최초 인증 — refresh_token 발급 (딱 한 번만 실행).

사전 준비 (https://developers.kakao.com):
  1) 애플리케이션 추가 → '앱 키'의 REST API 키 복사
  2) [카카오 로그인] 활성화 ON
  3) [카카오 로그인] → Redirect URI 등록: https://localhost
     (다른 값을 쓰려면 .env 의 KAKAO_REDIRECT_URI 도 동일하게 맞출 것)
  4) [카카오 로그인] → 동의항목 → '카카오톡 메시지 전송(talk_message)' 을 사용 설정

실행:
  1) .env 에 KAKAO_REST_KEY 를 넣거나, 실행 중 직접 입력
  2) `python scripts/kakao_auth.py`
  3) 출력된 URL 을 브라우저에서 열고 → 카카오 로그인·동의
  4) 'localhost 에 연결할 수 없음' 페이지가 떠도 정상 —
     주소창의 URL 에서  ?code=XXXXX  부분의 code 값을 복사
  5) 터미널에 code 를 붙여넣기
  6) 출력된 KAKAO_REFRESH_TOKEN 값을 .env(로컬) 와 GitHub Secret 에 저장
"""
import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가 (src.config 사용)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from src.config import config  # noqa: E402

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"


def main() -> int:
    rest_key = config.kakao_rest_key or input("KAKAO_REST_KEY (REST API 키): ").strip()
    redirect_uri = config.kakao_redirect_uri
    if not rest_key:
        print("REST API 키가 필요합니다.")
        return 1

    authorize = (
        f"{AUTH_URL}?response_type=code&client_id={rest_key}"
        f"&redirect_uri={redirect_uri}&scope=talk_message"
    )
    print("\n[1] 아래 URL 을 브라우저에서 열고 카카오 로그인·동의를 진행하세요:\n")
    print(authorize)
    print(
        "\n[2] 동의 후 '{}' 로 이동됩니다 (연결 실패 페이지여도 OK).".format(redirect_uri)
    )
    print("    주소창 URL 의  ?code=XXXX  에서 code 값을 복사하세요.\n")

    code = input("[3] 복사한 code 를 붙여넣으세요: ").strip()
    if not code:
        print("code 가 없습니다.")
        return 1

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": rest_key,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"\n토큰 발급 실패({resp.status_code}): {resp.text}")
        print("→ code 는 1회용입니다. 만료됐다면 [1] URL 부터 다시 시도하세요.")
        return 1

    body = resp.json()
    refresh = body.get("refresh_token")
    access = body.get("access_token")
    print("\n✅ 발급 성공!\n")
    print("아래 값을 .env 와 GitHub Secret 에 저장하세요:")
    print("─" * 60)
    print(f"KAKAO_REST_KEY={rest_key}")
    print(f"KAKAO_REFRESH_TOKEN={refresh}")
    print("─" * 60)
    print(f"\n(참고) 이번 access_token(6시간 유효): {access}")
    print("이제 `python -m src.kakao` 로 나에게 보내기 테스트를 할 수 있습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
