```
daily-ai-brief/
├── README.md                    # 项目介绍,后面写文章会引用
├── requirements.txt
├── .github/workflows/daily.yml  # 调度
├── config.py                    # 信息源配置、兴趣画像 prompt
├── main.py                      # 串起整个流程
├── db.py                        # SQLite 操作
├── fetchers/
│   ├── __init__.py
│   ├── arxiv.py
│   ├── rss.py                   # 博客统一用 RSS 抓
│   └── github.py
├── llm.py                       # LLM 调用封装
├── filter.py                    # 筛选逻辑
├── summarizer.py                # 总结逻辑
├── renderer.py                  # 生成 Markdown
├── briefs/                      # 每天的简报输出
│   └── 2026-05-04.md
└── data/
    └── brief.db                 # SQLite 文件
```
