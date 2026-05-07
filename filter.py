"""
Masters Vault — AI 过滤器 (独立运行)

从 vault/raw/ 读原始数据，过滤后写到 vault/filtered/。
不设置 SILICON_FLOW_KEY 时仅使用规则过滤。

独立于 collector.py，可单独运行。
"""

import os, json, re, time, glob
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

BJ = timezone(timedelta(hours=8))

# === 配置 ===
RAW_DIR = Path("vault/raw")
FILTERED_DIR = Path("vault/filtered")
META_DIR = Path("vault/meta")

AI_API_URL = "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions"
AI_MODEL = "mimo-v2.5-pro"
AI_API_KEY_ENV = "SILICON_FLOW_KEY"
AI_TIMEOUT = 30
AI_MAX_RETRIES = 3

SCORE_BATCH_SIZE = 10
SCORE_THRESHOLD = 3
RULE_MIN_TITLE_WORDS = 5

RULE_BLOCKWORDS = [
    "reaction", "reacts to", "responds to", "responding to",
    "top 10", "top 5", "top 100",
    "compilation", "best of", "moments",
    "try not to laugh", "challenge",
    "tiktok", "shorts",
    "clickbait", "you won't believe",
]


# ─── 第一级: 规则过滤 ────────────────────────────────────

def rule_filter(items):
    """零成本规则过滤，去掉明显噪音"""
    seen_urls = set()
    filtered = []

    for item in items:
        title = (item.get("title") or "").strip()
        url = item.get("url", "")

        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        if len(title.split()) < RULE_MIN_TITLE_WORDS:
            continue

        title_lower = title.lower()
        if any(kw in title_lower for kw in RULE_BLOCKWORDS):
            continue

        filtered.append(item)

    return filtered


# ─── 第二级: AI 批量打分 ─────────────────────────────────

SCORE_SYSTEM = "你是内容质量评估器。只输出 JSON 数组，不要输出其他内容。"
SCORE_PROMPT = """对以下 {n} 条内容逐条打分。

评分标准:
5 = 大师核心原创洞见、深度访谈、重要演讲
4 = 有价值的二手分析、详细解读
3 = 一般性报道、常规内容
2 = 浅层内容、重复信息
1 = 噪音、标题党、无关内容

输出格式: [{{"id": 1, "score": 5}}, ...]

{items}"""


def _format_items_for_scoring(items):
    lines = []
    for i, item in enumerate(items):
        title = item.get("title", "")
        itype = item.get("type", "")
        source = item.get("source", "")
        lines.append(f"{i+1}. [{itype}/{source}] {title}")
    return "\n".join(lines)


def _call_ai(prompt):
    api_key = os.environ.get(AI_API_KEY_ENV)
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": SCORE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    for attempt in range(AI_MAX_RETRIES):
        try:
            resp = requests.post(
                AI_API_URL, json=payload, headers=headers, timeout=AI_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            print(f"   ⏳ AI 超时 (第 {attempt+1}/{AI_MAX_RETRIES} 次)")
        except requests.exceptions.HTTPError as e:
            print(f"   ⚠️ AI HTTP {e.response.status_code} (第 {attempt+1}/{AI_MAX_RETRIES} 次)")
        except Exception as e:
            print(f"   ⚠️ AI 异常: {e} (第 {attempt+1}/{AI_MAX_RETRIES} 次)")

        if attempt < AI_MAX_RETRIES - 1:
            time.sleep(2 ** (attempt + 1))

    return None


def _parse_scores(raw_text, count):
    try:
        scores = json.loads(raw_text)
        if isinstance(scores, list) and len(scores) == count:
            return [s.get("score", 0) for s in scores]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", raw_text, re.DOTALL)
    if match:
        try:
            scores = json.loads(match.group())
            if len(scores) == count:
                return [s.get("score", 0) for s in scores]
        except json.JSONDecodeError:
            pass

    return None


def score_batch(items):
    """AI 批量打分，返回带 score 的 items"""
    api_key = os.environ.get(AI_API_KEY_ENV)
    if not api_key:
        print("   ℹ️  未设置 SILICON_FLOW_KEY，跳过 AI 打分")
        return items

    scored_items = []
    batches = [items[i:i + SCORE_BATCH_SIZE] for i in range(0, len(items), SCORE_BATCH_SIZE)]

    for batch_idx, batch in enumerate(batches):
        print(f"   🤖 AI 打分: 批次 {batch_idx + 1}/{len(batches)} ({len(batch)} 条)")

        prompt = SCORE_PROMPT.format(
            n=len(batch),
            items=_format_items_for_scoring(batch),
        )
        raw = _call_ai(prompt)

        if raw:
            scores = _parse_scores(raw, len(batch))
            if scores:
                for item, score in zip(batch, scores):
                    item["ai_score"] = score
                    scored_items.append(item)
                continue

        # 打分失败，保留所有
        for item in batch:
            item["ai_score"] = 0
            scored_items.append(item)

    before = len(scored_items)
    passed = [i for i in scored_items if i.get("ai_score", 0) >= SCORE_THRESHOLD]
    print(f"   📊 AI 过滤: {before} → {len(passed)} (阈值={SCORE_THRESHOLD})")
    return passed


# ─── 主流程 ──────────────────────────────────────────────

# ─── 类型映射 ────────────────────────────────────────────

TYPE_FILE_MAP = {
    "video": "videos",
    "article": "articles",
    "tweet": "tweets",
    "book": "books",
    "paper": "papers",
    "podcast": "podcasts",
    "report": "reports",
    "blog": "blogs",
}


def _group_by_type(items):
    """按 type 分组"""
    groups = {}
    for item in items:
        itype = item.get("type", "other")
        groups.setdefault(itype, []).append(item)
    return groups


def filter_master(master_dir):
    """处理单个大师的所有日期文件，按类型输出"""
    master_name = master_dir.name
    print(f"\n📖 过滤: {master_name}")

    json_files = sorted(master_dir.glob("*.json"))
    if not json_files:
        print("   ⏭️  无数据文件")
        return None

    # 收集所有日期的数据
    all_items = []
    for json_file in json_files:
        items = json.loads(json_file.read_text())
        all_items.extend(items)

    if not all_items:
        print("   ⏭️  空数据")
        return None

    raw_count = len(all_items)

    # 第一级: 规则过滤
    all_items = rule_filter(all_items)
    rule_count = len(all_items)

    # 第二级: AI 打分
    all_items = score_batch(all_items)
    ai_count = len(all_items)

    # 按类型分组输出
    out_dir = FILTERED_DIR / master_name
    out_dir.mkdir(parents=True, exist_ok=True)

    groups = _group_by_type(all_items)
    type_stats = {}

    for itype, items in groups.items():
        filename = TYPE_FILE_MAP.get(itype, itype) + ".json"
        out_file = out_dir / filename
        out_file.write_text(json.dumps(items, ensure_ascii=False, indent=2))
        type_stats[itype] = len(items)

    # 打印摘要
    summary = " | ".join(f"{t}: {n}" for t, n in sorted(type_stats.items(), key=lambda x: -x[1]))
    print(f"   📊 {raw_count} → {rule_count} → {ai_count} 条")
    print(f"   📁 {summary}")

    return {
        "master": master_name,
        "raw": raw_count,
        "rule_pass": rule_count,
        "ai_pass": ai_count,
        "types": type_stats,
    }


def main():
    if not RAW_DIR.exists():
        print("❌ vault/raw/ 不存在，请先运行 collector.py")
        return

    META_DIR.mkdir(parents=True, exist_ok=True)
    FILTERED_DIR.mkdir(parents=True, exist_ok=True)

    has_key = bool(os.environ.get(AI_API_KEY_ENV))
    mode = "AI 过滤" if has_key else "仅规则过滤"
    print(f"🏛️ Masters Vault — AI 过滤器 ({mode})")
    print(f"   读取: {RAW_DIR.resolve()}")
    print(f"   输出: {FILTERED_DIR.resolve()}")

    all_stats = []
    for master_dir in sorted(RAW_DIR.iterdir()):
        if not master_dir.is_dir():
            continue
        stats = filter_master(master_dir)
        if stats:
            all_stats.append(stats)

    # 保存元数据
    total_raw = sum(s["raw"] for s in all_stats)
    total_filtered = sum(s["ai_pass"] for s in all_stats)
    filter_rate = f"{(1 - total_filtered / total_raw) * 100:.0f}%" if total_raw else "-"

    # 汇总各类型
    type_totals = {}
    for s in all_stats:
        for t, n in s.get("types", {}).items():
            type_totals[t] = type_totals.get(t, 0) + n

    meta = {
        "timestamp": datetime.now(BJ).isoformat(),
        "mode": mode,
        "total_raw": total_raw,
        "total_filtered": total_filtered,
        "filter_rate": filter_rate,
        "type_totals": dict(sorted(type_totals.items(), key=lambda x: -x[1])),
        "masters": all_stats,
    }
    meta_file = META_DIR / f"{datetime.now(BJ).strftime('%Y%m%d')}.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n✅ 过滤完成: {total_raw} → {total_filtered} ({filter_rate} 过滤率)")
    print(f"📁 元数据: {meta_file}")


if __name__ == "__main__":
    main()
