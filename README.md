# 文献追踪 · 社会保障 / 老年照护 / 老龄健康

每日聚合学术产出，**由 MiniMax M3 智能分类 + 翻译**。纯静态站，无后端。

## 核心设计：论文级智能分类

不是"整刊打标签"，而是 **每篇论文单独由 M3 决定**：

```
RSS 抓取 (41 个期刊) → M3 分类 + 翻译 → papers.json
   ↓
前端按 paper.domains 过滤显示
```

例如 *Journal of Health Economics* 里的论文：
- "DRG 支付对医院行为的影响" → 医疗改革 ✓
- "美国阿尔茨海默的医保支出" → 老龄健康 ✓
- "药品专利期博弈" → 都不属于，归入"全部"但不出现在领域 tab

---

## 目录结构

```
.
├── index.html                       # 单页入口（6 个 tab）
├── static/
│   ├── css/                         # 主题 + 组件样式
│   └── js/                          # app-core / app-render / app-init
├── data/
│   ├── feeds.json                   # 41 个 RSS（name + url）
│   └── papers.json                  # fetch + M3 处理后的论文数据
├── scripts/
│   ├── fetch_rss.py                 # 抓 41 个 RSS → papers.json
│   └── translate.py                 # 调 M3 分类 + 翻译已有论文
├── .certs/cacert.pem                # macOS python.org SSL
└── .github/workflows/fetch.yml      # 每日 cron（需配 M3 secret）
```

---

## 首次配置

### 1. 配 MiniMax M3 API key（本地）

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，填入你的 key
echo 'MINIMAX_API_KEY=sk-cp-你的-key' > .env
echo 'MAX_WORKERS=8' >> .env
```

`.env` 在 `.gitignore` 里，**不会提交**。

### 2. 首次跑：分类 + 翻译全部 1051 篇

```bash
source .env
python3 scripts/translate.py
# 约 8 分钟（8 并发）。每 10 篇保存一次
```

### 3. 跑 fetch（每天 cron 做的事）

```bash
python3 scripts/fetch_rss.py    # 抓 RSS + 给新论文调 M3（约 1-3 分钟）
```

### 4. 起本地服务

```bash
python3 -m http.server 8000
# 浏览器打开 http://localhost:8000
```

---

## GitHub Actions 部署

在 repo **Settings → Secrets and variables → Actions** 加：
- `MINIMAX_API_KEY` = 你的 key

`.github/workflows/fetch.yml` 会每天 UTC 01:30 自动跑 fetch + M3 处理。

---

## Tab 结构

| Tab | 用途 |
|---|---|
| 期刊追踪 | 全部论文（按期刊 sidebar 过滤）|
| 学者追踪 | 占位，等你给 ORCID 列表 |
| 社会保障 / 医疗改革 / 老年照护 / 社会工作 | **只显示 M3 判定属于该领域的论文** |

每个 tab 内部：
- **Sidebar 期刊目录**：点击过滤该期刊
- **view-control 切换**：各刊最新（每刊前 5）/ 新收录（firstSeen == today）
- **点论文卡片 → 内联展开**：
  - 中文标题为主，英文原标题 italic 小字
  - 双语摘要（中文为主，zh-prose 衬线）
  - 右侧 sticky 元数据栏：刊名 / 发表 / 领域 / 原文链接
  - 「收起」按钮

---

## 调 M3 行为

`scripts/translate.py` 默认 prompt：

```
你判断这篇论文是否属于以下 5 个领域：
- socialSecurity: 养老金、社保、失业保险
- elderCare:      长期照护、护理人员、养老机构
- healthReform:   医疗保险、医疗政策、医院改革
- agingHealth:    痴呆、寿命、死亡率、健康老龄化
- socialWork:     个案管理、儿童福利、社区服务

返回 JSON: {domains: [...], titleZh: "...", abstractZh: "..."}
```

可调：
- `MINIMAX_MODEL` 改模型
- `MINIMAX_BASE_URL` 改端点
- `MAX_WORKERS` 改并发
- `MAX_PROCESS` 限制单次处理数量（默认 0 = 全部）

---

## 下一步

- [ ] 学者追踪（ORCID 列表）
- [ ] 学者主页 RSS 抓取
- [ ] NBER 工作论文（CrossRef 或 NBER 直接抓）
- [ ] 邮件订阅（Buttondown / Resend）
