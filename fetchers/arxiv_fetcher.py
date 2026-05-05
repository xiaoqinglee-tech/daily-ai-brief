# fetchers/arxiv.py
"""从 arXiv 拉取最近论文。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List

import arxiv

from schema import Item

logger = logging.getLogger(__name__)


def fetch_arxiv(
    categories: List[str],
    days: int = 2,
    max_results: int = 100,
) -> List[Item]:
    """从 arXiv 拉取过去 N 天指定分类的论文。

    Args:
        categories: arXiv 分类列表,如 ["cs.AI", "cs.CL", "cs.LG"]。
            完整列表见 https://arxiv.org/category_taxonomy
        days: 拉取过去多少天(基于 submission date)。
        max_results: 单次最多返回条数(arXiv API 自身有上限,建议 <= 200)。

    Returns:
        Item 列表,按发布时间倒序。
    """
    # 构造查询: cat:cs.AI OR cat:cs.CL OR cat:cs.LG
    cat_query = " OR ".join(f"cat:{c}" for c in categories)
    
    logger.info("Fetching arXiv: categories=%s, days=%d, max=%d",
                categories, days, max_results)

    search = arxiv.Search(
        query=cat_query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items: List[Item] = []
    
    client = arxiv.Client(page_size=100, delay_seconds=5, num_retries=5)
    
    for result in client.results(search):
        # 按时间过滤:超过 cutoff 的就停(因为已按时间倒序排)
        if result.published < cutoff:
            break
        
        items.append(_to_item(result))
    
    logger.info("Fetched %d items from arXiv", len(items))
    return items


def _to_item(result: "arxiv.Result") -> Item:
    """把 arxiv.Result 转成统一的 Item。"""
    # arxiv ID 形如 "http://arxiv.org/abs/2310.12345v1",取最后的 short_id
    arxiv_id = result.get_short_id()  # e.g. "2310.12345v1"
    
    return Item(
        id=f"arxiv:{arxiv_id}",
        source="arxiv",
        title=result.title.strip().replace("\n", " "),
        url=result.entry_id,
        published_at=result.published,
        summary=result.summary.strip().replace("\n", " "),
        authors=[a.name for a in result.authors],
        tags=result.categories,
        extra={
            "pdf_url": result.pdf_url,
            "primary_category": result.primary_category,
            "comment": result.comment or "",
        },
    )


# ----------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    items = fetch_arxiv(
        categories=["cs.AI", "cs.CL", "cs.LG"],
        days=5,
        max_results=20,
    )
    
    print(f"\n=== Fetched {len(items)} items ===\n")
    for item in items[:5]:  # 只看前 5 条
        print(f"[{item.published_at.date()}] {item.title}")
        print(f"  authors: {', '.join(item.authors[:3])}{'...' if len(item.authors) > 3 else ''}")
        print(f"  tags: {item.tags}")
        print(f"  url: {item.url}")
        print(f"  summary: {item.summary[:150]}...")
        print()
