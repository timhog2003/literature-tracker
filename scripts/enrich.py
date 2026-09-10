#!/usr/bin/env python3
"""enrich.py — 用 CrossRef 给已有论文补真摘要，再调 M3 重译。

适用：papers.json 里 abstract 是元数据堆砌或缺失的论文。
环境变量：
  MINIMAX_API_KEY  启用 M3 翻译；不设则只补 CrossRef 摘要，不翻译
  CROSSREF_ONLY=1  只补 CrossRef 摘要，不调 M3
  MAX_PROCESS=N    限制本次处理数量（0 = 全部）
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

# 把 scripts/ 加到 path 以便 import 同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_rss import enrich_abstracts, DATA_OUT  # noqa: E402

import json  # noqa: E402


def is_chinese(s: str) -> bool:
    return sum(1 for c in s if "一" <= c <= "鿿") > len(s) * 0.3


crossref_only = bool(os.environ.get("CROSSREF_ONLY"))
max_process = int(os.environ.get("MAX_PROCESS", "0"))

# 1) CrossRef 补摘要
data = json.loads(DATA_OUT.read_text())
all_papers = []
for arr in (data.get("domains") or {}).values():
    all_papers.extend(arr)

# 去重
seen = set()
unique = []
for p in all_papers:
    if p["url"] in seen:
        continue
    seen.add(p["url"])
    unique.append(p)

todo = [p for p in unique if not (p.get("abstract", "").strip() and len(p.get("abstract", "")) > 80 and "Author(s):" not in p.get("abstract", ""))]
print(f"→ 共 {len(unique)} 篇，{len(todo)} 篇需要补 CrossRef 摘要")
if max_process:
    todo = todo[:max_process]
    print(f"→ 本次处理 {len(todo)} 篇")

n = enrich_abstracts(todo, only_missing=True)
print(f"✓ CrossRef 补摘要 {n} 篇")

if not crossref_only and os.environ.get("MINIMAX_API_KEY"):
    # 2) M3 重新翻译（限英文 + abstract 改变了的）
    from translate import process_paper
    cnt = 0
    for p in todo:
        # 跳过中文论文（M3 中文→中文无意义）
        if is_chinese(p.get("title", "")):
            continue
        # 跳过 abstract 没变的
        # 简化：只要 abstract 存在就重译
        try:
            res = process_paper(p)
            p["domains"]    = res["domains"]
            p["titleZh"]    = res["titleZh"]
            p["abstractZh"] = res["abstractZh"]
            cnt += 1
            if cnt % 20 == 0:
                print(f"  已翻译 {cnt} 篇")
        except Exception as e:
            print(f"  ! 翻译失败: {e}", file=sys.stderr)
    print(f"✓ M3 重新翻译 {cnt} 篇")
else:
    print("(跳过 M3 翻译)")

DATA_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"\n✓ 已写入 {DATA_OUT}")
