# schema.py
"""项目共享的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Item:
    """一条信息条目,fetchers 的统一输出格式。"""
    
    # 必填字段
    id: str                       # 全局唯一 ID,用于去重(各 fetcher 自己保证唯一性)
    source: str                   # 来源标识: "arxiv" | "rss" | "github"
    title: str
    url: str
    published_at: datetime        # 发布时间 (UTC)
    
    # 可选字段
    summary: str = ""             # 原始摘要/abstract(LLM 总结之前)
    authors: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)  # 原始分类/标签 (e.g. arXiv categories)
    extra: Dict[str, Any] = field(default_factory=dict)  # 来源特有字段
    
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """转 dict,方便存数据库/序列化。"""
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        return d
