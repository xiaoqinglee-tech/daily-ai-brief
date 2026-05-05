"""GitHub 项目抓取器(尚未实现)。

计划:从 GitHub Search API 拉取过去 N 天 stars 增长快的 AI/Agent 相关 repo。
"""
from __future__ import annotations

import logging
from typing import List

from schema import Item

logger = logging.getLogger(__name__)


def fetch_github(
    query: str = "topic:llm OR topic:agent",
    days: int = 7,
    min_stars: int = 50,
) -> List[Item]:
    """从 GitHub 抓取最近创建的相关 repo。

    Args:
        query: GitHub Search 查询字符串。
        days: 只看过去多少天创建的 repo。
        min_stars: 最少 star 数(筛掉无人问津的)。

    Returns:
        Item 列表,按 star 数倒序。
    """
    raise NotImplementedError("GitHub fetcher 尚未实现")
