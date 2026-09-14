#!/usr/bin/env python3
"""fetch_crossref.py — 每天拉 29 个 SSCI/SCI 期刊的最新论文（主数据源）。

策略：按 ISSN 列表 + 7 天窗 + has-abstract 过滤，分页用 cursor。
   - 摘要缺失的论文：fallback 到 RSS（fetch_rss.py 跑了再补）
   - 分类 + 翻译留给 M3
"""
from __future__ import annotations
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import certifi  # type: ignore
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    bundled = ROOT / ".certs" / "cacert.pem"
    SSL_CTX = ssl.create_default_context(cafile=str(bundled)) if bundled.exists() \
              else ssl.create_default_context()

USER_AGENT = "literature-tracker/1.0 (mailto:tracker@example.com)"

# === 配置 =================================================================

JOURNALS_PATH = ROOT / "data" / "journals.json"
FEEDS_PATH    = ROOT / "data" / "feeds.json"
DATA_PATH     = ROOT / "data" / "papers.json"

# 每天拉过去 7 天
WINDOW_DAYS = 7
# 每次请求最多 1000（CrossRef 单次上限）
ROWS_PER_PAGE = 500
# polite pool 邮箱（换成你的）
POLITE_MAILTO = os.environ.get("CROSSREF_MAILTO", "tracker@example.com")


# === HTTP =================================================================

def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


# === CrossRef 拉取 =========================================================

def load_journals() -> list[dict]:
    cfg = json.loads(JOURNALS_PATH.read_text())
    return cfg.get("crossref_issns", [])


def crossref_query(issn: str, from_date: str, to_date: str, cursor: str = "*") -> dict:
    """单 ISSN 单次请求，返回 parsed JSON。"""
    params = {
        "filter": f"issn:{issn},from-pub-date:{from_date},until-pub-date:{to_date}",
        "rows": str(ROWS_PER_PAGE),
        "select": "DOI,title,author,abstract,published-print,published-online,issued,container-title,link,URL,subject",
        "cursor": cursor,
        "mailto": POLITE_MAILTO,
    }
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
    return json.loads(http_get(url))


def fetch_issn(journal: dict, from_date: str, to_date: str) -> list[dict]:
    """拉一个 ISSN 全部新论文。返回规范化的 paper dict 列表。"""
    issn = journal["issn"]
    out: list[dict] = []
    cursor = "*"
    pages = 0
    while True:
        try:
            data = crossref_query(issn, from_date, to_date, cursor)
        except Exception as e:
            print(f"  ! {issn} 失败: {type(e).__name__}: {str(e)[:60]}", flush=True)
            return out
        msg = data.get("message", {}) or {}
        items = msg.get("items", []) or []
        for w in items:
            paper = _normalize(w, journal, issn)
            if paper:
                out.append(paper)
        pages += 1
        next_cursor = msg.get("next-cursor")
        total = msg.get("total-results", 0)
        if not next_cursor or next_cursor == cursor or len(items) < ROWS_PER_PAGE:
            break
        cursor = next_cursor
        if pages > 5:  # 安全阀，单个期刊最多 5 页（5000 篇）
            break
    return out


def _normalize(item: dict, journal: dict, issn: str) -> dict | None:
    """CrossRef work item → 我们内部的 paper dict。"""
    doi = (item.get("DOI") or "").strip()
    if not doi:
        return None
    title_list = item.get("title") or []
    title = (title_list[0] if title_list else "").strip()
    if not title:
        return None

    # 作者
    authors = []
    for a in item.get("author") or []:
        n = " ".join(x for x in [a.get("given"), a.get("family")] if x)
        if n:
            authors.append(n)

    # 摘要（JATS XML，去标签）
    abstract_raw = (item.get("abstract") or "").strip()
    if abstract_raw:
        abstract = re.sub(r"<[^>]+>", "", abstract_raw.replace("\n", " ")).strip()
    else:
        abstract = ""

    # 日期
    pub = (item.get("published-print") or item.get("published-online") or item.get("issued") or {})
    parts = ((pub.get("date-parts") or [[]]))[0]
    if parts:
        y, m, d = (parts + [1, 1, 1])[:3]
        date_str = f"{y:04d}-{m:02d}-{d:02d}"
    else:
        date_str = ""

    # 期刊名
    container = (item.get("container-title") or [""])[0]
    # 链接
    url = item.get("URL") or f"https://doi.org/{doi}"
    # 学科（用于后续分类）
    subjects = item.get("subject") or []

    return {
        "id":       f"doi:{doi}",
        "doi":      doi,
        "url":      url,
        "title":    title,
        "authors":  authors,
        "abstract": abstract,
        "source":   container or journal.get("journal", ""),
        "issn":     issn,
        "date":     date_str,
        "subjects": subjects,
        "domains":  journal.get("domains", []),
        "firstSeen": date.today().isoformat(),
        "fetched_from": "crossref",
    }


# === 合并 / 写入 ===========================================================

def load_existing() -> dict[str, dict]:
    """读 papers.json，按 URL 建索引。同时把 domains 字段补上（很多老 paper 没有该字段，靠 list 结构分类）。"""
    if not DATA_PATH.exists():
        return {}
    data = json.loads(DATA_PATH.read_text())
    by_url: dict[str, dict] = {}
    for cat, arr in (data.get("domains") or {}).items():
        for p in arr:
            url = p.get("url")
            if not url:
                continue
            if url not in by_url:
                by_url[url] = dict(p)   # 拷贝避免污染原 list
                by_url[url].setdefault("domains", [])
            # 合并该 URL 的所有 domain
            domains = by_url[url].setdefault("domains", [])
            if cat not in domains:
                domains.append(cat)
    return by_url


def save_merged(by_url: dict[str, dict]) -> None:
    """把 by_url 重新按 5 个领域分桶 + 输出元数据，写回 papers.json。"""
    classified = {k: [] for k in ["socialSecurity", "elderCare", "healthReform", "agingHealth", "socialWork"]}
    for p in by_url.values():
        for d in p.get("domains") or []:
            if d in classified:
                classified[d].append(p)
    for cat in classified:
        classified[cat].sort(key=lambda x: x.get("date", ""), reverse=True)

    today = date.today().isoformat()
    out = {
        "date":     today,
        "fetched":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "domains":  classified,
        "totals":   {k: len(v) for k, v in classified.items()},
        "feeds_ok": len([f for f in (json.loads(FEEDS_PATH.read_text()) if FEEDS_PATH.exists() else {}).get("feeds", [])]),
    }
    DATA_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))


# === Main ==================================================================

def main() -> int:
    journals = load_journals()
    today = date.today()
    from_date = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    to_date   = today.isoformat()
    print(f"→ CrossRef 主拉取：{len(journals)} ISSN，{from_date} 至 {to_date}", flush=True)

    existing = load_existing()
    print(f"  已有 {len(existing)} 条历史", flush=True)

    new_count = 0
    upd_count = 0
    for j in journals:
        issn = j["issn"]
        try:
            papers = fetch_issn(j, from_date, to_date)
        except Exception as e:
            print(f"  ! {issn} 异常: {e}", flush=True)
            continue
        for p in papers:
            url = p["url"]
            if url in existing:
                # 更新：补全 abstract / authors
                cur = existing[url]
                changed = False
                for k in ("abstract", "authors", "title"):
                    if not cur.get(k) and p.get(k):
                        cur[k] = p[k]
                        changed = True
                if changed:
                    upd_count += 1
            else:
                existing[url] = p
                new_count += 1
        print(f"  · {j['journal']:42s}  +{len(papers)}", flush=True)
        time.sleep(0.3)   # 礼貌限流

    save_merged(existing)
    print(f"\n✓ 新增 {new_count}，更新 {upd_count}", flush=True)
    print(f"  现在 {len(existing)} 条唯一记录", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
