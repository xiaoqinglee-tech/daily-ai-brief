"""主入口:执行完整的简报生成流程。

流程:
1. fetch:从配置的源抓取最近论文,存入 db
2. filter:对未筛选的条目调用 LLM 判断是否相关
3. summarize:对通过筛选的条目生成总结
4. render:把今日条目渲染成 markdown 简报

每个步骤独立 try/except,失败的步骤记日志后继续,不中断整体流程。

Usage:
    python main.py              # 完整跑一次(默认)
    python main.py --skip-fetch # 跳过抓取,只重新筛选/总结/渲染
    python main.py --dry-run    # 只看会做什么,不实际执行(暂未实现)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from db import ItemDB
from fetchers import fetch_arxiv
from items_filter import filter_items
from llm import LLMClient
from renderer import render_today_brief
from summarizer import summarize_items
from config import (
    ARXIV_CATEGORIES,
    ARXIV_DAYS,
    ARXIV_MAX_RESULTS,
    FILTER_DAYS_WINDOW,
    BRIEF_DAYS_WINDOW,
    DB_PATH,
    LOG_DIR,
)


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 日志配置
# ----------------------------------------------------------------------
def setup_logging() -> None:
    """配置日志:终端 + 按日期分文件。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now():%Y-%m-%d}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    # 第三方库日志降级,减少噪音
    logging.getLogger("arxiv").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ----------------------------------------------------------------------
# 各步骤封装
# ----------------------------------------------------------------------
def step_fetch(db: ItemDB) -> int:
    """抓取数据,返回新增条数。"""
    logger.info("=" * 60)
    logger.info("Step: Fetch")
    logger.info("=" * 60)

    try:
        items = fetch_arxiv(
            categories=ARXIV_CATEGORIES,
            days=ARXIV_DAYS,
            max_results=ARXIV_MAX_RESULTS,
        )
    except Exception as e:
        logger.exception("arxiv fetch failed: %s", e)
        return 0

    new, exist = db.upsert_items(items)
    logger.info("Fetch result: %d new, %d existing", new, exist)
    return new


def step_filter(db: ItemDB, llm: LLMClient) -> tuple[int, int]:
    """筛选,返回 (通过条数, 拒绝条数)。"""
    logger.info("=" * 60)
    logger.info("Step: Filter")
    logger.info("=" * 60)

    try:
        return filter_items(db, llm, days=FILTER_DAYS_WINDOW)
    except Exception as e:
        logger.exception("filter failed: %s", e)
        return 0, 0


def step_summarize(db: ItemDB, llm: LLMClient) -> tuple[int, int]:
    """总结,返回 (成功条数, 失败条数)。"""
    logger.info("=" * 60)
    logger.info("Step: Summarize")
    logger.info("=" * 60)

    try:
        return summarize_items(db, llm)
    except Exception as e:
        logger.exception("summarize failed: %s", e)
        return 0, 0


def step_render(db: ItemDB) -> Path | None:
    """渲染,返回生成的文件路径(无内容时返回 None)。"""
    logger.info("=" * 60)
    logger.info("Step: Render")
    logger.info("=" * 60)

    try:
        return render_today_brief(db, days_window=BRIEF_DAYS_WINDOW)
    except Exception as e:
        logger.exception("render failed: %s", e)
        return None


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Daily AI Brief generator")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="跳过抓取阶段(用 db 里已有数据)",
    )
    args = parser.parse_args()

    setup_logging()

    logger.info("daily-ai-brief starting")

    db = ItemDB(db_path=DB_PATH)
    llm = LLMClient.from_env()

    new_count = 0
    try:
        if not args.skip_fetch:
            new_count = step_fetch(db)
        else:
            logger.info("Skipping fetch (--skip-fetch)")

        passed, rejected = step_filter(db, llm)
        success, failure = step_summarize(db, llm)
        brief_path = step_render(db)

        # 总结报告
        logger.info("=" * 60)
        logger.info("Pipeline complete")
        logger.info("=" * 60)
        logger.info("  Fetched:    %d new items", new_count)
        logger.info("  Filtered:   %d passed, %d rejected", passed, rejected)
        logger.info("  Summarized: %d ok, %d failed", success, failure)
        if brief_path:
            logger.info("  Brief:      %s", brief_path)
        else:
            logger.info("  Brief:      (no items)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
