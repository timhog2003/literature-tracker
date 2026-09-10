// app-core.js — Tab 切换、主题切换、搜索过滤
// ponytail: 单一职责；状态在 window.STATE

const STATE = window.STATE = {
  activeTab: "journals",
  query: "",
  theme: localStorage.getItem("theme") || "light",
};

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(STATE.theme);
  bindTabs();
  bindThemeToggle();
  bindSearch();
  setTodayDate();
});

function applyTheme(t) {
  document.body.dataset.theme = t;
  localStorage.setItem("theme", t);
}

function bindThemeToggle() {
  document.getElementById("theme-toggle").addEventListener("click", () => {
    STATE.theme = STATE.theme === "light" ? "dark" : "light";
    applyTheme(STATE.theme);
  });
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab").forEach(b => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn);
      });
      // ponytail: 新 HTML 用 .tabpane 不是 .section
      document.querySelectorAll(".tabpane").forEach(s => {
        const show = s.dataset.tab === tab;
        s.classList.toggle("active", show);
        if (show) s.removeAttribute("hidden"); else s.setAttribute("hidden", "");
      });
      STATE.activeTab = tab;
      window.dispatchEvent(new CustomEvent("tab:change", { detail: { tab } }));
    });
  });
}

function bindSearch() {
  const input = document.getElementById("search");
  input.addEventListener("input", e => {
    STATE.query = e.target.value.trim().toLowerCase();
    window.dispatchEvent(new CustomEvent("search:change", { detail: { q: STATE.query } }));
  });
}

function setTodayDate() {
  const fmt = d => d.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  document.getElementById("today-date").textContent = fmt(new Date());
}
