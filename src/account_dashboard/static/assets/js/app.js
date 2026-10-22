/* 应用外壳：路由、主题、导航、全局事件、页面编排。 */

import { initApi, api, apiMode } from './core/api.js';
import { state, applyTheme, setPeriod } from './core/store.js';
import { $, $$, toast, closeLayer, skeletonPage, errorPanel, pageHead } from './core/ui.js';
import { icon } from './core/icons.js';
import { openTransaction } from './core/tx-drawer.js';

import * as dashboard from './pages/dashboard.js';
import * as reports from './pages/reports.js';
import * as analysis from './pages/analysis.js';
import * as importPage from './pages/import.js';
import * as buffer from './pages/buffer.js';
import * as raw from './pages/raw.js';
import * as detail from './pages/detail.js';
import * as pending from './pages/pending.js';
import * as rules from './pages/rules.js';
import * as categories from './pages/categories.js';
import * as backup from './pages/backup.js';
import * as settings from './pages/settings.js';
import * as help from './pages/help.js';
import * as ds from './pages/ds.js';

const ROUTES = [
  { k: 'dashboard', n: '仪表盘', g: '总览', i: 'dashboard', f: dashboard, d: '本期收支全貌' },
  { k: 'reports', n: '报表中心', g: '总览', i: 'reports', f: reports, d: '月度 / 季度 / 年度' },
  { k: 'analysis', n: '分类分析', g: '总览', i: 'pie', f: analysis, d: '分类结构与下钻' },
  { k: 'import', n: '导入账单', g: '数据', i: 'import', f: importPage, d: '缓冲区五步链路' },
  { k: 'buffer', n: '缓冲区', g: '数据', i: 'buffer', f: buffer, d: '批次与残留管理' },
  { k: 'raw', n: '原始库', g: '数据', i: 'archive', f: raw, d: '按月归档与追溯' },
  { k: 'detail', n: '流水明细', g: '数据', i: 'list', f: detail, d: '查询与分类修正' },
  { k: 'pending', n: '待确认', g: '分类', i: 'pending', f: pending, d: '未分类流水' },
  { k: 'rules', n: '分类规则', g: '分类', i: 'rules', f: rules, d: '自动归类规则' },
  { k: 'categories', n: '分类体系', g: '分类', i: 'tag', f: categories, d: '一级 / 二级分类' },
  { k: 'backup', n: '备份与恢复', g: '系统', i: 'shield', f: backup, d: '本机备份与回退' },
  { k: 'settings', n: '基础设置', g: '系统', i: 'gear', f: settings, d: '阈值 / 目录 / 主题' },
  { k: 'help', n: '帮助说明', g: '系统', i: 'help', f: help, d: '口径与引导' },
  { k: 'ds', n: '设计规范', g: '系统', i: 'palette', f: ds, d: '变量 / 组件 / 状态' },
];

const PAGES = Object.fromEntries(ROUTES.map((r) => [r.k, r.f]));
let renderToken = 0;
let lastRoute = null;
let badgeTimer = 0;

/* ---------------- 外壳 ---------------- */
function renderRail() {
  const groups = ['总览', '数据', '分类', '系统'];
  const pend = state.pendingBadge || 0;
  $('#rail').innerHTML = `
    <div class="brand">
      <span class="brand__mark">账</span>
      <span class="brand__text">
        <span class="brand__name" style="display:block">记账簿</span>
        <span class="brand__sub">finance.local</span>
      </span>
    </div>
    <nav class="nav" aria-label="主导航">
      ${groups.map((g) => `<div class="nav__group">
        <div class="nav__label">${g}</div>
        ${ROUTES.filter((r) => r.g === g).map((r) => `
          <button class="nav__item" data-go="${r.k}" ${state.route === r.k ? 'aria-current="page"' : ''}
            title="${r.n} · ${r.d}">
            ${icon(r.i, 17)}<span>${r.n}</span>
            ${r.k === 'pending' && pend > 0 ? `<span class="nav__badge">${pend}</span>` : ''}
          </button>`).join('')}
      </div>`).join('')}
    </nav>
    <div class="rail__foot">
      <div class="rail__card">
        <b>数据目录</b>
        <span data-dir-text>${state.health?.data_dir ? truncate(state.health.data_dir, 26) : '—'}</span>
        ${state.health ? `<br>数据库 <code>${state.health.db_ok ? '正常' : '异常'}</code> · 待清理 <code>${state.health.backlog?.cleanup ?? 0}</code>` : ''}
      </div>
      <div class="rail__ver"><span class="rail__dot">本地运行</span><span>v${state.health?.version || '0.1.0'}</span></div>
    </div>`;
}

function renderTopbar() {
  const r = ROUTES.find((x) => x.k === state.route) || ROUTES[0];
  const mock = apiMode() === 'mock';
  const down = state.health && state.health.db_ok === false;
  const badge = down
    ? `<span class="src-badge src-badge--down" title="数据库不可用"><i></i>数据库异常</span>`
    : mock
      ? `<span class="src-badge src-badge--mock" title="后端统计接口尚未交付（C2~C4），当前使用与契约同构的本地数据源；加 ?mock=0 可强制连接真实后端"><i></i>演示数据</span>`
      : `<span class="src-badge" title="已连接本地服务：127.0.0.1"><i></i>本地服务</span>`;

  $('#topbar').innerHTML = `
    <div class="topbar__crumb">
      <span>个人财务分析</span><span class="sep">/</span><b>${r.n}</b>
      <span class="sep">·</span><span>${r.d}</span>
    </div>
    <span class="topbar__date">${todayText()} · 仅监听 127.0.0.1</span>
    <div class="topbar__right">
      ${badge}
      <div class="theme-switch" role="group" aria-label="界面主题">
        <button class="theme-switch__item" data-theme-set="pink" aria-pressed="${state.theme === 'pink'}" title="玫瑰粉 · 少女感"><i></i>粉</button>
        <button class="theme-switch__item" data-theme-set="sky" aria-pressed="${state.theme === 'sky'}" title="天青蓝 · 自然清新"><i></i>蓝</button>
      </div>
      <button class="icon-btn" data-go="help" aria-label="帮助">${icon('help', 17)}</button>
      <button class="icon-btn" data-go="settings" aria-label="设置">${icon('gear', 17)}</button>
    </div>`;
}

function todayText() {
  const d = new Date();
  const wd = '日一二三四五六'[d.getDay()];
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} 周${wd}`;
}

const truncate = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

/* ---------------- 渲染 ---------------- */
async function renderCurrent() {
  const t = ++renderToken;
  const route = ROUTES.find((x) => x.k === state.route) || ROUTES[0];
  const page = PAGES[state.route];
  window.__fdRoute = state.route;
  document.title = `${route.n} · 记账簿`;

  renderRail();
  renderTopbar();

  const view = $('#view');
  if (lastRoute !== state.route) {
    window.scrollTo(0, 0);
    lastRoute = state.route;
    page?.onEnter?.();
  }
  view.setAttribute('aria-busy', 'true');
  view.innerHTML = skeletonPage();

  try {
    const html = await page.render();
    if (t !== renderToken) return;
    view.innerHTML = html;
    view.removeAttribute('aria-busy');
    await page.afterRender?.();
    if (t !== renderToken) return;
    refreshBadge();
  } catch (err) {
    if (t !== renderToken) return;
    view.removeAttribute('aria-busy');
    view.innerHTML = pageHead(route.n, route.d)
      + errorPanel(err, 'data-act="retry-render"');
    console.error('[render]', err);
  }
}

function refreshBadge() {
  const now = Date.now();
  if (now - badgeTimer < 15000) return;
  badgeTimer = now;
  api.pendingCount().then((r) => {
    const prev = state.pendingBadge || 0;
    state.pendingBadge = r.count;
    if (prev !== r.count) renderRail();
  }).catch(() => { /* 待确认计数失败不打扰用户 */ });
}

/* ---------------- 导航 ---------------- */
function go(route, opts = {}) {
  if (!ROUTES.some((r) => r.k === route)) return;
  // 从导航进入导入页时默认开一个新的导入；只有缓冲区「继续处理」才保留批次
  if (route === 'import' && !opts.keepBatch) {
    state.importBatchId = '';
    state.importStep = 1;
  }
  state.route = route;
  if (location.hash.slice(1) !== route) {
    // 用 replaceState 写地址，避免 hashchange 与本次渲染重复触发
    history.replaceState(null, '', '#' + route);
  }
  renderCurrent();
}

/* ---------------- 全局事件 ---------------- */
document.addEventListener('click', async (e) => {
  const goEl = e.target.closest('[data-go]');
  if (goEl) {
    e.preventDefault();
    go(goEl.dataset.go);
    return;
  }

  const th = e.target.closest('[data-theme-set]');
  if (th) {
    const t = th.dataset.themeSet;
    applyTheme(t);
    $$('[data-theme-set]').forEach((el) => el.setAttribute('aria-pressed', String(el.dataset.themeSet === t)));
    toast(t === 'pink' ? '已切换到「玫瑰粉」主题' : '已切换到「天青蓝」主题', 'ok');
    if (['ds', 'settings'].includes(state.route)) renderCurrent();
    return;
  }

  const per = e.target.closest('[data-period]');
  if (per) {
    setPeriod(per.dataset.period);
    state.filters.page = 1;
    renderCurrent();
    return;
  }

  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;
  const page = PAGES[state.route];

  if (act === 'close-layer') {
    if (el.classList.contains('overlay') && e.target.closest('.modal, .drawer')) return;
    closeLayer();
    return;
  }

  if (act === 'retry-render') {
    renderCurrent();
    return;
  }

  const fn = page?.actions?.[act];
  if (fn) {
    try {
      await fn(el.dataset, el, ctx);
    } catch (err) {
      console.error('[action]', act, err);
      toast(err.message || '操作未完成，请重试', 'warn');
    }
    return;
  }

  if (act === 'toggle') {
    const on = el.getAttribute('aria-checked') === 'true';
    el.setAttribute('aria-checked', String(!on));
    return;
  }

  if (act === 'toast') toast(el.dataset.msg || '已完成', 'ok');
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLayer();
});

window.addEventListener('hashchange', () => {
  const k = decodeURIComponent(location.hash.slice(1));
  if (ROUTES.some((r) => r.k === k) && k !== state.route) {
    state.route = k;
    renderCurrent();
  }
});

/* 图表 tooltip（事件委托，图表重绘后无需重新绑定） */
const tip = { el: null };
document.addEventListener('mousemove', (e) => {
  const el = e.target.closest('[data-tip]');
  if (!el) {
    if (tip.el) tip.el.classList.remove('is-on');
    $$('.chart .pt').forEach((p) => (p.style.opacity = '0'));
    return;
  }
  tip.el = tip.el || $('#tip');
  tip.el.innerHTML = el.dataset.tip;
  tip.el.classList.add('is-on');
  const pad = 14;
  tip.el.style.left = Math.min(window.innerWidth - 160, e.clientX + pad) + 'px';
  tip.el.style.top = Math.max(8, e.clientY - 36) + 'px';
  if (el.classList.contains('hit')) {
    const svg = el.closest('svg');
    if (svg) svg.querySelectorAll('.pt').forEach((p) => (p.style.opacity = p.dataset.i === el.dataset.i ? '1' : '0'));
  }
});

/* 页面上下文：刷新、导航、打开流水抽屉 */
const ctx = {
  refresh: () => renderCurrent(),
  go: (route, opts) => go(route, opts),
  openTx: (id) => openTransaction(id, { onChanged: () => renderCurrent() }),
};

window.__fdRefresh = () => renderCurrent();
window.__fdGo = (r) => go(r);

/* ---------------- 启动 ---------------- */
async function boot() {
  applyTheme(state.theme);
  renderRail();
  renderTopbar();

  await initApi();
  try {
    state.health = await api.health();
  } catch {
    state.health = null;
  }

  const initial = decodeURIComponent(location.hash.slice(1));
  if (ROUTES.some((r) => r.k === initial)) state.route = initial;
  else if (!location.hash) history.replaceState(null, '', '#' + state.route);

  await renderCurrent();
  if (apiMode() === 'mock') {
    console.info('[记账簿] 当前使用本地契约数据源：后端 C2~C4 未交付时自动启用；?mock=0 可强制真机联调。');
  }
}

boot();
