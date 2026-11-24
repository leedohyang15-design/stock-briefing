"""네이버 증권(신규 stock.naver.com) JSON API 공용 헬퍼.

2026-11-23 부로 finance.naver.com 의 HTML 페이지(sise_quant, theme, frgn, mainnews 등)가
모두 클라이언트 렌더링 SPA(stock.naver.com)로 리다이렉트되어 기존 표 파싱이 0건이 됐다.
대신 모바일 사이트(m.stock.naver.com)가 쓰는 무료·무키 JSON API 를 호출한다.

  - 거래상위:     /api/stocks/quantTop/{KOSPI|KOSDAQ}?page=1&pageSize=N
  - 테마 목록:    /api/stocks/theme?page=1&pageSize=N        (등락률 내림차순)
  - 테마 상세:    /api/stocks/theme/{no}                      (쿼리 붙이면 타임아웃 — 붙이지 말 것)
  - 투자자 동향:  /api/stock/{code}/trend?pageSize=N          (일별 외국인·기관 순매매량)
  - 주요뉴스:     /api/news/list?category=mainnews&page=1&pageSize=N

API 가 간헐적으로 응답을 끊거나 지연하는 경우가 있어 짧은 백오프로 재시도한다.
테스트는 get_json 을 monkeypatch 해서 저장된 fixture 로 구동한다.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE = "https://m.stock.naver.com/api"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json",
}


def get_json(path: str, params: Optional[Dict[str, Any]] = None,
             timeout: float = 12, retries: int = 2) -> Optional[Any]:
    """BASE + path 를 GET 해서 JSON 반환. 실패 시 로그 남기고 None."""
    url = f"{BASE}{path}"
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(1.5 * attempt)  # 간헐적 connection reset 대비 짧은 백오프
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"[naver] 요청 실패({url} {params or ''}): {last_err}")
    return None


def num(text) -> Optional[float]:
    """'1,234' · '+1.20%' · '-56' → float. 부호(-)는 보존, +/%/콤마는 제거."""
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).replace(",", "").replace("%", "").replace("+", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_theme_list(data: Any) -> List[Tuple[str, str, float]]:
    """테마 목록 응답 → [(no, 테마명, 등락률%)] (등락률 내림차순 보장)."""
    out: List[Tuple[str, str, float]] = []
    groups = data.get("groups", []) if isinstance(data, dict) else []
    for g in groups or []:
        no, name, chg = g.get("no"), g.get("name"), num(g.get("changeRate"))
        if no is None or not name or chg is None:
            continue
        out.append((str(no), str(name).strip(), chg))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def fetch_theme_list(page_size: int = 40) -> List[Tuple[str, str, float]]:
    """등락률 상위 테마 목록."""
    data = get_json("/stocks/theme", {"page": 1, "pageSize": page_size})
    rows = parse_theme_list(data)
    if not rows:
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        print(f"[naver] 테마 목록 0건. 응답 keys={keys}")
    return rows


def fetch_theme_stocks(no: str) -> List[Dict[str, Any]]:
    """테마 구성종목 원본 dict 목록(최대 20, 등락률순). 쿼리 파라미터를 붙이면 API 가 응답하지 않는다."""
    data = get_json(f"/stocks/theme/{no}")
    stocks = data.get("stocks", []) if isinstance(data, dict) else []
    return [s for s in stocks or [] if isinstance(s, dict)]
