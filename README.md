# Masters Vault

> 大师数据采集器 — 纯采集，不依赖 AI

Last Updated: 2026-05-07

## 架构

```
masters-vault (本仓库)              Masters-Council (数据仓库)
┌──────────────────────┐           ┌─────────────────────────┐
│ collector.py         │           │ vault/                  │
│   纯爬虫，0 AI 依赖   │  ─push──→│   ├── raw/    (原始数据) │
│                      │           │   ├── filtered/(AI过滤后)│
│ filter.py (可选)     │  ─push──→│   └── meta/   (统计元数据)│
│   有 KEY 才跑 AI      │           │                         │
│                      │           │ masters/  (炼油厂在用)   │
│ push.py              │           └─────────────────────────┘
│   推送数据到 Council  │
└──────────────────────┘
```

## 三个独立流程

| 流程 | 文件 | 触发 | 依赖 |
|:-----|:-----|:-----|:-----|
| 采集 | collector.py | 每日 11:37 | 无 AI 依赖 |
| 过滤 | filter.py | 每日 11:57 (可选) | SILICON_FLOW_KEY |
| 保活 | heartbeat.yml | 每日 08:00 | 无 |

## 数据分层

| 层级 | 目录 | 说明 |
|:-----|:-----|:-----|
| raw | vault/raw/ | 纯爬虫采集，完整保留，永远不删 |
| filtered | vault/filtered/ | AI 过滤后，高质量子集 |
| meta | vault/meta/ | 过滤统计、评分分布 |

## 环境变量

| 变量 | 必需 | 说明 |
|:-----|:-----|:-----|
| GH_PAT | 是 | 推送到 Masters-Council 的 token |
| SILICON_FLOW_KEY | 否 | AI 打分用，不设置则仅规则过滤 |

## 目录结构

```
.
├── collector.py              # 采集器 (纯爬虫)
├── filter.py                 # AI 过滤器 (可选)
├── push.py                   # 推送到 Masters-Council
├── config.py                 # 配置
├── masters/                  # 大师配置文件
│   ├── buffett.yml
│   ├── taleb.yml
│   └── ...
├── vault/                    # 本地数据 (push 后可清理)
│   ├── raw/
│   ├── filtered/
│   └── meta/
└── .github/workflows/
    ├── collect.yml           # 每日采集
    ├── filter.yml            # AI 过滤 (可选)
    └── heartbeat.yml         # 保活
```

---
*by [masters-vault](https://github.com/wenfp108/masters-vault) · 数据存储在 [Masters-Council](https://github.com/wenfp108/Masters-Council)*
