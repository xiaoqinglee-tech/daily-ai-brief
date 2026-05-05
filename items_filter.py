# filter.py
"""筛选模块:用 LLM 判断 Item 是否值得放进简报。"""
from __future__ import annotations

import json
import logging
from typing import List, Tuple

from db import ItemDB
from llm import LLMClient
from schema import Item
from config import FILTER_BATCH_SIZE

logger = logging.getLogger(__name__)


# 筛选用的 system prompt
INTEREST_PROMPT = """\
你是一个论文筛选助手,帮用户从大量 arXiv 论文中找出值得阅读的。

# 用户兴趣画像

## 核心关注(高优先级,务必通过)
- LLM Agent:架构设计、规划、工具调用、多智能体协作、Agent 评测
- AI Infra:推理优化(vLLM、SGLang、TensorRT-LLM 等)、KV cache、量化、批处理、推理调度
- LLM 系统工程:大规模部署、成本控制、生产环境实践、长上下文、并发处理
- RAG / 检索增强:架构、检索器、上下文压缩、生产实践

## 次要关注(中优先级,主题确实有干货才通过)
- 模型训练系统(分布式训练、并行策略、训练框架优化)
- 模型评测、benchmark 设计(尤其是 Agent/工程类评测)
- 重要的开源模型发布(技术报告、权重、训练细节)

## 明确不关注(直接拒绝)
- 纯理论分析、数学证明类论文(没有工程参考价值)
- 计算机视觉(纯 CV、图像分类、目标检测)
- 经典 NLP 任务(机器翻译、命名实体识别等,不涉及大模型)
- 特定垂直应用(医疗、法律、金融、教育的具体场景)
- 小幅度 SOTA 提升(在某 benchmark 上提升 0.X%)
- prompt 技巧、prompt 模板分享类
- 偏研究方法论的探讨(meta 研究、综述综述)
- 安全/对抗/水印等周边方向(除非提出了新的攻击/防御范式)

## 判断原则
- 宁缺毋滥:不确定就拒绝
- 看论文是否回答了"工程师能学到什么具体技术或经验"
- 经典作者/团队(OpenAI、Anthropic、DeepMind、Meta AI、清华、北大等)的工作可以适当放宽
- 综述类只通过主题完全契合的(LLM Agent / Infra / RAG 综述等)

# 输出格式

判断给定的论文标题和摘要,严格输出 JSON:
{
  "relevant": true/false,
  "reason": "一句话理由(<=30字)",
  "category": "Agent" | "Infra" | "RAG" | "Training" | "Other",
  "importance": "P0" | "P1"
}

- relevant=false 时,category 和 importance 设为 "Other" 和 "P1"
- relevant=true 时,category 必须是上述五个之一
- importance: P0=核心关注且高质量, P1=次要关注或核心关注但一般质量
"""

# 批量筛选的 user prompt 模板
BATCH_USER_PROMPT_TEMPLATE = """\
请对下面 {n} 篇论文逐一判断是否相关。

每篇论文格式如下:
[ID: <id>]
Title: <标题>
Abstract: <摘要>

# 论文列表

{items_text}

# 输出要求

严格输出一个 JSON 对象,格式:
{{
  "results": [
    {{
      "id": "<对应的 ID>",
      "relevant": true 或 false,
      "reason": "一句话理由,<=30 字",
      "category": "Agent" 或 "Infra" 或 "RAG" 或 "Training" 或 "Other",
      "importance": "P0" 或 "P1"
    }}
  ]
}}

注意:
- 必须为输入的 {n} 篇全部输出判断,不要遗漏
- id 必须严格使用输入中的 ID,不要修改
- relevant=false 时,category 设为 "Other",importance 设为 "P1"
- 不要输出任何 JSON 之外的文字
"""

def _is_valid_result(r: dict) -> bool:
    if not isinstance(r, dict):
        return False
    required = {"id", "relevant"}
    return required.issubset(r.keys())

def filter_items(db: ItemDB,
                 llm: LLMClient,
                 days: int = 2,
                 batch_size: int = FILTER_BATCH_SIZE) -> Tuple[int, int]:
    """从 db 取最近 N 天 unfiltered items,用 LLM 筛选,把结果写回 db。
    
    Returns:
        (通过筛选的条数, 被筛掉的条数)
    """
    items = db.get_unfiltered_items(days=days)
    if not items:
        logger.info("No unfiltered items to process")
        return 0, 0
    logger.info("Filtering %d items published in the last %d days", len(items), days)

    pass_count = 0
    fail_count = 0

    # 分批处理
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start:batch_start + batch_size]
        try:
            results = _filter_batch(llm, batch)
        except Exception as e:
            logger.exception("Batch failed (items %d-%d): %s",
                             batch_start, batch_start + len(batch), e)
            continue  # 这一批挂了就跳过，处理下一批

        results_by_id = {r["id"]: r for r in results if _is_valid_result(r)}
        for item in batch:
            r = results_by_id.get(item.id)
            if r is None:
                logger.warning("LLM didn't return valid result for item %s", item.id)
                continue
            passed = bool(r.get("relevant", False))

            db.update_filter_result(
                item_id=item.id,
                passed=passed,
                reason=r.get("reason", ""),
                category=r.get("category", "Other"),
                importance=r.get("importance", "P1")
            )
            if passed:
                pass_count += 1
            else:
                fail_count += 1
    logger.info("Filter done: %d passed, %d rejected", pass_count, fail_count)
    return pass_count, fail_count

def _filter_batch(llm: LLMClient, batch: List[Item]) -> List[dict]:
    """对一批 Item 调用一次 LLM,返回结果列表。"""
    # 构造 user prompt
    items_text = "\n\n".join([_format_item(item) for item in batch])
    user_prompt = BATCH_USER_PROMPT_TEMPLATE.format(n=len(batch), items_text=items_text)

    # 调用 LLM
    response = llm.chat_json(
        messages=[
            {"role": "system", "content": INTEREST_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        use_native_json_mode=False,  # 兼容性优先
        thinking=False,  # 筛选是简单分类任务，关掉提速
    )

    if not isinstance(response, dict) or "results" not in response:
        raise ValueError(f"Unexpected LLM response format: {response}")

    results = response["results"]
    if not isinstance(results, list):
        raise ValueError(f"LLM response 'results' is not a list: {results}")

    return results

def _format_item(item: Item) -> str:
    """格式化单个 Item 用于构造 prompt。"""
    return (
        f"[ID: {item.id}]\n"
        f"Title: {item.title}\n"
        f"Abstract: {item.summary}"
    )

if __name__ == "__main__":
    from dotenv import load_dotenv
    
    load_dotenv(override=False)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    db = ItemDB(db_path="data/brief.db")
    llm = LLMClient.from_env()
    
    # 处理最近 5 天的 unfiltered items
    passed, failed = filter_items(db, llm, days=5, batch_size=5)
    print(f"\nResult: {passed} passed, {failed} rejected")
    
    db.close()
