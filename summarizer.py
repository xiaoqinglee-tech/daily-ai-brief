"""总结模块:对通过筛选的 Item 生成结构化的中文总结。

策略:
- 逐条调用(总结质量优先,不批量)
- 失败留 NULL,下次跑会再处理(下次重试)
- prompt 限定字数 + max_tokens 双重控制长度
"""
from __future__ import annotations

import logging
from typing import Optional

from db import ItemDB
from llm import LLMClient
from schema import Item

logger = logging.getLogger(__name__)


SUMMARIZER_SYSTEM_PROMPT = """\
你是一个 AI 论文总结助手,服务于一位关注 LLM Agent 和 AI Infra 的工程师。

# 任务

给定一篇论文的标题和摘要,生成一段结构化的中文总结,**严格按以下三段式**:

【做了什么】用一句话说清楚论文要解决的问题和提出的方案(20-30字)
【怎么做】用一句话描述核心方法或技术路线(30-40字)
【适合谁看】用一句话说明哪类工程师/研究者会从中获益(20-30字)

# 要求

- 总字数控制在 100 字以内，宁可精简也不要凑字数
- 用平实的中文,不要堆砌术语
- 不要出现"本文"、"作者"等学术腔
- 不要分点列表、不要 markdown 标记
- 不输出任何额外说明,只输出三段式结果

# 示例

输入论文:
Title: Adaptive Speculative Decoding with Quantization-Aware Draft Selection
Abstract: We present a method that dynamically selects draft model size based on input characteristics, combined with INT8 quantization to reduce LLM inference latency...

正确输出:
【做了什么】提出自适应投机解码方案,降低 LLM 推理延迟。
【怎么做】根据输入动态选择 draft model 大小,结合 INT8 量化感知训练。
【适合谁看】做高吞吐 LLM 推理服务、需要降本提速的系统工程师。
"""

# 总结字数上限的 token buffer
MAX_SUMMARY_TOKENS = 300


def summarize_items(db: ItemDB, llm: LLMClient) -> tuple[int, int]:
    """对所有 filter_pass=1 但还没总结的条目生成总结。
    
    Returns:
        (成功条数, 失败条数)
    """
    items = db.get_unsummarized_items()
    if not items:
        logger.info("No items to summarize")
        return 0, 0
    
    logger.info("Summarizing %d items", len(items))
    
    success = 0
    failure = 0
    for item in items:
        summary = _summarize_one(llm, item)
        if summary:
            db.update_summary(item_id=item.id, summary=summary)
            success += 1
        else:
            failure += 1
            # 不写库,留 NULL,下次再试
    
    logger.info("Summarize done: %d ok, %d failed (will retry next run)",
                success, failure)
    return success, failure


def _summarize_one(llm: LLMClient, item: Item) -> Optional[str]:
    """对单条 item 调用 LLM 生成总结。失败返回 None。
    
    成功的判定:
    - LLM 返回非空字符串
    - 字数在合理范围(>20 且 <300)
    - 包含至少一个【】标记(三段式校验)
    """
    user_prompt = (
        f"Title: {item.title}\n\n"
        f"Abstract: {item.summary}"
    )
    
    try:
        text = llm.chat(
            messages=[
                {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=MAX_SUMMARY_TOKENS,
            thinking=False,  # 总结任务不需要长 thinking,实测可改 True 对比
        )
    except Exception as e:
        logger.warning("LLM call failed for %s: %s", item.id, e)
        return None
    
    text = text.strip()
    
    # 简单的输出校验
    if not text:
        logger.warning("Empty summary for %s", item.id)
        return None
    
    if len(text) < 20:
        logger.warning("Summary too short for %s (%d chars): %s",
                       item.id, len(text), text)
        return None
    
    if len(text) > 300:
        logger.warning("Summary too long for %s (%d chars), truncating",
                       item.id, len(text))
        text = text[:300]
    
    if "【" not in text:
        logger.warning("Summary missing structure marker for %s: %s",
                       item.id, text[:80])
        # 这个不算硬性失败,继续保存
    
    return text


# ----------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv(override=False)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    db = ItemDB(db_path="data/brief.db")
    llm = LLMClient.from_env()

    success, failure = summarize_items(db, llm)
    print(f"\nResult: {success} succeeded, {failure} failed")

    # 打印生成的总结
    if success > 0:
        print("\n=== Generated summaries ===")
        cursor = db.conn.cursor()
        cursor.execute('''
            SELECT id, title, llm_summary
            FROM items
            WHERE filter_pass = 1 AND llm_summary IS NOT NULL
            ORDER BY published_at DESC
            LIMIT 5
        ''')
        for row in cursor.fetchall():
            print(f"\n--- {row[0]} ---")
            print(f"Title: {row[1]}")
            print(f"Summary:\n{row[2]}")
    
    db.close()
