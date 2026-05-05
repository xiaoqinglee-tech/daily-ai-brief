# daily-ai-brief
[![Daily AI Brief Generator](https://github.com/xiaoqinglee-tech/daily-ai-brief/actions/workflows/daily.yml/badge.svg)](https://github.com/xiaoqinglee-tech/daily-ai-brief/actions/workflows/daily.yml)

> 一个用 LLM 作为筛选与总结引擎的 AI 论文每日简报工具。从 arXiv 抓取上百篇论文,用大模型筛掉无关内容、生成结构化总结,最终输出一份你愿意每天看的 Markdown 简报。

## Why

AI 信息太多了。

每天 cs.AI / cs.CL / cs.LG 三个分类有数十到数百篇新论文,绝大多数跟一个工程师无关。常见的工具(订阅 newsletter、刷 Twitter、看 trending)要么被动、要么噪音大、要么不可定制。

这个项目想做的是:**让一个 LLM 知道我的兴趣,每天替我做"扫读 + 筛选 + 总结"**,把信息过载问题转成一份简报。

## Output Sample

每天产出一份长这样的 Markdown 简报(完整内容见 [briefs/](briefs/)):

```markdown
# AI Daily Brief - 2026-05-05

> 共 9 条 · Agent 4 / Infra 3 / Training 2

## Agent (4)

### [SpecKV: Adaptive Speculative Decoding ...](http://arxiv.org/abs/2605.02888v1)

【做了什么】提出自适应投机解码控制器,动态选择推测长度以加速推理。
【怎么做】基于量化级别分析,用小MLP根据draft模型置信度和熵预测最优长度。
【适合谁看】做量化LLM推理加速与投机解码优化的系统工程师。

### [FlexSQL: Flexible Exploration ...](http://arxiv.org/abs/2605.02815v1)
...
```

## Architecture

```
arXiv API
    │
    ▼
┌─────────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐
│  fetchers/  │ ─▶ │  db.py   │ ─▶ │ filter.py  │ ─▶ │summarizer│
│  抓原始论文  │    │ SQLite   │    │ LLM 筛选    │    │ LLM 总结  │
└─────────────┘    └──────────┘    └────────────┘    └──────────┘
                        │                                  │
                        └──────────────────┬───────────────┘
                                           ▼
                                     ┌──────────┐
                                     │renderer  │ ─▶ briefs/YYYY-MM-DD.md
                                     │  渲染    │
                                     └──────────┘
```

每个模块**只负责一件事**,通过 SQLite 解耦,断点恢复友好。

## Key Design Choices

| 决策 | 为什么 |
|------|--------|
| 用 SQLite 持久化中间状态 | LLM 调用花钱,每一步结果都该留下;失败可断点续跑 |
| Filter 用批量,Summarizer 用逐条 | 筛选是分类任务可批量,总结质量优先要逐条 |
| Filter 用 ID 对齐,不依赖 LLM 输出顺序 | LLM 输出顺序不可靠,按 ID 匹配最稳 |
| `INSERT ... ON CONFLICT DO NOTHING` | 重复抓到同一篇论文是常态,不应该报错也不应该覆盖 |
| Prompt 用 few-shot + 反例 | 比纯描述更稳定,反例尤其能教 LLM 学到边界 |
| 总结输出加 `<br>` 分隔 | 跨 Markdown 渲染器(GitHub / Obsidian / 公众号)兼容 |

## Tech Stack

- Python 3.11
- LLM: 任何 OpenAI 兼容 API(默认硅基流动 GLM)
- Storage: SQLite
- Scheduler: GitHub Actions (每天 UTC 0:00 自动触发)

## Project Structure

```
daily-ai-brief/
├── llm.py              # 通用 LLM 客户端 (retry / json / streaming / thinking)
├── schema.py           # 核心数据模型 Item
├── db.py               # SQLite 存储与查询
├── config.py           # 配置(可被 .env 覆盖)
├── fetchers/
│   ├── arxiv_fetcher.py    # arXiv 抓取
│   ├── rss_fetcher.py      # RSS(尚未实现)
│   └── github_fetcher.py   # GitHub trending(尚未实现)
├── items_filter.py     # 用 LLM 筛选哪些论文值得看
├── summarizer.py       # 用 LLM 生成结构化中文总结
├── renderer.py         # 把通过的论文渲染成 Markdown
├── main.py             # 主入口,串联所有步骤
├── briefs/             # 每日简报输出
├── data/brief.db       # SQLite 文件(本地,不入版本控制)
└── logs/               # 运行日志
```

## Setup

```bash
# 创建环境
conda create -n daily-ai-brief python=3.11 -y
conda activate daily-ai-brief

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 LLM API key
```

## Usage

```bash
# 完整跑一次:抓取 → 筛选 → 总结 → 渲染
python main.py

# 跳过抓取(用 db 里已有数据,适合调试 prompt)
python main.py --skip-fetch
```

输出位于 `briefs/YYYY-MM-DD.md`,运行日志位于 `logs/YYYY-MM-DD.log`。

## Configuration

通过 `.env` 自定义运行参数(默认值见 `config.py`):

```bash
# arXiv 抓取
ARXIV_CATEGORIES=cs.AI,cs.CL,cs.LG
ARXIV_DAYS=3
ARXIV_MAX_RESULTS=200

# Pipeline 时间窗口
FILTER_DAYS_WINDOW=5
BRIEF_DAYS_WINDOW=7

# 批处理
FILTER_BATCH_SIZE=5
```

## Customizing the Filter

筛选 prompt 在 `items_filter.py` 中的 `INTEREST_PROMPT` 变量。这是项目里**最值得调的部分**——它决定了筛选质量。

修改 prompt 时建议:
- 用真实的"误判论文"作为反例加进去
- 一次只改一个维度,跑数据看效果
- 把每次改动 commit 一下,git history 就是你的 prompt 实验日志

## Roadmap

- [x] arXiv 抓取
- [x] LLM 筛选(批量 + ID 对齐)
- [x] LLM 总结(三段式 + 字数控制)
- [x] Markdown 渲染(分类分组,跨渲染器兼容)
- [x] 主入口与统一日志
- [x] GitHub Actions 每日自动运行
- [ ] RSS 博客源(Simon Willison / Lilian Weng / Anthropic Engineering 等)
- [ ] GitHub trending(关注度增长快的 LLM/Agent 项目)
- [ ] Prompt 迭代实验记录

## License

MIT
