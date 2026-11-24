"""[섹션 4] 전일 주요 증시 이슈 수집 (네이버 증권 주요뉴스).

네이버 증권 '주요뉴스' JSON(m.stock.naver.com/api/news/list?category=mainnews)에서
상위 기사 2~3개의 제목과 원문 링크를 가져온다. 제목이 곧 이슈 요약이므로 LLM 없이
그대로 링크로 제공한다. (구 finance.naver.com/news/mainnews.naver 는 2026-11 부로
신규 SPA 로 리다이렉트되어 HTML 파싱 불가)
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, List
from urllib.parse import urljoin

from . import _naver

_BASE = "https://finance.naver.com"


@dataclass
class Issue:
    title: str
    url: str


def _article_url(href: str) -> str:
    """네이버 뉴스 링크를 모바일·PC 모두 열리는 표준 기사 퍼머링크
    (n.news.naver.com/article/{언론사}/{기사})로 변환.

    변환 실패 시(형식이 다르면) 원래 링크를 절대경로로 반환.
    """
    aid = re.search(r"article_id=(\d+)", href) or re.search(r"/article/\d+/(\d+)", href)
    oid = re.search(r"office_id=(\d+)", href) or re.search(r"/article/(\d+)/", href)
    if aid and oid:
        return f"https://n.news.naver.com/article/{oid.group(1)}/{aid.group(1)}"
    return urljoin(_BASE, href)


def _parse_mainnews(data: Any, limit: int) -> List[Issue]:
    """news/list 응답(기사 dict 리스트: tit·oid·aid …) → Issue 목록."""
    issues: List[Issue] = []
    seen = set()
    if isinstance(data, dict):  # 혹시 래핑돼 오는 경우 대비
        data = data.get("items") or data.get("list") or []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        title = html.unescape(str(item.get("tit") or item.get("title") or "")).strip()
        oid, aid = str(item.get("oid") or ""), str(item.get("aid") or "")
        if not title or len(title) < 8 or title in seen or not (oid and aid):
            continue
        seen.add(title)
        issues.append(Issue(title=title,
                            url=_article_url(f"/article/{oid}/{aid}")))
        if len(issues) >= limit:
            break
    return issues


def fetch_top_issues(limit: int = 3) -> List[Issue]:
    """전일 주요 증시 뉴스 상위 기사 제목 + 원문 링크."""
    data = _naver.get_json("/news/list",
                           {"category": "mainnews", "page": 1, "pageSize": 10})
    issues = _parse_mainnews(data, limit)
    if not issues:
        print(f"[issues] 주요뉴스 0건 (응답 타입={type(data).__name__})")
    return issues


def to_plain_lines(issues: List[Issue]) -> List[str]:
    return [f"- {i.title} ({i.url})" for i in issues]


if __name__ == "__main__":
    for line in to_plain_lines(fetch_top_issues()):
        print(line)
