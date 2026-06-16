#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自動更新「專案狀態.md」中的狀態快照區塊。

設計理由（為什麼有這支程式）：
  專案狀態.md 過去用手打方式記錄「最新 commit / 有沒有未 commit / 版本號 /
  未發版項目」，這些 git 自己就知道，手抄一定會跟真實狀態漂移，所以每次都要
  有人提醒更新。這支程式把「機器知道的事」自動產生，由 post-commit hook 觸發，
  人就不必再記得。

  注意：專案狀態.md 在 git repo（tide-deploy/）的「上一層」，不在版本控制內，
  所以更新它不會動到 git 歷史，也不會造成「改了又沒 commit」的副作用。

安全原則：任何錯誤都不應該擋下 commit，找不到檔案就安靜結束（CI 環境沒有這份檔）。
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta

MARK_START = "<!-- AUTO-STATUS:START — 這段由 git hook 自動產生，請勿手改 -->"
MARK_END = "<!-- AUTO-STATUS:END -->"


def git(*args):
    """跑 git 指令，失敗回空字串（永不拋例外）。"""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def find_repo_root():
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return root or os.getcwd()
    except Exception:
        return os.getcwd()


def parse_changelog(repo_root):
    """回傳 (目前版本, 未發版項目清單)。"""
    path = os.path.join(repo_root, "CHANGELOG.md")
    version = "（未知）"
    unreleased = []
    if not os.path.exists(path):
        return version, unreleased
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return version, unreleased

    in_unreleased = False
    found_version = False
    for ln in lines:
        m = re.match(r"^##\s*\[([^\]]+)\]", ln)
        if m:
            tag = m.group(1).strip()
            if tag.lower() == "unreleased":
                in_unreleased = True
                continue
            in_unreleased = False
            if not found_version:
                version = "v" + tag
                found_version = True
            continue
        if in_unreleased:
            item = ln.strip()
            if item.startswith("- "):
                # 取粗體標題或前 40 字，當作摘要
                text = item[2:].strip()
                bold = re.match(r"\*\*(.+?)\*\*", text)
                summary = bold.group(1) if bold else text
                summary = re.sub(r"`([^`]*)`", r"\1", summary)
                if len(summary) > 46:
                    summary = summary[:46] + "…"
                unreleased.append(summary)
    return version, unreleased


def build_block():
    tz = timezone(timedelta(hours=8))  # 台北時間
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "（未知）"
    last_hash = git("log", "-1", "--format=%h")
    last_subj = git("log", "-1", "--format=%s")
    last_date = git("log", "-1", "--format=%ad", "--date=short")

    porcelain = git("status", "--porcelain")
    if porcelain:
        files = [l[3:] for l in porcelain.splitlines() if l[3:]]
        n = len(files)
        shown = "、".join(files[:5]) + ("…" if n > 5 else "")
        worktree = f"⚠️ 有 {n} 個未 commit 變動：{shown}"
    else:
        worktree = "✅ 乾淨（無未 commit 變動）"

    version, unreleased = parse_changelog(REPO_ROOT)

    lines = []
    lines.append(MARK_START)
    lines.append("")
    lines.append("## ⚡ 目前狀態快照（自動產生 · 勿手改）")
    lines.append("")
    lines.append(f"- 產生時間：{now}（台北）")
    lines.append(f"- 分支：`{branch}`")
    if last_hash:
        lines.append(f"- 最新 commit：`{last_hash}` {last_subj}（{last_date}）")
    lines.append(f"- 工作目錄：{worktree}")
    lines.append(f"- 目前版本：{version}")
    if unreleased:
        lines.append(f"- 未發版（Unreleased）：{len(unreleased)} 項")
        for u in unreleased:
            lines.append(f"  - {u}")
    else:
        lines.append("- 未發版（Unreleased）：無")
    lines.append(
        "- 同步狀態：以本次對話開場的 `git fetch` 為準"
        "（Actions 每交易日自動 commit data.json，本機可能落後，靜態文字無法保證準確）"
    )
    lines.append("")
    lines.append(MARK_END)
    return "\n".join(lines)


def main():
    global REPO_ROOT
    REPO_ROOT = find_repo_root()

    # 專案狀態.md 在 repo 上一層；CI 或其他環境沒有就跳過
    status_path = os.path.normpath(os.path.join(REPO_ROOT, "..", "專案狀態.md"))
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return 0
    if not os.path.exists(status_path):
        return 0

    try:
        block = build_block()
        with open(status_path, encoding="utf-8") as f:
            content = f.read()

        pattern = re.compile(
            re.escape(MARK_START) + r".*?" + re.escape(MARK_END),
            re.DOTALL,
        )
        if pattern.search(content):
            new_content = pattern.sub(block, content)
        else:
            # 沒有標記區就插在第一個「---」之後（介紹區塊後）
            parts = content.split("\n---\n", 1)
            if len(parts) == 2:
                new_content = parts[0] + "\n---\n\n" + block + "\n" + parts[1]
            else:
                new_content = block + "\n\n" + content

        if new_content != content:
            with open(status_path, "w", encoding="utf-8") as f:
                f.write(new_content)
    except Exception as e:
        # 永不擋下 commit
        sys.stderr.write(f"[gen_status_block] 略過：{e}\n")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
