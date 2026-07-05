"""[섹션 4] 전일 주요 증시 이슈 수집 (네이버 금융 주요뉴스).

네이버 금융 '주요뉴스' 페이지에서 상위 기사 2~3개의 제목과 원문 링크를
가져온다. 제목이 곧 이슈 요약이므로 LLM 없이 그대로 링크로 제공한다.
"""
from __future__ import annotations

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
            issues.append(Issue(title=title, url=urljoin(_BASE, href)))
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
