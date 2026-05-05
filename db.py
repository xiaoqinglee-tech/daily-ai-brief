import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from schema import Item

logger = logging.getLogger(__name__)


class ItemDB:
    def __init__(self, db_path: str = 'data/brief.db'):
        # 确保父目录存在
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._initialize_db()

    def _initialize_db(self):
        cursor = self.conn.cursor()
        # 1. 创建表 (加上 IF NOT EXISTS 防止重复运行报错)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id            TEXT PRIMARY KEY,           -- e.g. "arxiv:2310.12345v1"
                source        TEXT NOT NULL,              -- "arxiv" | "rss" | "github"
                title         TEXT NOT NULL,
                url           TEXT NOT NULL,
                summary       TEXT,                       -- 原始 abstract
                authors       TEXT,                       -- JSON 数组的字符串
                tags          TEXT,                       -- JSON 数组的字符串
                extra         TEXT,                       -- JSON 对象的字符串
                published_at  TEXT NOT NULL,              -- ISO 8601 字符串
                fetched_at    TEXT NOT NULL,              -- 抓取时间
                
                -- LLM 处理结果(后续模块填)
                filter_pass   INTEGER,                    -- 0/1/NULL(NULL = 还没筛过)
                filter_reason TEXT,
                llm_summary   TEXT,                       -- LLM 生成的总结
                category      TEXT,                       -- "Agent" | "Infra" | ...
                importance    TEXT,                       -- "P0" | "P1"
                
                -- 简报关联
                brief_date    TEXT                        -- 出现在哪一天的简报里
            );
        ''')
        # 2. 创建索引 (加上 IF NOT EXISTS 防止重复运行报错)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_published_at ON items(published_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_brief_date ON items(brief_date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_filter_pass ON items(filter_pass)')
        self.conn.commit()
        logger.debug("Database and indexes initialized at %s", self.db_path)

    def close(self):
        self.conn.close()

    # 写入(自动去重,已存在的不覆盖,但可以更新)
    def upsert_items(self, items: list[Item]) -> tuple[int, int]:
        """批量插入。已存在的 id 会被忽略(不覆盖)。
    
        Returns:
            (新增条数, 已存在被忽略的条数)
        """
        if not items:
            return 0, 0
    
        new_count = 0
        exist_count = 0
        cursor = self.conn.cursor()
        for item in items:
            cursor.execute('''
                INSERT INTO items (id, source, title, url, summary, authors, tags, extra, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
            ''', (
                item.id,
                item.source,
                item.title,
                item.url,
                item.summary,
                json.dumps(item.authors),
                json.dumps(item.tags),
                json.dumps(item.extra),
                item.published_at.isoformat(),
                item.fetched_at.isoformat()
            ))
            if cursor.rowcount > 0:
                new_count += 1
            else:
                exist_count += 1
        self.conn.commit()
        logger.debug("Upserted items: %d new, %d existing", new_count, exist_count)
        return new_count, exist_count

    @staticmethod
    def _row_to_item(row, has_llm_fields: bool = False) -> Item:
        """把 SQLite row 转回 Item 对象
        
        has_llm_fields: 如果 SELECT 里包含了 llm_summary/category/importance,设 True。
        """
        item = Item(
            id=row[0],
            source=row[1],
            title=row[2],
            url=row[3],
            summary=row[4] or "",
            authors=json.loads(row[5]) if row[5] else [],
            tags=json.loads(row[6]) if row[6] else [],
            extra=json.loads(row[7]) if row[7] else {},
            published_at=datetime.fromisoformat(row[8]),
            fetched_at=datetime.fromisoformat(row[9])
        )

        if has_llm_fields:
            item.llm_summary = row[10] or ""
            item.category = row[11] or ""
            item.importance = row[12] or ""
        return item

    # 查询
    def get_unfiltered_items(self, days: int = 2) -> list[Item]:
        """拿出最近 N 天还没被筛选的条目,供 filter 模块处理"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, source, title, url, summary,
                       authors, tags, extra,
                       published_at, fetched_at
            FROM items
                       WHERE filter_pass IS NULL
                       AND published_at >= ?
            ORDER BY published_at DESC
        ''', (cutoff,))
        rows = cursor.fetchall()
        items = [self._row_to_item(row) for row in rows]
        logger.info("Found %d unfiltered items in last %d days", len(items), days)
        return items

    def get_unsummarized_items(self) -> list[Item]:
        """拿出通过筛选但还没总结的条目"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, source, title, url, summary,
                       authors, tags, extra,
                       published_at, fetched_at
            FROM items
            WHERE filter_pass = 1
              AND (llm_summary IS NULL OR llm_summary = '')
            ORDER BY published_at DESC
        ''')
        rows = cursor.fetchall()
        items = [self._row_to_item(row) for row in rows]
        logger.info("Found %d items needing summarization", len(items))
        return items

    def update_summary(self, item_id: str, summary: str) -> None:
        """写入 LLM 生成的总结"""
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE items
            SET llm_summary = ?
            WHERE id = ?
        ''', (summary, item_id))
        self.conn.commit()
        if cursor.rowcount == 0:
            logger.warning("update_summary: item %s not found", item_id)

    # 更新 LLM 处理结果
    def update_filter_result(self,
                             item_id: str,
                             passed: bool,
                             reason: str,
                             category: str = "",
                             importance: str = ""):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE items
            SET filter_pass = ?,
                filter_reason = ?,
                category = ?,
                importance = ?
            WHERE id = ?
        ''', (1 if passed else 0, reason, category, importance, item_id))
        self.conn.commit()
        if cursor.rowcount == 0:
            logger.warning("update_filter_result: item %s not found", item_id)

    def get_today_brief_items(self, days_window: int = 3) -> list[Item]:
        """拿出过去 N 天通过 filter、有 summary、还没出现在任何简报里的条目。
        
        排序:先按 importance(P0 在前),再按 published_at 倒序。
        
        Args:
            days_window: 时间窗口,只取过去 N 天 published 的论文。
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_window)).isoformat()

        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT id, source, title, url, summary,
                authors, tags, extra,
                published_at, fetched_at,
                llm_summary, category, importance
            FROM items
            WHERE filter_pass = 1
            AND llm_summary IS NOT NULL
            AND llm_summary != ''
            AND brief_date IS NULL
            AND published_at >= ?
            ORDER BY 
            CASE importance WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
            published_at DESC
        ''', (cutoff,))

        rows = cursor.fetchall()
        items = [self._row_to_item(row, has_llm_fields=True) for row in rows]
        logger.info("Found %d items for today's brief", len(items))
        return items

    def mark_in_brief(self, item_ids: list[str], brief_date: str) -> None:
        """标记一批 item 出现在哪一天的简报里。"""
        if not item_ids:
            return
        
        cursor = self.conn.cursor()
        placeholders = ','.join('?' * len(item_ids))
        cursor.execute(
            f'UPDATE items SET brief_date = ? WHERE id IN ({placeholders})',
            [brief_date] + list(item_ids),
        )
        self.conn.commit()
        
        logger.info("Marked %d items into brief %s", cursor.rowcount, brief_date)


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    from fetchers.arxiv_fetcher import fetch_arxiv
    
    # 抓 5 条
    items = fetch_arxiv(
        categories=["cs.AI"],
        days=5,
        max_results=5,
    )
    print(f"\nFetched {len(items)} items from arXiv")
    
    # 存进 db
    db = ItemDB(db_path="data/brief.db")
    new, exist = db.upsert_items(items)
    print(f"DB: {new} new, {exist} existing")
    
    # 第二次跑,应该全部 existing(验证去重)
    new2, exist2 = db.upsert_items(items)
    print(f"Re-run DB: {new2} new, {exist2} existing")
    db.close()
