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

用户是一位关注 LLM Agent 和 AI Infra 的工程师,核心需求是:
学习"如何构建/优化大语言模型系统",而不是"如何评估这些系统"。

## 核心关注主题

满足下列主题之一,且符合下方"论文类型"要求时通过:

- LLM Agent: 架构设计、规划、工具调用、多智能体协作
- AI Infra: 大模型推理优化(vLLM、SGLang 等)、KV cache、量化、批处理、推理调度
- LLM 系统工程: 大规模部署、成本控制、生产实践、长上下文、并发处理
- RAG / 检索增强: 架构、检索器、上下文压缩、生产实践
- 大模型训练系统: 分布式训练、并行策略、训练框架优化
- 重要的开源大模型发布: 技术报告、权重、训练细节

## 论文类型(关键判断维度)

应该通过的论文类型:
- 方法论文: 提出新的算法、架构、机制
- 系统/Infra 论文: 具体的工程优化、性能改进
- 综述论文: 对某个核心关注主题的系统性整理
- 应用论文: 把 LLM/Agent 用在新场景,且涉及到具体的构建方法

应该拒绝的论文类型(即使主题相关也拒绝):
- Benchmark / 数据集论文: 核心贡献是发布一个评测集
- 评测对比报告: 测试已有模型在某任务上的表现
- 实验观察论文: 观察某现象但不提出解决方案

## 明确不关注的方向(直接拒绝)

- 量子计算、量子机器学习、量子张量网络等量子方向
- 纯理论分析、数学证明类论文
- 计算机视觉(纯 CV、图像分类、目标检测)
- 经典 NLP(机器翻译、命名实体识别等,不涉及大模型)
- 传统机器学习(SVM、决策树、随机森林、传统张量分解等)
- 特定垂直应用(医疗、法律、金融、教育、生物信息)
- 小幅度 SOTA 提升(在某 benchmark 上提升 0.X%)
- prompt 技巧、prompt 模板分享类
- 安全/对抗/水印等周边方向(除非提出新的攻击/防御范式)
- 联邦学习、边缘计算等非大模型核心方向

## 判断原则

- 核心问题: 这篇论文教会读者"如何做一件事",还是"评估一件事做得怎么样"?
- 教"怎么做" 通过(无论是新方法、新优化、新综述还是新应用)
- 评估或测量 拒绝(无论包装得多像"工程")
- 不要被关键词迷惑,看论文的核心贡献是什么
- 如果论文的核心方法不是大语言模型相关,即使提到 ML 术语也拒绝
- 综述类只通过主题完全契合的(LLM Agent / Infra / RAG 综述等)
- 宁缺毋滥: 不确定就拒绝

# 反例: 这些应该被拒绝

## 反例 1: 量子方向伪装成 ML

Title: Entanglement is Half the Story: Post-Selection vs. Partial Traces
摘要提到 tensor networks, machine learning, hybrid architecture, hyperparameter
拒绝理由: 核心是量子机器学习,跟大语言模型无关。
正确判断: relevant=false

## 反例 2: Agent 的 benchmark 论文

Title: AcademiClaw: A bilingual benchmark of 80 complex tasks for AI agents
摘要要点: 发布了 80 任务的 benchmark,测试 6 个 frontier model
拒绝理由: 核心贡献是数据集,工程师从中学不到具体的 Agent 构建方法。
即使主题是 Agent,也属于评测类论文,拒绝。
正确判断: relevant=false

# 正例: 这些应该通过

## 正例 1: 方法论文

Title: ReAct: Synergizing Reasoning and Acting in Language Models
通过理由: 提出新的 Agent 架构(推理 + 行动结合),教读者如何构建 Agent。

## 正例 2: Infra 论文

Title: SpecKV: Adaptive Speculative Decoding with Compression-Aware Gamma Selection
通过理由: 具体的推理优化技术,有可复用的工程价值。

## 正例 3: 综述论文

Title: A Survey of LLM Agent Architectures
通过理由: 系统整理 Agent 领域,帮助读者建立知识图谱。

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
