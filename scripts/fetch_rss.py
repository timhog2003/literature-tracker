#!/usr/bin/env python3
"""fetch_rss.py — 抓取用户在 Zotero 中订阅的 41 个 RSS，按期刊→领域映射归类。

数据源是用户 Zotero 库里的 RSS 订阅（data/feeds.json），不是 CrossRef 关键词搜索。
优势：
  - 期刊已经过用户人工筛选，质量有保障
  - 包含中文顶刊（经济研究、管理世界、卫生经济研究等）
  - 直接拉 RSS，无需认证

# ponytail: 单脚本、stdlib only；XML 用 ElementTree 解析 RSS 2.0 + Atom；
# 按 <link rel=alternate href> 找文章链接（多数 RSS 把全文链接放这里）。
"""
from __future__ import annotations
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

# 把 scripts/ 加到 path 以便 import translate
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ponytail: macOS python.org 装的 Python 3.12 证书链坏的（已知问题）。
try:
    import certifi  # type: ignore
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    bundled = Path(__file__).resolve().parent.parent / ".certs" / "cacert.pem"
    SSL_CTX = ssl.create_default_context(cafile=str(bundled)) if bundled.exists() \
              else ssl.create_default_context()

USER_AGENT = "literature-tracker/0.4 (mailto:your-email@example.com)"
FEEDS_PATH = Path(__file__).resolve().parent.parent / "data" / "feeds.json"
DATA_OUT   = Path(__file__).resolve().parent.parent / "data" / "papers.json"


# === CrossRef enrichment ==================================================

def _doi_from_url(url: str) -> str:
    """从 URL 抽 DOI（如 https://doi.org/10.123/abc → 10.123/abc）"""
    m = re.search(r"(10\.\d{4,}/[^\s?#/]+)", url)
    return m.group(1) if m else ""


def _pii_from_url(url: str) -> str:
    """ScienceDirect PII（pii/S…）"""
    m = re.search(r"/pii/(S[0-9A-Z]{10,})", url)
    return m.group(1) if m else ""


def _crossref_fetch_abstract(doi: str, timeout: int = 15) -> str:
    """从 CrossRef 拉单篇论文的完整 abstract。失败返回空串。"""
    if not doi:
        return ""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            data = json.loads(r.read())
        msg = data.get("message", {}) or {}
        return (msg.get("abstract") or "").strip()
    except Exception:
        return ""


def _crossref_lookup_by_altid(alt_id: str, id_type: str, timeout: int = 15) -> str:
    """按 PII / alternative-id 查 CrossRef，返回 abstract。"""
    url = f"https://api.crossref.org/works?filter=alternative-id:{urllib.parse.quote(alt_id)}&rows=1"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            data = json.loads(r.read())
        items = (data.get("message") or {}).get("items") or []
        if not items:
            return ""
        return (items[0].get("abstract") or "").strip()
    except Exception:
        return ""


def _semantic_scholar_fetch(doi: str, timeout: int = 15) -> str:
    """从 Semantic Scholar 拉真摘要（开放学术索引，含 ScienceDirect）。"""
    if not doi:
        return ""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='/:')}"
    try:
        req = urllib.request.Request(url + "?fields=abstract", headers={
            "User-Agent": USER_AGENT,
        })
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            data = json.loads(r.read())
        return (data.get("abstract") or "").strip()
    except Exception:
        return ""


def _fetch_abstract_for_paper(p: dict, timeout: int = 15) -> str:
    """按 DOI 优先：①CrossRef ②Semantic Scholar。"""
    doi = _doi_from_url(p.get("url", ""))
    if doi:
        txt = _crossref_fetch_abstract(doi, timeout)
        if txt:
            return txt
        # CrossRef 找不到时退到 Semantic Scholar
        return _semantic_scholar_fetch(doi, timeout)
    pii = _pii_from_url(p.get("url", ""))
    if pii:
        return _crossref_lookup_by_altid(pii, "PII", timeout)
    return ""


def enrich_abstracts(papers: list[dict], only_missing: bool = True) -> int:
    """对缺/短/疑似元数据 abstract 的论文，从 CrossRef 拉真摘要。"""
    n = 0
    tried = skipped_doi = skipped_pii = no_data = 0
    for p in papers:
        cur = (p.get("abstract") or "").strip()
        if only_missing and cur and len(cur) > 80 and not _looks_like_metadata(cur):
            continue
        url = p.get("url", "")
        doi = _doi_from_url(url)
        if not doi:
            pii = _pii_from_url(url)
            if not pii:
                skipped_doi += 1
                continue
        tried += 1
        abs_text = _fetch_abstract_for_paper(p)
        if not abs_text:
            no_data += 1
            continue
        clean = re.sub(r"<[^>]+>", "", unescape(abs_text)).strip()
        if clean and len(clean) > 80:
            p["abstract"] = clean[:1500]
            n += 1
        time.sleep(0.2)   # CrossRef 礼貌
    print(f"    [enrich] tried={tried}  skipped_no_id={skipped_doi}  no_crossref_data={no_data}  enriched={n}")
    return n

# 多源兼容命名空间
NS = {
    "atom":  "http://www.w3.org/2005/Atom",
    "dc":    "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


# --- HTTP ------------------------------------------------------------------

def http_get(url: str, retries: int = 2) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, */*",
    })
    last_err = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                return r.read()
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise last_err  # type: ignore[misc]


# --- RSS / Atom 解析 -------------------------------------------------------

def _text(node, tag: str, ns: str | None = None) -> str:
    el = node.find(tag, NS) if ns else node.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(s)).strip()


# ponytail: 多个期刊的 RSS description 字段是"元数据拼贴"而非真摘要；
# 这些特征词一出现就视为元数据。
_METADATA_MARKERS = (
    "Author(s):", "Publication date:", "Source:", "DOI:",
    "作者:", "发布日期:", "来源:", "摘要:", "关键字:",
    "Permanent link", "Full text:", "View HTML", "View PDF",
)


def _looks_like_metadata(text: str) -> bool:
    """返回 True 表示 description 是元数据堆砌，不是真摘要。"""
    if not text:
        return True
    if len(text) < 120:                    # 太短也不太可能是摘要
        return True
    hits = sum(1 for m in _METADATA_MARKERS if m in text)
    return hits >= 2                         # 至少 2 个特征词


def _parse_date(s: str) -> str:
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    except Exception:
        pass
    # 退路：直接抽前 10 个字符（YYYY-MM-DD）
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return m.group(0) if m else s[:10]


def parse_feed(xml_bytes: bytes, source_name: str) -> list[dict]:
    """返回 [{title, url, date, abstract, source}, ...]"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"  ! {source_name} 解析失败: {e}", file=sys.stderr)
        return []

    items: list[dict] = []

    def _emit(item, title_tag: str = "title", link_tag: str = "link",
              date_tag: str = "pubDate", date_ns: str | None = None,
              abstract_tag: str = "description", abstract_ns: str | None = None) -> None:
        title = _strip_html(_text(item, title_tag))
        link = _text(item, link_tag)
        if not link:
            for al in item.findall("atom:link", NS):
                href = al.attrib.get("href", "")
                rel  = al.attrib.get("rel", "alternate")
                if rel in ("alternate", ""):
                    link = href
                    break
        if not title or not link:
            return
        pub = _text(item, date_tag) if not date_ns else _text(item, date_tag, date_ns)
        desc = _text(item, abstract_tag) if not abstract_ns else _text(item, abstract_tag, abstract_ns)
        desc_clean = _strip_html(desc)[:600]
        # 元数据堆砌的 description 视为无摘要
        if _looks_like_metadata(desc_clean):
            desc_clean = ""
        items.append({
            "title":    title,
            "url":      link.strip(),
            "date":     _parse_date(pub),
            "abstract": desc_clean,
            "source":   source_name,
        })

    RSS1_NS = "{http://purl.org/rss/1.0/}"

    # RSS 2.0: <rss><channel><item>
    for item in root.iter("item"):
        _emit(item)

    # RSS 1.0 (RDF): <rdf:RDF><item>  -- Chicago Press 用这种
    if root.tag.endswith("RDF") and not items:
        for item in root.iter(RSS1_NS + "item"):
            _emit(item, title_tag=RSS1_NS + "title",
                  link_tag=RSS1_NS + "link",
                  date_tag="date", date_ns="dc",
                  abstract_tag=RSS1_NS + "description")

    # Atom: <feed><entry>
    if root.tag.endswith("feed") and not items:
        for entry in root.findall("atom:entry", NS):
            title = _strip_html(_text(entry, "atom:title", "atom"))
            link = ""
            for al in entry.findall("atom:link", NS):
                if al.attrib.get("rel", "alternate") in ("alternate", ""):
                    link = al.attrib.get("href", "")
                    break
            if not title or not link:
                continue
            pub = _text(entry, "atom:published", "atom") or _text(entry, "atom:updated", "atom")
            desc = _text(entry, "atom:summary", "atom") or _text(entry, "atom:content", "atom")
            items.append({
                "title":    title,
                "url":      link.strip(),
                "date":     _parse_date(pub),
                "abstract": _strip_html(desc)[:600],
                "source":   source_name,
            })

    return items


# --- 主流程 ---------------------------------------------------------------

def main() -> int:
    feeds_cfg = json.loads(FEEDS_PATH.read_text())
    feeds = feeds_cfg["feeds"]
    print(f"→ 抓取 {len(feeds)} 个 RSS 订阅")

    # ponytail: 读上一次的 papers.json，把 firstSeen 沿用下来，用于"新收录"
    prev_firstseen: dict[str, str] = {}
    is_first_run = True
    if DATA_OUT.exists():
        try:
            prev = json.loads(DATA_OUT.read_text())
            for arr in (prev.get("domains") or {}).values():
                for p in arr:
                    if p.get("url") and p.get("firstSeen"):
                        prev_firstseen[p["url"]] = p["firstSeen"]
            if prev_firstseen:
                is_first_run = False
            print(f"  · 沿用上批 {len(prev_firstseen)} 条 firstSeen")
        except Exception:
            pass

    seen: dict[str, dict] = {}   # url → paper
    today = date.today().isoformat()
    new_count = 0

    # ponytail: 启用 M3 时，新论文抓完立即做"分类+翻译"
    from translate import process_paper as m3_process
    m3_enabled = bool(os.environ.get("MINIMAX_API_KEY"))

    for f in feeds:
        name, url = f["name"], f["url"]
        try:
            xml_bytes = http_get(url)
            items = parse_feed(xml_bytes, name)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name}: {e}", file=sys.stderr)
            time.sleep(0.5)
            continue
        added = 0
        for it in items:
            if it["url"] in seen:
                continue
            it["id"] = it["url"]
            it["authors"] = []
            it["topics"] = []
            # firstSeen 规则
            if it["url"] in prev_firstseen:
                it["firstSeen"] = prev_firstseen[it["url"]]
            elif is_first_run:
                it["firstSeen"] = it.get("date") or today
            else:
                it["firstSeen"] = today
                new_count += 1
            # 新论文调 M3 分类+翻译（已有则跳过：之前批处理时已加）
            if m3_enabled and not it.get("domains"):
                try:
                    res = m3_process(it)
                    it["domains"]    = res["domains"]
                    it["titleZh"]    = res["titleZh"]
                    it["abstractZh"] = res["abstractZh"]
                except Exception as e:  # noqa: BLE001
                    print(f"  ! M3 处理失败 {it['url'][:60]}: {e}", file=sys.stderr)
                    it.setdefault("domains", [])
                    it.setdefault("titleZh", it["title"])
                    it.setdefault("abstractZh", "")
            seen[it["url"]] = it
            added += 1
        print(f"  · {name}: +{added}")
        time.sleep(0.35)

    # ponytail: 新抓的英文论文如果 abstract 短/是元数据，实时去 CrossRef 拉真摘要
    enriched = enrich_abstracts(list(seen.values()), only_missing=True)
    if enriched:
        print(f"  · CrossRef 补摘要 {enriched} 篇")

    # 按论文级 domains 归桶（每篇论文自带 domains 字段，由 M3 分类）
    classified: dict[str, list[dict]] = {
        "socialSecurity": [], "elderCare": [], "healthReform": [],
        "agingHealth": [], "socialWork": [],
    }
    for paper in seen.values():
        for d in (paper.get("domains") or []):
            if d in classified:
                classified[d].append(paper)

    # 时间倒序
    for cat in classified:
        classified[cat].sort(key=lambda x: x["date"], reverse=True)

    # 统计"新收录"（firstSeen == today 的论文，按期刊去重）
    new_by_journal: dict[str, int] = {}
    for p in seen.values():
        if p.get("firstSeen") == today:
            new_by_journal[p["source"]] = new_by_journal.get(p["source"], 0) + 1

    out = {
        "date":     today,
        "fetched":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "domains":  classified,
        "totals":   {k: len(v) for k, v in classified.items()},
        "feeds_ok": len([f for f in feeds if any(p["source"] == f["name"] for p in seen.values())]),
        "new_today":       new_count,
        "new_by_journal":  new_by_journal,
    }

    DATA_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✓ 写入 {DATA_OUT}")
    print(f"  期刊条目去重后总数：{len(seen)}")
    print(f"  归类：{out['totals']}")
    print(f"  本批新增（firstSeen==today）：{new_count}")
    if new_by_journal:
        for j, n in sorted(new_by_journal.items(), key=lambda x: -x[1])[:10]:
            print(f"    · {j}: +{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
