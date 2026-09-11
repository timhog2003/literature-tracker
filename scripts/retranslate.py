#!/usr/bin/env python3
"""retranslate.py — 一次性：找到英文论文 + 有 abstract 但缺 abstractZh，调 M3 重译。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate import process_paper  # noqa
from fetch_rss import DATA_OUT  # noqa

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

def is_chinese(s):
    return sum(1 for c in s if "一" <= c <= "鿿") > len(s) * 0.3

todo = [p for p in unique if (
    p.get("titleZh") and not is_chinese(p.get("title",""))
    and p.get("abstract", "").strip() and len(p["abstract"]) > 80
    and not p.get("abstractZh", "").strip()
)]
print(f"待重译: {len(todo)} 篇")

# 用并发 4 路加速
from concurrent.futures import ThreadPoolExecutor, as_completed

def work(p):
    try:
        res = process_paper(p)
        return p["url"], res, None
    except Exception as e:
        return p["url"], None, str(e)

ok = fail = 0
with ThreadPoolExecutor(max_workers=4) as pool:
    futs = {pool.submit(work, p): p for p in todo}
    for i, fut in enumerate(as_completed(futs), 1):
        url, res, err = fut.result()
        if err or not res:
            fail += 1
            if fail < 5: print(f"  ! 失败: {err}")
        else:
            p = futs[fut]
            p["domains"]    = res["domains"]
            p["titleZh"]    = res["titleZh"]
            p["abstractZh"] = res["abstractZh"]
            ok += 1
        if i % 20 == 0 or i == len(todo):
            DATA_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            print(f"  [{i}/{len(todo)}]  ok={ok}  fail={fail}")

DATA_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"\n✓ 完成 ok={ok} fail={fail}")
