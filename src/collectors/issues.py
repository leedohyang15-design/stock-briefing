"""[섹션 4] 전일 주요 증시 이슈 수집 (네이버 금융 주요뉴스).

네이버 금융 '주요뉴스' 페이지에서 상위 기사 2~3개의 제목과 원문 링크를
가져온다. 제목이 곧 이슈 요약이므로 LLM 없이 그대로 링크로 제공한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}
_BASE = "https://finance.naver.com"
_URL = f"{_BASE}/news/mainnews.naver"


@dataclass
class Issue:
    title: str
    url: str


def _article_url(href: str) -> str:
    """네이버 금융 뉴스 링크(PC용 news_read)를 모바일·PC 모두 열리는
    표준 기사 퍼머링크(n.news.naver.com/article/{언론사}/{기사})로 변환.

    변환 실패 시(형식이 다르면) 원래 링크를 절대경로로 반환.
    """
    aid = re.search(r"article_id=(\d+)", href) or re.search(r"/article/\d+/(\d+)", href)
    oid = re.search(r"office_id=(\d+)", href) or re.search(r"/article/(\d+)/", href)
    if aid and oid:
        return f"https://n.news.naver.com/article/{oid.group(1)}/{aid.group(1)}"
    return urljoin(_BASE, href)


def fetch_top_issues(limit: int = 3) -> List[Issue]:
    """전일 주요 증시 뉴스 상위 기사 제목 + 원문 링크."""
    issues: List[Issue] = []
    seen = set()
    try:
        resp = requests.get(_URL, headers=_HEADERS, timeout=10)
        resp.encoding = "euc-kr"
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.select(".articleSubject a, dd.articleSubject a"):
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or len(title) < 8 or title in seen:
                continue
            seen.add(title)
            issues.append(Issue(title=title, url=_article_url(href)))
            if len(issues) >= limit:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[issues] 주요뉴스 조회 실패: {e}")
    return issues


def to_plain_lines(issues: List[Issue]) -> List[str]:
    return [f"- {i.title} ({i.url})" for i in issues]


if __name__ == "__main__":
    for line in to_plain_lines(fetch_top_issues()):
        print(line)
