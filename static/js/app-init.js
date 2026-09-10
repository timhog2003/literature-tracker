// app-init.js — 启动：拉数据 + 按 tab 渲染
// ponytail: 单文件，所有逻辑在一个 main() 里

const DOMAIN_KEYS = ["socialSecurity", "elderCare", "healthReform", "agingHealth", "socialWork"];
const DOMAIN_TAB = {
  socialSecurity: "social-security",
  elderCare:      "elder-care",
  healthReform:   "health-reform",
  agingHealth:    "aging-health",
  socialWork:     "social-work",
};
const TAB_DOMAIN = Object.fromEntries(Object.entries(DOMAIN_TAB).map(([k, v]) => [v, k]));

const TAB_LABEL = {
  journals: "期刊追踪",
  scholars: "学者追踪",
  "social-security": "社会保障",
  "health-reform":   "医疗改革",
  "elder-care":      "老年照护",
  "social-work":     "社会工作",
};

// 每个 tab 独立状态
const STATE_TAB = {};
function tabState(tab) {
  if (!(tab in STATE_TAB)) STATE_TAB[tab] = { viewMode: "newest", selectedJournal: "__all__", query: "" };
  return STATE_TAB[tab];
}

async function loadJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(`HTTP ${r.status} on ${path}`);
  return r.json();
}

// --- helpers --------------------------------------------------------------

function isChinese(s) { return /[一-龿]/.test(s || ""); }
function escapeHtml(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                         .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}
const escapeAttr = escapeHtml;
function paperHTML(p, num)       { return window.RENDER.paperHTML(p, num); }
function applyFilter(items, q)   { return window.RENDER.applyFilter(items, q); }

// --- 期刊目录 sidebar ----------------------------------------------------

function renderSidebar(journals, papersByJournal, selectedKey) {
  const totalPapers = Object.values(papersByJournal).reduce((n, arr) => n + arr.length, 0);
  const items = [];

  items.push(`
    <div class="jlist-item ${selectedKey === "__all__" ? "active" : ""}" data-key="__all__">
      <span class="jlist-num">·</span>
      <span class="jlist-name" style="font-weight:600;">全部期刊</span>
      <span class="jlist-count">${totalPapers} 篇</span>
    </div>
  `);

  journals.forEach((j, i) => {
    const ps = papersByJournal[j.name] || [];
    if (!ps.length) return;
    const active = selectedKey === j.name ? " active" : "";
    const zh = isChinese(j.name) ? " zh" : "";
    items.push(`
      <div class="jlist-item${active}" data-key="${escapeAttr(j.name)}">
        <span class="jlist-num">${String(i + 1).padStart(2, "0")}</span>
        <span class="jlist-name${zh}">${escapeHtml(j.name)}</span>
        <span class="jlist-count">${ps.length}</span>
      </div>
    `);
  });

  return `
    <aside class="sidebar">
      <div class="sidebar-head">
        <span class="sidebar-title">期刊目录</span>
        <span class="sidebar-total">${journals.length} 本</span>
      </div>
      <nav class="jlist">${items.join("")}</nav>
    </aside>
  `;
}

// --- 视图控制（segmented pills） -----------------------------------------

function renderViewControl(state, newCount, totalCount) {
  return `
    <div class="view-control">
      <div class="seg-pills">
        <button class="seg-pill ${state.viewMode === "newest" ? "active" : ""}" data-mode="newest">
          各刊最新 <span class="seg-n">${totalCount}</span>
        </button>
        <button class="seg-pill ${state.viewMode === "batch" ? "active" : ""}" data-mode="batch">
          新收录 <span class="seg-n">${newCount}</span>
        </button>
      </div>
    </div>
  `;
}

function renderSubTabs(journals, selectedJournal) {
  if (!journals.length) return "";
  const total = journals.reduce((n, j) => n + j.count, 0);
  const tabs = [`<button class="sub-tab ${selectedJournal === "__all__" ? "active" : ""}" data-key="__all__">全部(${total})</button>`];
  for (const j of journals) {
    const zh = isChinese(j.name) ? " zh" : "";
    tabs.push(`<button class="sub-tab ${selectedJournal === j.name ? "active" : ""}" data-key="${escapeAttr(j.name)}">
      <span class="${zh}">${escapeHtml(j.name)}</span>(${j.count})
    </button>`);
  }
  return `<div class="sub-tabs">${tabs.join("")}</div>`;
}

// --- 主区论文列表 -------------------------------------------------------

function renderMain(journalName, papers, q) {
  const filtered = q ? applyFilter(papers, q) : papers;
  const isAll = journalName === "__all__";
  const zhTitle = !isAll && isChinese(journalName);
  const titleHTML = isAll
    ? `<h2 class="main-title">全部期刊</h2>`
    : `<h2 class="main-title${zhTitle ? " zh" : ""}">● ${escapeHtml(journalName)}</h2>`;
  const body = filtered.length
    ? filtered.map((p, i) => paperHTML(p, i + 1)).join("")
    : `<div class="main-empty">${q ? "无匹配搜索结果" : "该期刊暂无论文"}</div>`;
  return `
    <section class="main">
      <div class="main-head">${titleHTML}<span class="main-meta">${filtered.length} 篇</span></div>
      <div class="main-body">${body}</div>
    </section>`;
}

function renderScholars() {
  return `<div class="scholars-empty">
    <h2>学者追踪 · 待接入</h2>
    <p>在 <code>data/feeds.json</code> 加 <code>scholars: [{name, orcid}]</code>，<br>写 <code>fetch_scholars.py</code> 拉 ORCID 公开 API 即可。</p>
  </div>`;
}

// --- 数据派生 ----------------------------------------------------------

// ponytail: 数据按"论文级 domains"分类，而非期刊级
// 1051 篇论文中，符合某领域的才进该 tab；其他归"全部"

function allUniquePapers(papersByDomain) {
  const seen = new Set();
  const out = [];
  for (const arr of Object.values(papersByDomain)) {
    for (const p of arr) {
      if (seen.has(p.url)) continue;
      seen.add(p.url);
      out.push(p);
    }
  }
  return out;
}

function papersForTab(tabKey, allPapers) {
  if (tabKey === "journals") {
    return [...allPapers].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  }
  const dom = TAB_DOMAIN[tabKey];
  if (!dom) return [];
  return allPapers.filter(p => (p.domains || []).includes(dom))
                  .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
}

function journalsForTab(tabKey, allPapers, feeds) {
  if (tabKey === "journals") {
    // 期刊追踪：所有 feeds
    return feeds;
  }
  // 领域 tab：只显示有 ≥1 篇论文的期刊
  const dom = TAB_DOMAIN[tabKey];
  if (!dom) return [];
  const journalsWithPapers = new Set(
    allPapers.filter(p => (p.domains || []).includes(dom)).map(p => p.source)
  );
  return feeds.filter(f => journalsWithPapers.has(f.name));
}

function filterByFirstSeen(papers, today) {
  return papers.filter(p => p.firstSeen === today);
}

function topNPerJournal(papers, n = 5) {
  const byJ = buildPapersByJournal(papers);
  const out = [];
  for (const arr of Object.values(byJ)) out.push(...arr.slice(0, n));
  out.sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return out;
}

function buildPapersByJournal(papers) {
  const out = {};
  for (const p of papers) (out[p.source] ||= []).push(p);
  for (const k in out) out[k].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  return out;
}

// --- 论文卡片：点开 → 弹窗（yandu 风格） -------------------------------

function paperFromEl(el) {
  return {
    title:      el.dataset.title      || "",
    titleZh:    el.dataset.titleZh    || "",
    source:     el.dataset.source     || "",
    date:       el.dataset.date       || "",
    abstract:   el.dataset.abstract   || "",
    abstractZh: el.dataset.abstractZh || "",
    url:        el.dataset.url        || "",
    domain:     (el.dataset.domain     || "").split(",").filter(Boolean)[0] || "",
  };
}

function bindPaperClicks(section) {
  section.querySelectorAll(".paper").forEach(el => {
    el.addEventListener("click", (e) => {
      // 内部链接不触发展开
      if (e.target.closest("a")) return;
      openPaperModal(el);
    });
  });
}

function openPaperModal(el) {
  const p = paperFromEl(el);
  const modal = document.getElementById("paperModal");
  const titleZh = p.titleZh || p.title;
  const hasZhTitle = p.titleZh && p.titleZh !== p.title;
  const hasEnTitle = p.title && p.title !== p.titleZh;

  document.getElementById("modalKicker").textContent = p.source;
  // 主标题 = 中文（若有），链接到原文
  const titleEl = document.getElementById("modalTitle");
  titleEl.innerHTML = p.url
    ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(titleZh)}</a>`
    : esc(titleZh);
  // 副标题 = 英文
  const enEl = document.getElementById("modalEn");
  enEl.textContent = hasEnTitle ? p.title : "";
  enEl.style.display = hasEnTitle ? "" : "none";

  // 摘要：中文期刊只显示中文，英文期刊双语
  const isEN = !isChinese(p.title);
  const absZh = p.abstractZh || (isEN ? "" : (p.abstract || ""));
  const absEn = isEN ? (p.abstract || "") : "";
  const secZh = document.getElementById("modalSecZh");
  const secEn = document.getElementById("modalSecEn");
  document.getElementById("modalAbsZh").textContent = absZh;
  document.getElementById("modalAbsEn").textContent = absEn;
  secZh.style.display = absZh ? "" : "none";
  secEn.style.display = (isEN && absEn) ? "" : "none";

  // 右侧栏
  document.getElementById("modalJournal").textContent = p.source;
  document.getElementById("modalDate").textContent = p.date || "—";
  document.getElementById("modalDomain").textContent = p.domain || "—";
  const link = document.getElementById("modalLink");
  if (p.url) {
    link.href = p.url;
    link.style.display = "";
  } else {
    link.style.display = "none";
  }

  modal.hidden = false;
  modal.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  setTimeout(() => modal.querySelector(".modal-close")?.focus(), 50);
}

function closePaperModal() {
  const modal = document.getElementById("paperModal");
  modal.hidden = true;
  modal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

function bindModalClose() {
  const modal = document.getElementById("paperModal");
  modal.querySelectorAll("[data-close]").forEach(el => {
    el.addEventListener("click", closePaperModal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closePaperModal();
  });
}

function esc(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

// --- 主流程 -------------------------------------------------------------

async function main() {
  let papersData, feedsData;
  try {
    [papersData, feedsData] = await Promise.all([
      loadJSON("data/papers.json"),
      loadJSON("data/feeds.json"),
    ]);
  } catch (e) {
    document.getElementById("loading").textContent = `加载失败：${e.message}`;
    return;
  }

  const feeds = feedsData.feeds || [];
  const today = papersData.date || new Date().toISOString().slice(0, 10);

  const papersByDomain = {};
  for (const k of DOMAIN_KEYS) papersByDomain[k] = [];
  for (const [k, arr] of Object.entries(papersData.domains || {})) {
    if (papersByDomain[k]) papersByDomain[k] = arr;
  }

  const allPapers = Object.values(papersByDomain).flat();
  document.getElementById("paper-count").textContent = allPapers.length;
  document.getElementById("journal-count").textContent = feeds.length;
  document.getElementById("last-update").textContent = papersData.date || "--";
  document.getElementById("footer-feeds").textContent = feeds.length;
  document.getElementById("loading").style.display = "none";

  const newPapers = filterByFirstSeen(allPapers, today);
  const newCount = newPapers.length;

  function renderTabPane(tabKey) {
    if (tabKey === "scholars") {
      document.getElementById("section-scholars").innerHTML = renderScholars();
      return;
    }
    const section = document.getElementById(`section-${tabKey}`);
    const st = tabState(tabKey);

    // 全部去重论文（按 paper.domains 过滤）
    const allPapers = allUniquePapers(papersByDomain);
    const tabPapers = papersForTab(tabKey, allPapers);
    const journals = journalsForTab(tabKey, allPapers, feeds);

    const allByJournal = buildPapersByJournal(tabPapers);

    let displayPapers, displayJournals, subTabJournals = [];
    if (st.viewMode === "batch") {
      const tabNewPapers = filterByFirstSeen(tabPapers, today);
      const byJ = {};
      for (const p of tabNewPapers) (byJ[p.source] ||= []).push(p);
      subTabJournals = Object.entries(byJ)
        .map(([name, arr]) => ({ name, count: arr.length }))
        .sort((a, b) => b.count - a.count);
      displayPapers = tabNewPapers;
      displayJournals = subTabJournals.map(j => journals.find(f => f.name === j.name)).filter(Boolean);
    } else {
      displayPapers = topNPerJournal(tabPapers, 5);
      displayJournals = journals;
    }

    const displayByJournal = buildPapersByJournal(displayPapers);

    // 选中的期刊（sub-tab 选择）
    let selectedJournal = st.selectedJournal;
    if (selectedJournal !== "__all__" && !displayByJournal[selectedJournal]) {
      selectedJournal = "__all__";
      st.selectedJournal = "__all__";
    }
    const viewPapers = selectedJournal === "__all__"
      ? displayPapers
      : displayByJournal[selectedJournal] || [];

    section.innerHTML = `
      <div class="tab-toolbar">
        ${renderViewControl(st, newCount, allPapers.length)}
        ${st.viewMode === "batch" ? renderSubTabs(subTabJournals, selectedJournal) : ""}
      </div>
      <div class="tab-content">
        ${renderSidebar(displayJournals, displayByJournal, selectedJournal)}
        ${renderMain(selectedJournal, viewPapers, st.query)}
      </div>
    `;

    // 绑定 sidebar 点击
    section.querySelectorAll(".jlist-item").forEach(el => {
      el.addEventListener("click", () => {
        st.selectedJournal = el.dataset.key;
        renderTabPane(tabKey);
      });
    });
    // 绑定 segmented pills
    section.querySelectorAll(".seg-pill").forEach(el => {
      el.addEventListener("click", () => {
        st.viewMode = el.dataset.mode;
        st.selectedJournal = "__all__";
        renderTabPane(tabKey);
      });
    });
    // 绑定 sub-tabs
    section.querySelectorAll(".sub-tab").forEach(el => {
      el.addEventListener("click", () => {
        st.selectedJournal = el.dataset.key;
        renderTabPane(tabKey);
      });
    });
    // 论文卡片点击 → 内联展开
    bindPaperClicks(section);
  }

  ["journals", "social-security", "health-reform", "elder-care", "social-work", "scholars"]
    .forEach(renderTabPane);

  window.addEventListener("search:change", () => {
    const tab = window.STATE.activeTab;
    if (tab === "scholars") return;
    tabState(tab).query = window.STATE.query;
    renderTabPane(tab);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindModalClose();
  main();
});
