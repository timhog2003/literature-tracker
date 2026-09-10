// app-render.js — 论文卡片 + 展开详情
// 中文标题/摘要（来自 M3 翻译）作为主显示，英文作为副显示

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function isChinese(s) {
  return /[一-龿]/.test(s || "");
}

// 论文卡片列表态：中文标题为主，英文为副
function paperHTML(paper, num) {
  const date = paper.date || "";
  const numStr = String(num).padStart(2, "0");
  const titleZh = paper.titleZh || paper.title || "";
  const titleEn = paper.titleZh && paper.title !== paper.titleZh ? paper.title : "";
  const domain = (paper.domains || []).join(",");
  const url = paper.url || "#";

  return `
    <article class="paper" data-url="${escapeHtml(paper.url)}" data-source="${escapeHtml(paper.source)}" data-date="${escapeHtml(date)}" data-title="${escapeHtml(paper.title)}" data-title-zh="${escapeHtml(paper.titleZh || '')}" data-abstract="${escapeHtml(paper.abstract || '')}" data-abstract-zh="${escapeHtml(paper.abstractZh || '')}" data-domain="${escapeHtml(domain)}">
      <div class="paper-num">${numStr}</div>
      <div class="paper-body">
        <h3 class="paper-title">${escapeHtml(titleZh)}</h3>
        ${titleEn ? `<p class="paper-title-en">${escapeHtml(titleEn)}</p>` : ""}
        <div class="paper-meta">
          <span class="source">${escapeHtml(paper.source)}</span>
          <span>·</span>
          <span>${escapeHtml(date)}</span>
          <a class="paper-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">阅读原文 ↗</a>
        </div>
      </div>
    </article>`;
}

function emptyHTML(msg) {
  return `<div class="main-empty">${escapeHtml(msg)}</div>`;
}

function applyFilter(items, q) {
  if (!q) return items;
  return items.filter(it =>
    (it.title    || "").toLowerCase().includes(q) ||
    (it.titleZh  || "").toLowerCase().includes(q) ||
    (it.source   || "").toLowerCase().includes(q)
  );
}

window.RENDER = { paperHTML, emptyHTML, applyFilter, escapeHtml, isChinese };
