"""
Masters Vault — 数据采集器
每天爬一次，收集大师相关的书籍、视频、推文、播客、文章链接。
"""

import os, json, yaml, hashlib, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import feedparser

BJ = timezone(timedelta(hours=8))
DATA_DIR = Path("data")
DEDUP_FILE = DATA_DIR / ".seen.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def load_seen():
    if DEDUP_FILE.exists():
        return json.loads(DEDUP_FILE.read_text())
    return {}


def save_seen(seen):
    DEDUP_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2))


def item_id(item):
    key = item.get("url") or item.get("title", "")
    return hashlib.md5(key.encode()).hexdigest()


def load_masters():
    masters = []
    for f in Path("masters").glob("*.yml"):
        with open(f) as fh:
            cfg = yaml.safe_load(fh)
            cfg["_file"] = f.stem
            masters.append(cfg)
    return masters


# ─── YouTube (via yt-dlp search) ─────────────────────────

def search_youtube(query, limit=10):
    try:
        import yt_dlp
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "default_search": "ytsearch",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        items = []
        for entry in (result.get("entries") or [])[:limit]:
            items.append({
                "type": "video",
                "title": entry.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                "duration": entry.get("duration"),
                "channel": entry.get("channel", entry.get("uploader", "")),
                "source": "youtube",
            })
        return items
    except Exception as e:
        print(f"   ⚠️ YouTube 搜索失败 [{query}]: {e}")
        return []


# ─── Podcasts (iTunes Search API) ─────────────────────────

def search_podcasts(query, limit=10):
    try:
        r = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "podcast", "limit": limit},
            headers=HEADERS, timeout=15
        )
        data = r.json()
        items = []
        for p in data.get("results", []):
            items.append({
                "type": "podcast",
                "title": p.get("trackName", p.get("collectionName", "")),
                "url": p.get("trackViewUrl", p.get("collectionViewUrl", "")),
                "author": p.get("artistName", ""),
                "source": "apple-podcasts",
            })
        return items
    except Exception as e:
        print(f"   ⚠️ 播客搜索失败 [{query}]: {e}")
        return []


# ─── Arxiv ─────────────────────────────────────────────────

def search_arxiv(query, limit=5):
    try:
        r = requests.get(
            "http://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            headers=HEADERS, timeout=15
        )
        items = []
        for entry in feedparser.parse(r.text).entries:
            items.append({
                "type": "paper",
                "title": entry.get("title", "").replace("\n", " "),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": "arxiv",
            })
        return items
    except Exception as e:
        print(f"   ⚠️ Arxiv 搜索失败 [{query}]: {e}")
        return []


# ─── Google News RSS ──────────────────────────────────────

def search_news(query, limit=10):
    try:
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en"
        r = requests.get(url, headers=HEADERS, timeout=15)
        feed = feedparser.parse(r.text)
        items = []
        for entry in feed.entries[:limit]:
            items.append({
                "type": "article",
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": "google-news",
            })
        return items
    except Exception as e:
        print(f"   ⚠️ 新闻搜索失败 [{query}]: {e}")
        return []


# ─── Z-Library (搜索链接) ──────────────────────────────────

def search_zlibrary(query, limit=5):
    """返回 zlibrary 搜索页链接，不直接爬内容"""
    search_url = f"https://z-lib.org/s/{requests.utils.quote(query)}"
    return [{
        "type": "book",
        "title": f"Z-Library: {query}",
        "url": search_url,
        "source": "zlibrary",
    }]


# ─── Goodreads ─────────────────────────────────────────────

def search_goodreads(query, limit=5):
    try:
        r = requests.get(
            "https://www.goodreads.com/search",
            params={"q": query, "search_type": "books"},
            headers=HEADERS, timeout=15
        )
        # 只返回搜索页链接
        return [{
            "type": "book-list",
            "title": f"Goodreads: {query}",
            "url": f"https://www.goodreads.com/search?q={requests.utils.quote(query)}",
            "source": "goodreads",
        }]
    except Exception as e:
        print(f"   ⚠️ Goodreads 失败 [{query}]: {e}")
        return []


# ─── 主采集流程 ────────────────────────────────────────────

CRAWLERS = {
    "youtube": lambda cfg: _crawl_youtube(cfg),
    "twitter": lambda cfg: _crawl_twitter(cfg),
    "books": lambda cfg: _crawl_books(cfg),
    "podcasts": lambda cfg: _crawl_podcasts(cfg),
    "articles": lambda cfg: _crawl_articles(cfg),
    "academic": lambda cfg: _crawl_academic(cfg),
    "blogs": lambda cfg: _crawl_blogs(cfg),
    "reports": lambda cfg: _crawl_reports(cfg),
}


def _crawl_youtube(cfg):
    items = []
    for src in cfg.get("sources", {}).get("youtube", []):
        q = src["query"]
        limit = src.get("limit", 10)
        items.extend(search_youtube(q, limit))
        time.sleep(1)
    return items


def _crawl_twitter(cfg):
    # Twitter 搜索通过 Google News RSS 间接获取
    items = []
    account = None
    for src in cfg.get("sources", {}).get("twitter", []):
        if "account" in src:
            account = src["account"]
        for kw in src.get("keywords", []):
            items.extend(search_news(f"twitter {kw}", limit=5))
            time.sleep(0.5)
    # 也搜索 nitter RSS（如果可用）
    if account:
        try:
            r = requests.get(f"https://nitter.net/{account}/rss", headers=HEADERS, timeout=10)
            if r.status_code == 200:
                feed = feedparser.parse(r.text)
                for entry in feed.entries[:20]:
                    items.append({
                        "type": "tweet",
                        "title": entry.get("title", "")[:100],
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": "twitter",
                        "account": account,
                    })
        except Exception:
            pass
    return items


def _crawl_books(cfg):
    items = []
    for src in cfg.get("sources", {}).get("books", []):
        q = src["query"]
        items.extend(search_zlibrary(q))
        time.sleep(0.5)
    return items


def _crawl_podcasts(cfg):
    items = []
    for src in cfg.get("sources", {}).get("podcasts", []):
        if "url" in src:
            items.append({
                "type": "podcast",
                "title": src.get("name", ""),
                "url": src["url"],
                "source": "podcast-feed",
            })
        if "query" in src:
            items.extend(search_podcasts(src["query"], limit=5))
            time.sleep(0.5)
    return items


def _crawl_articles(cfg):
    items = []
    for src in cfg.get("sources", {}).get("articles", []):
        q = src["query"]
        items.extend(search_news(q, limit=10))
        time.sleep(0.5)
    return items


def _crawl_academic(cfg):
    items = []
    for src in cfg.get("sources", {}).get("academic", []):
        if src.get("platform") == "arxiv":
            items.extend(search_arxiv(src["query"], limit=5))
            time.sleep(1)
    return items


def _crawl_blogs(cfg):
    items = []
    for src in cfg.get("sources", {}).get("blogs", []):
        items.append({
            "type": "blog",
            "title": src.get("name", ""),
            "url": src["url"],
            "source": "blog",
        })
    return items


def _crawl_reports(cfg):
    items = []
    for src in cfg.get("sources", {}).get("reports", []):
        items.append({
            "type": "report",
            "title": src.get("name", ""),
            "url": src["url"],
            "source": src.get("type", "report"),
        })
    return items


def collect_master(master, seen):
    name = master.get("name", "unknown")
    file_key = master["_file"]
    print(f"\n📖 采集: {name}")

    all_items = []
    for source_type, crawler in CRAWLERS.items():
        if source_type in _flatten_sources(master):
            items = crawler(master)
            all_items.extend(items)

    # 去重
    new_items = []
    for item in all_items:
        iid = item_id(item)
        if iid not in seen:
            seen[iid] = {
                "first_seen": datetime.now(BJ).isoformat(),
                "master": file_key,
                "type": item.get("type"),
            }
            new_items.append(item)

    print(f"   ✅ {len(all_items)} 条采集, {len(new_items)} 条新增")
    return new_items


def _flatten_sources(cfg):
    """返回 master 配置里有哪些 source 类型"""
    sources = cfg.get("sources", {})
    return set(sources.keys())


def save_data(master_key, items):
    day_str = datetime.now(BJ).strftime("%Y%m%d")
    out_dir = DATA_DIR / master_key
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{day_str}.json"

    # 追加到当日文件
    existing = []
    if out_file.exists():
        existing = json.loads(out_file.read_text())
    existing.extend(items)
    out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return len(existing)


def generate_readme(masters_results):
    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    total_new = sum(r["new"] for r in masters_results)
    total_all = sum(r["total"] for r in masters_results)

    md = f"""# 🏛️ Masters Vault

> 大师数据归档 — 每日自动采集
>
> 更新：{now} BJT

| 大师 | 今日新增 | 总量 | 数据源 |
|:-----|:--------|:-----|:-------|
"""
    for r in sorted(masters_results, key=lambda x: x["new"], reverse=True):
        md += f"| {r['name']} | +{r['new']} | {r['total']} | {r['sources']} |\n"

    md += f"""
**合计**: {total_new} 条新增 / {total_all} 条总量

## 数据说明

| 类型 | 存储方式 |
|:-----|:---------|
| 书籍 | zlibrary 链接 |
| 视频 | YouTube 链接 + 标题 |
| 推文 | 公开内容 (via nitter/Google News) |
| 播客 | RSS / Apple Podcasts 链接 |
| 文章 | 新闻链接 + 标题 |
| 论文 | arxiv 链接 |
| 年报/备忘录 | 官方链接 |

## 目录结构

```
data/
├── munger/     # Charlie Munger
├── naval/      # Naval Ravikant
├── dalio/      # Ray Dalio
├── taleb/      # Nassim Taleb
├── buffett/    # Warren Buffett
├── marks/      # Howard Marks
├── li_lu/      # Li Lu
└── soros/      # George Soros
```

---
*by [masters-vault](https://github.com/wenfp108/masters-vault) · 每日自动采集*
"""
    Path("README.md").write_text(md, encoding="utf-8")


def main():
    DATA_DIR.mkdir(exist_ok=True)
    seen = load_seen()
    masters = load_masters()
    results = []

    for master in sorted(masters, key=lambda m: m.get("name")):
        name = master.get("name", "unknown")
        file_key = master["_file"]

        # 检查更新频率（soros 等低频大师）
        freq = master.get("update_freq", "daily")
        if freq == "weekly":
            day_of_week = datetime.now(BJ).weekday()
            if day_of_week != 0:  # 周一才更新
                print(f"⏭️ {name}: weekly 更新，跳过")
                continue

        new_items = collect_master(master, seen)
        total = save_data(file_key, new_items)

        source_types = set(i.get("type") for i in new_items)
        results.append({
            "name": name,
            "new": len(new_items),
            "total": total,
            "sources": ", ".join(sorted(source_types)) if source_types else "-",
        })

    save_seen(seen)
    generate_readme(results)

    total_new = sum(r["new"] for r in results)
    print(f"\n🏛️ 采集完成: {total_new} 条新增, {len(masters)} 位大师")


if __name__ == "__main__":
    main()
