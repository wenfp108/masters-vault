"""
Masters Vault — 数据推送

将 vault/ 目录推送到 Masters-Council 仓库。
需要 GH_PAT 环境变量（有 Masters-Council 写权限的 token）。

用法:
    python push.py                # 推送 raw + filtered + meta
    python push.py --raw-only     # 只推送 raw (采集后立即推送)
    python push.py --filtered     # 只推送 filtered + meta (过滤后推送)
"""

import os, sys, subprocess, shutil, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJ = timezone(timedelta(hours=8))
VAULT_DIR = Path("vault")
REPO_URL = "https://github.com/wenfp108/Masters-Council.git"
CLONE_DIR = Path("/tmp/Masters-Council-push")


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"❌ 命令失败: {cmd}")
        print(f"   stderr: {r.stderr.strip()}")
        sys.exit(1)
    return r


def clone_repo():
    """克隆 Masters-Council"""
    if CLONE_DIR.exists():
        shutil.rmtree(CLONE_DIR)

    pat = os.environ.get("GH_PAT")
    if not pat:
        print("❌ 未设置 GH_PAT 环境变量")
        sys.exit(1)

    # 用 PAT 构建带认证的 URL
    auth_url = REPO_URL.replace("https://", f"https://x-access-token:{pat}@")
    run(f'git clone "{auth_url}" "{CLONE_DIR}"')
    print(f"✅ 克隆完成: {CLONE_DIR}")


def copy_vault(mode):
    """复制 vault 数据到克隆的仓库"""
    target = CLONE_DIR / "vault"
    target.mkdir(parents=True, exist_ok=True)

    copied = []

    if mode in ("all", "raw"):
        src = VAULT_DIR / "raw"
        if src.exists():
            dst = target / "raw"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied.append("raw")

        # 推送去重记录
        seen_src = VAULT_DIR / ".seen.json"
        if seen_src.exists():
            shutil.copy2(seen_src, target / ".seen.json")
            copied.append(".seen.json")

    if mode in ("all", "filtered"):
        src = VAULT_DIR / "filtered"
        if src.exists():
            dst = target / "filtered"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied.append("filtered")

        src = VAULT_DIR / "meta"
        if src.exists():
            dst = target / "meta"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            copied.append("meta")

    return copied


def commit_and_push(copied):
    """提交并推送"""
    run("git config user.name 'Vault Bot'", cwd=CLONE_DIR)
    run("git config user.email 'bot@wenfp108.com'", cwd=CLONE_DIR)

    run("git add vault/", cwd=CLONE_DIR)

    # 检查是否有变更
    r = run("git diff --cached --quiet", cwd=CLONE_DIR, check=False)
    if r.returncode == 0:
        print("💤 没有新数据，跳过推送")
        return False

    now = datetime.now(BJ).strftime("%Y-%m-%d %H:%M")
    msg = f"vault: {now} ({', '.join(copied)})"
    run(f'git commit -m "{msg}"', cwd=CLONE_DIR)

    # pull --rebase 防止冲突
    run("git pull origin main --rebase", cwd=CLONE_DIR, check=False)
    run("git push origin main", cwd=CLONE_DIR)

    print(f"✅ 推送完成: {msg}")
    return True


def main():
    # 解析参数
    mode = "all"
    if "--raw-only" in sys.argv:
        mode = "raw"
    elif "--filtered" in sys.argv:
        mode = "filtered"

    print(f"🏛️ Masters Vault — 数据推送 (模式: {mode})")

    if not VAULT_DIR.exists():
        print("❌ vault/ 目录不存在，请先运行 collector.py")
        sys.exit(1)

    clone_repo()
    copied = copy_vault(mode)

    if not copied:
        print("💤 没有数据需要推送")
        sys.exit(0)

    commit_and_push(copied)


if __name__ == "__main__":
    main()
