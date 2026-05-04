# daily-ai-brief

> An LLM agent that curates daily AI/Agent/Infra updates from arXiv, GitHub, and curated blogs into a focused brief. Built to fight information overload.

## Why

每天的 AI 信息太多了。这个项目用 LLM Agent 帮我:
- 从 arXiv、GitHub、几个固定博客抓取过去 24 小时的更新
- 自动筛选出我真正关心的内容
- 生成结构化的每日简报

## Status

🚧 Work in progress. Building in public.

## Tech Stack

- Python 3.11+
- LLM: GLM (via 硅基流动)
- Storage: SQLite
- Scheduler: GitHub Actions

## Setup

```bash
# 创建环境
conda create -n daily-ai-brief python=3.11 -y
conda activate daily-ai-brief

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API key
```

## Usage

```bash
# 手动生成今日简报
python main.py

# 输出会写入 briefs/YYYY-MM-DD.md
```

## Roadmap

- [x] Project scaffold
- [ ] MVP: arXiv 抓取 + LLM 筛选总结 + Markdown 输出
- [ ] 加入 RSS 博客源
- [ ] 加入 GitHub trending
- [ ] Prompt 调优
- [ ] GitHub Actions 自动化
- [ ] 加入更多信息源(Twitter, HN)

## License

MIT
