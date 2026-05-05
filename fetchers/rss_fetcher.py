"""RSS 博客源抓取器(尚未实现)。

计划:从配置的 RSS feed 列表抓取过去 N 天的新文章,转为 Item。
"""
from __future__ import annotations

import logging
from typing import List

from schema import Item

logger = logging.getLogger(__name__)


def fetch_rss(feed_urls: List[str], days: int = 2) -> List[Item]:
    """从一组 RSS feed 抓取过去 N 天的新文章。

    Args:
        feed_urls: RSS/Atom feed 的 URL 列表。
        days: 抓取过去多少天的文章。

    Returns:
        Item 列表,按发布时间倒序。
    """
    raise NotImplementedError("RSS fetcher 尚未实现")
