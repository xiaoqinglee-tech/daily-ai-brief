"""渲染模块:把 db 里的简报条目渲染成 markdown 文件。"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import List, Optional

from db import ItemDB
from schema import Item

logger = logging.getLogger(__name__)


# 输出目录
BRIEFS_DIR = Path("briefs")

# Category 显示顺序(更重要的在前)
CATEGORY_ORDER = ["Agent", "Infra", "RAG", "Training", "Other"]


def render_today_brief(
    db: ItemDB,
    output_dir: Path = BRIEFS_DIR,
    days_window: int = 3,
    today: Optional[date] = None,
) -> Optional[Path]:
    """生成今日简报,返回生成的文件路径。
    
    如果没有可用条目,不生成文件,返回 None。
    """
    today = today or date.today()
    today_str = today.isoformat()
    
    items = db.get_today_brief_items(days_window=days_window)
    
    if not items:
        logger.info("No items for today's brief")
        return None
    
    # 按 category 分组(已经按 importance + published_at 排好序了)
    grouped = defaultdict(list)
    for item in items:
        cat = item.category or "Other"
        grouped[cat].append(item)
    
    # 按 CATEGORY_ORDER 排列 category,未知 category 放最后
    ordered_categories = [c for c in CATEGORY_ORDER if c in grouped]
    extras = sorted(c for c in grouped if c not in CATEGORY_ORDER)
    ordered_categories.extend(extras)
    
    # 渲染 markdown
    md = _render_markdown(today_str, items, grouped, ordered_categories)
    
    # 写文件
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{today_str}.md"
    output_path.write_text(md, encoding="utf-8")
    logger.info("Wrote brief to %s (%d items)", output_path, len(items))
    
    # 标记 db
    db.mark_in_brief([item.id for item in items], today_str)
    
    return output_path


def _render_markdown(
    today_str: str,
    items: List[Item],
    grouped: dict,
    ordered_categories: List[str],
) -> str:
    """构造 markdown 内容。"""
    lines = []
    
    # 标题
    lines.append(f"# AI Daily Brief - {today_str}")
    lines.append("")
    
    # 顶部统计
    stats_parts = [f"{cat} {len(grouped[cat])}" for cat in ordered_categories]
    lines.append(f"> 共 {len(items)} 条 · {' / '.join(stats_parts)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # 各 category 章节
    for cat in ordered_categories:
        cat_items = grouped[cat]
        lines.append(f"## {cat} ({len(cat_items)})")
        lines.append("")
        
        for item in cat_items:
            lines.append(f"### [{item.title}]({item.url})")
            lines.append("")
            lines.append(item.llm_summary)
            lines.append("")
            lines.append("---")
            lines.append("")
    
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    db = ItemDB(db_path="data/brief.db")
    
    output_path = render_today_brief(db)
    if output_path:
        print(f"\n=== Brief generated: {output_path} ===\n")
        print(output_path.read_text(encoding="utf-8"))
    else:
        print("No items for today's brief")
    
    db.close()
