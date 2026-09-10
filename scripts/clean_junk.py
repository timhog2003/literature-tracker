#!/usr/bin/env python3
"""clean_junk.py — 清理 RSS 来源里的元数据堆砌型"abstract"。

ScienceDirect / OUP / 部分 Wiley 的 RSS description 字段是元数据拼接，不是真摘要。
这些会被 M3 翻译成"作者：xxx；来源：xxx；发表：xxx"完全没用的内容。
本脚本把它们统一清空，让弹窗只显示标题（已经够用）。
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_rss import _looks_like_metadata, DATA_OUT  # noqa: E402
import json  # noqa: E402

data = json.loads(DATA_OUT.read_text())
all_papers = []
for arr in (data.get("domains") or {}).values():
    all_papers.extend(arr)
seen = set()
unique = []
for p in all_papers:
    if p["url"] in seen:
        continue
    seen.add(p["url"])
    unique.append(p)

cleaned = 0
for p in unique:
    cur = (p.get("abstract") or "").strip()
    if not cur:
        continue
    if _looks_like_metadata(cur):
        p["abstract"] = ""
        # 如果没有真摘要，且已有 M3 翻译，也清掉
        p.pop("abstractZh", None)
        cleaned += 1

DATA_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"✓ 清空 {cleaned} 篇元数据堆砌型 abstract")
print(f"  共 {len(unique)} 篇，{sum(1 for p in unique if p.get('abstract','').strip() and not _looks_like_metadata(p.get('abstract','')))} 篇有真摘要")
