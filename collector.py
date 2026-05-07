"""
Masters Vault — 数据采集器
每天爬一次，收集大师相关的书籍、视频、推文、播客、文章链接。
纯采集，不依赖 AI。原始数据存到 vault/raw/。
"""

import os, json, yaml, hashlib, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests
import feedparser

BJ = timezone(timedelta(hours=8))
DATA_DIR = Path("vault/raw")
DEDUP_FILE = Path("vault/.seen.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def load_seen():
    if DEDUP_FILE.exists():
        return json.loads(DEDUP_FILE.read_text())
    return {}


def save_seen(seen):
    DEDUP_FILE.parent.mkdir(parents=True, exist_ok=True)
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
    """推文采集：通过 Google News RSS 间接获取
    注：nitter 已死，不再尝试。正经推文数据由 x-kit 项目提供。"""
    items = []
    for src in cfg.get("sources", {}).get("twitter", []):
        for kw in src.get("keywords", []):
            items.extend(search_news(f"twitter {kw}", limit=5))
            time.sleep(0.5)
    # URL 转换：nitter → x.com
    for item in items:
        item["url"] = _fix_twitter_url(item.get("url", ""))
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


# ─── 采集时算法过滤 ───────────────────────────────────────

def _fix_twitter_url(url):
    """nitter URL → x.com 原链接"""
    if not url:
        return url
    # nitter.net/RayDalio/status/xxx#m → x.com/RayDalio/status/xxx
    import re
    match = re.search(r"nitter\.net/([^/]+/status/\d+)", url)
    if match:
        return f"https://x.com/{match.group(1)}"
    return url


def clean_items(items):
    """按内容类型做规则过滤，采集时就剔除噪音"""
    cleaned = []
    for item in items:
        # 通用 URL 修复
        item["url"] = _fix_twitter_url(item.get("url", ""))
        if _should_keep(item):
            cleaned.append(item)
    return cleaned


def _should_keep(item):
    """单条数据是否值得保留"""
    title = (item.get("title") or "").strip()
    itype = item.get("type", "")

    # 通用：标题太短
    if len(title) < 10:
        return False

    # 通用：全是大写（标题党特征）
    if title.isupper() and len(title) > 20:
        return False

    # 通用：标题党关键词
    title_lower = title.lower()
    blockwords = [
        "reaction", "reacts to", "responds to", "responding to",
        "top 10", "top 5", "top 100", "you won't believe",
        "compilation", "best of", "moments", "try not to laugh",
        "tiktok", "shorts", "clickbait",
    ]
    if any(kw in title_lower for kw in blockwords):
        return False

    # 按类型过滤
    if itype == "video":
        return _keep_video(item)
    elif itype == "tweet":
        return _keep_tweet(item)
    elif itype == "article":
        return _keep_article(item)
    elif itype == "book":
        return _keep_book(item)

    # paper, podcast, report, blog → 默认保留
    return True


def _keep_video(item):
    """视频过滤：去短视频、切片"""
    duration = item.get("duration")

    # 短视频 < 120 秒（切片、Shorts）
    if duration and duration < 120:
        return False

    # 标题暗示是切片
    title_lower = (item.get("title") or "").lower()
    clip_hints = ["clip", "short", "highlight", "moment", "excerpt"]
    if any(h in title_lower for h in clip_hints):
        return False

    return True


def _keep_tweet(item):
    """推文过滤：去太短、去纯转推"""
    title = item.get("title", "")

    # 太短的推文没有信息量
    if len(title) < 30:
        return False

    # 纯转推标记
    if title.startswith("RT ") or title.startswith("RT:"):
        return False

    # 只是 @ 了某人，没有实质内容
    if title.count("@") > 3 and len(title.split()) < 10:
        return False

    return True


def _keep_article(item):
    """文章过滤：去纯引用标题"""
    title = item.get("title", "")

    # 标题只是带引号的引用（如: Dalio says "xxx"）
    # 这类通常是低质量新闻引用一句话
    if title.startswith('"') and title.endswith('"') and len(title) < 80:
        return False

    # Google News 特有的 "来源 - 站名" 格式，标题部分太短
    if " - " in title:
        headline = title.rsplit(" - ", 1)[0].strip()
        if len(headline) < 15:
            return False

    return True


def _keep_book(item):
    """书籍过滤：去泛搜索链接"""
    title = item.get("title", "")

    # Z-Library 泛搜索页（不是具体书）
    if title.startswith("Z-Library:"):
        return False

    # Goodreads 搜索页
    if title.startswith("Goodreads:"):
        return False

    return True


def collect_master(master, seen):
    name = master.get("name", "unknown")
    file_key = master["_file"]
    print(f"\n📖 采集: {name}")

    all_items = []
    for source_type, crawler in CRAWLERS.items():
        if source_type in _flatten_sources(master):
            items = crawler(master)
            all_items.extend(items)

    # 采集时算法过滤
    before_clean = len(all_items)
    all_items = clean_items(all_items)
    cleaned = before_clean - len(all_items)
    if cleaned:
        print(f"   🧹 算法过滤: 去除 {cleaned} 条噪音")

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

    print(f"   ✅ {before_clean} → {len(new_items)} 条 (算法去噪 {cleaned}, 去重 {len(all_items) - len(new_items)})")
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

    existing = []
    if out_file.exists():
        existing = json.loads(out_file.read_text())

    # 同日去重：按 url+title 去重
    existing_keys = {item_id(i) for i in existing}
    new_items = [i for i in items if item_id(i) not in existing_keys]

    existing.extend(new_items)
    out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
    return len(existing)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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

    total_new = sum(r["new"] for r in results)
    print(f"\n🏛️ 采集完成: {total_new} 条新增, {len(masters)} 位大师")
    print(f"📁 原始数据: {DATA_DIR.resolve()}")

    # 输出摘要供 push.py 使用
    summary = {
        "timestamp": datetime.now(BJ).isoformat(),
        "total_new": total_new,
        "masters": len(masters),
        "results": results,
    }
    Path("vault/last_collect.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
