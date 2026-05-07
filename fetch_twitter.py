"""
Masters Vault — 从 Supabase 拉取 Twitter 数据

从 Supabase 的 twitter_logs 表拉取大师相关推文，
存到 vault/raw/{master}/twitter-{month}.json。

需要环境变量: SUPABASE_URL, SUPABASE_KEY
"""

import os, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJ = timezone(timedelta(hours=8))
DATA_DIR = Path("vault/raw")

# 大师的 Twitter 账号（screen_name）
MASTER_ACCOUNTS = {
    "buffett": ["WarrenBuffett"],
    "dalio": ["RayDalio"],
    "marks": ["HowardMarksxxx"],
    "munger": ["_CharlieMunger"],
    "naval": ["naval"],
    "taleb": ["nntaleb"],
    "soros": ["GeorgeSoros"],
    "li_lu": [],  # Li Lu 没有 Twitter
}

FETCH_LIMIT = 200  # 每个账号拉多少条


def fetch_twitter():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("❌ 未设置 SUPABASE_URL 或 SUPABASE_KEY")
        sys.exit(1)

    from supabase import create_client
    supabase = create_client(url, key)

    month_str = datetime.now(BJ).strftime("%Y-%m")
    total_new = 0

    for master, accounts in MASTER_ACCOUNTS.items():
        if not accounts:
            continue

        print(f"\n📖 拉取推文: {master} ({', '.join(accounts)})")

        # 从 Supabase 查询
        all_tweets = []
        for account in accounts:
            try:
                res = supabase.table("twitter_logs") \
                    .select("*") \
                    .eq("screen_name", account) \
                    .order("bj_time", desc=True) \
                    .limit(FETCH_LIMIT) \
                    .execute()
                tweets = res.data or []
                all_tweets.extend(tweets)
                print(f"   📡 {account}: {len(tweets)} 条")
            except Exception as e:
                print(f"   ⚠️ {account}: {e}")

        if not all_tweets:
            print(f"   ⏭️  无数据")
            continue

        # 转成统一格式
        items = []
        for t in all_tweets:
            items.append({
                "type": "tweet",
                "title": (t.get("full_text") or "")[:200],
                "url": t.get("url", ""),
                "published": t.get("bj_time", ""),
                "source": "supabase",
                "account": t.get("screen_name", ""),
                "user_name": t.get("user_name", ""),
                "likes": t.get("likes", 0),
                "retweets": t.get("retweets", 0),
                "replies": t.get("replies", 0),
                "bookmarks": t.get("bookmarks", 0),
                "views": t.get("views", 0),
            })

        # 保存到 vault/raw/{master}/twitter-{month}.json
        out_dir = DATA_DIR / master
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"twitter-{month_str}.json"

        existing = []
        if out_file.exists():
            existing = json.loads(out_file.read_text())

        # 去重
        existing_urls = {i.get("url") for i in existing}
        new_items = [i for i in items if i.get("url") not in existing_urls]

        if new_items:
            existing.extend(new_items)
            out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2))
            print(f"   ✅ 新增 {len(new_items)} 条 (总计 {len(existing)})")
            total_new += len(new_items)
        else:
            print(f"   ✅ 无新增 (总计 {len(existing)})")

    print(f"\n🏛️ 推文拉取完成: {total_new} 条新增")


if __name__ == "__main__":
    fetch_twitter()
