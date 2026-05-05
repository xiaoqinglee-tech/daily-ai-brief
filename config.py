"""项目级配置。

所有可能因部署/运行场景不同而调整的常量,都集中在这里。
默认值适合本地开发;通过 .env 可以覆盖,适合 GitHub Actions 等场景。

不包括:
- prompt 模板(放在使用它的模块里,如 filter.py / summarizer.py)
- schema 定义(放在 schema.py)
- LLM 客户端的 API key/base URL(由 LLMClient.from_env() 直接读环境变量)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env(只加载一次)
load_dotenv(override=False)


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def _env_int(key: str, default: int) -> int:
    """从环境变量读 int,缺失或格式错则用默认值。"""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_list(key: str, default: list[str], sep: str = ",") -> list[str]:
    """从环境变量读逗号分隔列表,空白会被 strip。"""
    raw = os.getenv(key)
    if not raw:
        return default
    return [s.strip() for s in raw.split(sep) if s.strip()]


# ----------------------------------------------------------------------
# 数据源:arXiv
# ----------------------------------------------------------------------
ARXIV_CATEGORIES: list[str] = _env_list(
    "ARXIV_CATEGORIES",
    default=["cs.AI", "cs.CL", "cs.LG"],
)
ARXIV_DAYS: int = _env_int("ARXIV_DAYS", 3)
ARXIV_MAX_RESULTS: int = _env_int("ARXIV_MAX_RESULTS", 200)


# ----------------------------------------------------------------------
# Pipeline 时间窗口
# ----------------------------------------------------------------------
FILTER_DAYS_WINDOW: int = _env_int("FILTER_DAYS_WINDOW", 5)
BRIEF_DAYS_WINDOW: int = _env_int("BRIEF_DAYS_WINDOW", 7)


# ----------------------------------------------------------------------
# Pipeline 批量参数
# ----------------------------------------------------------------------
FILTER_BATCH_SIZE: int = _env_int("FILTER_BATCH_SIZE", 5)


# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
DB_PATH: str = os.getenv("DB_PATH", "data/brief.db")
BRIEFS_DIR: Path = Path(os.getenv("BRIEFS_DIR", "briefs"))
LOG_DIR: Path = Path(os.getenv("LOG_DIR", "logs"))
