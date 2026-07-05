"""윈도우 한글 사용자명 대응 SSL 부트스트랩.

yfinance 가 내부적으로 쓰는 curl_cffi(libcurl)는 CA 인증서 파일 경로에
한글(비 ASCII) 문자가 있으면 로딩에 실패한다(curl error 77).
윈도우 사용자명이 한글이면 certifi 인증서가 `C:\\Users\\한글\\...` 아래에 있어
모든 yfinance 요청이 실패하는 문제가 생긴다.

해결: certifi 인증서를 ASCII 경로로 복사하고, curl/requests 가 참조하는
환경변수(CURL_CA_BUNDLE 등)를 그 경로로 지정한다.

- ASCII 경로(리눅스/영문 윈도우, GitHub Actions 등)에서는 아무 것도 하지 않는다.
- import 시 1회 자동 실행된다.
"""
from __future__ import annotations

import os
import shutil


def _ascii_ca_dirs():
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    yield os.path.join(pd, "stock-briefing")
    yield r"C:\stock-briefing"


def ensure_ascii_ca_bundle() -> None:
    try:
        import certifi
    except Exception:  # noqa: BLE001
        return

    src = certifi.where()
    # 경로가 이미 ASCII 면(리눅스/영문 윈도우) 손댈 필요 없음.
    if src.isascii():
        return

    for dst_dir in _ascii_ca_dirs():
        dst = os.path.join(dst_dir, "cacert.pem")
        try:
            os.makedirs(dst_dir, exist_ok=True)
            # 이미 같은 크기로 복사돼 있으면 재복사 생략.
            if not (os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src)):
                shutil.copyfile(src, dst)
        except Exception:  # noqa: BLE001
            continue  # 다음 후보 경로 시도

        # curl_cffi(CURL_CA_BUNDLE) · requests(REQUESTS_CA_BUNDLE) · 표준 SSL(SSL_CERT_FILE)
        for var in ("CURL_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            os.environ.setdefault(var, dst)
        return


ensure_ascii_ca_bundle()
