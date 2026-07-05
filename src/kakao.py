"""카카오톡 '나에게 보내기' (메모 API) 발송 — 무료.

동작:
  1) refresh_token 으로 access_token 을 갱신한다 (access_token 은 6시간마다 만료).
  2) 메모 API(기본 텍스트 템플릿)로 나에게 브리핑 요약을 보낸다.

카카오 텍스트 템플릿은 최대 200자 + 링크 버튼 1개만 지원하므로,
전문은 이메일로, 카톡은 '핵심 요약 + 전문 확인 링크'로 보낸다.

초기 세팅(REST 키·refresh_token 발급)은 scripts/kakao_auth.py 참고.
"""
from __future__ import annotations

from typing import Optional, Tuple

import requests

from .config import config

_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
_TEXT_LIMIT = 200  # 카카오 텍스트 템플릿 text 필드 최대 길이


def _refresh_access_token() -> Optional[str]:
    """refresh_token 으로 새 access_token 을 발급받는다.

    카카오가 새 refresh_token 을 함께 주면(만료 임박 시) 알림만 출력한다.
    (자동 저장 불가 — 사용자가 GitHub Secret 을 갱신해야 함. 보통 2개월마다.)
    """
    data = {
        "grant_type": "refresh_token",
        "client_id": config.kakao_rest_key,
        "refresh_token": config.kakao_refresh_token,
    }
    if config.kakao_client_secret:
        data["client_secret"] = config.kakao_client_secret
    resp = requests.post(_TOKEN_URL, data=data, timeout=15)
    if resp.status_code != 200:
        print(f"[kakao] access_token 갱신 실패({resp.status_code}): {resp.text}")
        return None
    body = resp.json()
    if body.get("refresh_token"):
        print(
            "[kakao] ⚠️ 새 refresh_token 이 발급되었습니다. 곧 만료될 수 있으니 "
            "아래 값으로 KAKAO_REFRESH_TOKEN 을 갱신하세요:\n"
            f"        {body['refresh_token']}"
        )
    return body.get("access_token")


def _send_memo(access_token: str, text: str, link_url: str, button_title: str,
               buttons: Optional[List[dict]] = None) -> bool:
    import json

    template = {
        "object_type": "text",
        "text": text[:_TEXT_LIMIT],
        "link": {"web_url": link_url, "mobile_web_url": link_url},
    }
    if buttons:
        # buttons: [{"title": "메일 보기", "url": "https://..."}, ...] (최대 2개)
        template["buttons"] = [
            {"title": b["title"],
             "link": {"web_url": b["url"], "mobile_web_url": b["url"]}}
            for b in buttons[:2]
        ]
    else:
        template["button_title"] = button_title
    resp = requests.post(
        _MEMO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"[kakao] 메모 전송 실패({resp.status_code}): {resp.text}")
        return False
    return True


def send_kakao_memo(text: str, link_url: str = "https://finance.naver.com",
                    button_title: str = "네이버 금융",
                    buttons: Optional[List[dict]] = None) -> bool:
    """나에게 브리핑 요약을 카카오톡으로 발송. 성공하면 True.

    buttons: [{"title": "메일 보기", "url": "https://..."}] 형태(최대 2개).
             지정하면 message 하단에 버튼으로 노출된다.
    키가 없거나 실패해도 예외를 던지지 않고 False 를 반환한다
    (이메일 발송을 막지 않기 위함).
    """
    if not config.kakao_enabled:
        print("[kakao] KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 미설정 — 카톡 발송 건너뜀.")
        return False
    try:
        token = _refresh_access_token()
        if not token:
            return False
        ok = _send_memo(token, text, link_url, button_title, buttons)
        if ok:
            print("[kakao] 나에게 보내기 발송 완료.")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"[kakao] 발송 중 오류 → 건너뜀: {e}")
        return False


if __name__ == "__main__":
    ok = send_kakao_memo(
        "📈 카카오 연동 테스트\n이 메시지가 보이면 '나에게 보내기'가 정상 동작하는 겁니다!",
        button_title="테스트",
    )
    print("결과:", "성공" if ok else "실패")
