# Masters Vault

> 大师数据采集器 — 纯采集，不依赖 AI

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    masters-vault (本仓库)                 │
│                                                         │
│  collector.py            fetch_twitter.py               │
│  爬虫采集                  从 Supabase 拉取               │
│  (YouTube/News/Arxiv/     x-kit 精选推文                  │
│   Podcast/Books)              │                          │
│        │                      │                          │
│        └──────────┬───────────┘                          │
│                   ▼                                      │
│           vault/raw/{master}/{month}.json                │
│                                                         │
│  filter.py (可选)                                         │
│  规则过滤 + AI 打分                                       │
│                   │                                      │
│                   ▼                                      │
│  vault/filtered/{master}/{month}-{type}.json             │
│                                                         │
│  push.py ──→ Masters-Council                             │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│               Masters-Council (数据仓库)                 │
│                                                         │
│  vault/raw/          原始数据，按大师+月份                │
│  vault/filtered/     AI 过滤后，按类型分文件              │
│  vault/meta/         过滤统计                            │
│  vault/.seen.json    全局去重记录                         │
│  masters/            大师配置 (yml)                       │
└─────────────────────────────────────────────────────────┘
```

## 数据来源

| 来源 | 脚本 | 内容 |
|:-----|:-----|:-----|
| YouTube | collector.py | 视频搜索，按大师关键词 |
| Google News | collector.py | 新闻文章 RSS |
| Arxiv | collector.py | 学术论文 |
| Apple Podcasts | collector.py | 播客节目 |
| Supabase (x-kit) | fetch_twitter.py | 精选推文，按互动分排序 |

## 流程

| 流程 | 时间 | 说明 |
|:-----|:-----|:-----|
| 采集 | 每日 11:37 BJT | collector.py + fetch_twitter.py，推送 raw |
| 过滤 | 每日 11:57 BJT | filter.py，推送 filtered (可选) |
| 保活 | 每日 08:00 BJT | heartbeat.yml 更新时间戳 |

## 数据分层

| 层级 | 说明 |
|:-----|:-----|
| raw | 爬虫 + Supabase 原始数据，按月追加，永不删除 |
| filtered | 规则 + AI 过滤后的高质量子集 |
| meta | 过滤统计、评分分布 |

## 环境变量

| 变量 | 必需 | 说明 |
|:-----|:-----|:-----|
| GH_PAT | 是 | Masters-Council 写权限 token |
| SUPABASE_URL | 否 | Supabase 地址，拉取推文用 |
| SUPABASE_KEY | 否 | Supabase Key |
| SILICON_FLOW_KEY | 否 | AI 打分，不设置则仅规则过滤 |

## 文件说明

```
collector.py        # 采集器 — YouTube/News/Arxiv/Podcast/Books
fetch_twitter.py    # 推文拉取 — 从 Supabase raw_signals 表
filter.py           # AI 过滤器 — 规则 + 小模型打分 (可选)
push.py             # 推送 — vault/ → Masters-Council
masters/            # 大师配置 (yml)，定义采集源
requirements.txt    # Python 依赖
.github/workflows/  # GitHub Actions 自动化
```

---
*数据存储在 [Masters-Council](https://github.com/wenfp108/Masters-Council)*
