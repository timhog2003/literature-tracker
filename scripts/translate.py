#!/usr/bin/env python3
"""translate.py — 用 MiniMax M3 对 papers.json 里的论文做 分类 + 翻译。

输出：每篇论文加 3 个字段
  - domains:      ["healthReform", "elderCare", ...]  // 论文级分类
  - titleZh:      "中文标题"
  - abstractZh:   "中文摘要（截断到 ~500 字）"

# ponytail: 一次 LLM 调用做三件事；失败时降级（不丢论文）；
# 串行调用（10 req/s 内稳），跑完会显示进度条。
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
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# === 配置（env 变量） ====================================================
API_KEY  = os.environ.get("MINIMAX_API_KEY", "")
BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1/text/chatcompletion_v2")
MODEL    = os.environ.get("MINIMAX_MODEL", "MiniMax-M3")
DOMAINS_DESC = {
    "socialSecurity": "社会保障（养老金、社保、失业保险、社会福利政策）",
    "elderCare":      "老年照护（长期照护、居家养老、护理人员、养老机构）",
    "healthReform":   "医疗改革（医疗保险、医疗政策、医院改革、药品定价）",
    "agingHealth":    "老龄健康（痴呆、寿命、死亡率、老年疾病、健康老龄化）",
    "socialWork":     "社会工作（个案管理、儿童福利、社区服务、公益组织）",
}
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "papers.json"

# === HTTP ===============================================================

try:
    import certifi  # type: ignore
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    bundled = ROOT / ".certs" / "cacert.pem"
    SSL_CTX = ssl.create_default_context(cafile=str(bundled)) if bundled.exists() \
              else ssl.create_default_context()

def call_m3(system: str, user: str, max_tokens: int = 2000, retries: int = 3) -> str:
    """调 MiniMax M3，返回 assistant content。M3 偶把答案放 reasoning_content，优先取。失败抛异常。"""
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(BASE_URL, data=body, method="POST", headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
                resp = json.loads(r.read())
            msg = resp["choices"][0]["message"]
            # ponytail: M3 有时把答案放 reasoning_content 而非 content
            content = (msg.get("content") or "").strip()
            if content:
                return content
            reasoning = (msg.get("reasoning_content") or "").strip()
            if reasoning:
                return reasoning
            return ""  # 两者都空
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError) as e:
            last = e
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"M3 调用失败: {last}")

# === Prompt ============================================================

SYSTEM = """你是学术论文策展助手。根据用户给定的论文标题与摘要，完成三件事并以严格 JSON 返回：
1. 判断这篇论文属于下列哪些领域（可多个，可空数组表示不属于任何领域）：
""" + "\n".join(f"   - {k}: {v}" for k, v in DOMAINS_DESC.items()) + """

2. 把标题翻译成中文（学术风格、简洁）。若已是中文则原样返回。
3. 把摘要翻译成中文（保留学术术语与数字）。若已是中文则原样返回。若摘要为空则 abstractZh 设为空字符串。

返回格式（严格 JSON，不要任何额外文本、代码块标记或解释）：
{"domains":["..."],"titleZh":"...","abstractZh":"..."}"""

USER_TMPL = """标题：{title}

摘要：{abstract}"""

def extract_json(text: str) -> dict | None:
    """从模型回复里抠 JSON。容忍 ```json ...``` 包裹和前后杂质。"""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

# === 主流程 ============================================================

def process_paper(p: dict) -> dict:
    """调用 M3，返回分类 + 翻译；失败返回兜底（保留原文）。"""
    title = (p.get("title") or "").strip()
    abstract = (p.get("abstract") or "").strip()[:1500]
    if not title:
        return {"domains": [], "titleZh": "", "abstractZh": ""}

    try:
        out = call_m3(SYSTEM, USER_TMPL.format(title=title, abstract=abstract))
    except Exception as e:  # noqa: BLE001
        print(f"  ! M3 调用失败: {e}", file=sys.stderr)
        return {"domains": [], "titleZh": title, "abstractZh": ""}

    data = extract_json(out)
    if not data:
        return {"domains": [], "titleZh": title, "abstractZh": ""}

    domains = data.get("domains") or []
    domains = [d for d in domains if d in DOMAINS_DESC]
    return {
        "domains":    domains,
        "titleZh":   (data.get("titleZh")    or "").strip() or title,
        "abstractZh":(data.get("abstractZh") or "").strip(),
    }

def main() -> int:
    if not API_KEY:
        print("错误：未设置 MINIMAX_API_KEY 环境变量", file=sys.stderr)
        return 1

    data = json.loads(DATA.read_text())
    domains_map: dict[str, list] = data.get("domains", {})
    all_papers: list[dict] = []
    for arr in domains_map.values():
        all_papers.extend(arr)
    # 去重（同一篇论文可能跨多个领域）
    seen = set()
    unique = []
    for p in all_papers:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        unique.append(p)

    # 已处理的：domains 字段存在且非空（视为已分类）
    todo = [p for p in unique if not p.get("domains")]
    print(f"→ 共 {len(unique)} 篇，{len(todo)} 篇待处理")

    if not todo:
        print("✓ 全部已处理")
        return 0

    # 限制：避免一次性跑太多（按需通过 N 环境变量调整）
    cap = int(os.environ.get("MAX_PROCESS", "0")) or len(todo)
    todo = todo[:cap]
    print(f"→ 本次处理 {len(todo)} 篇")

    # ponytail: 并发 N 路，加快 batch 速度
    workers = int(os.environ.get("MAX_WORKERS", "5"))
    print(f"→ 并发 {workers} 路")

    # 在闭包内修改 dict 需同步；用 list 索引代替
    pending = list(enumerate(todo))
    done_lock_path = DATA  # 只是引用
    t0 = time.time()

    def work(item):
        idx, p = item
        result = process_paper(p)
        return idx, p, result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(work, it) for it in pending]
        for i, fut in enumerate(as_completed(futs), 1):
            idx, p, result = fut.result()
            p["domains"]    = result["domains"]
            p["titleZh"]    = result["titleZh"]
            p["abstractZh"] = result["abstractZh"]
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate if rate > 0 else 0
            pct = (i / len(todo)) * 100
            print(f"  [{i:4}/{len(todo)}] {pct:5.1f}%  {elapsed:5.0f}s  ETA {eta:4.0f}s  ✓  {p['title'][:50]}")
            if i % 10 == 0 or i == len(todo):
                DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✓ 处理 {done} 篇，已写入 {DATA}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
