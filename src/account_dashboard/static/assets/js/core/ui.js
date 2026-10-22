/* 通用 UI：卡片、状态徽标、总览带、弹层、轻提示。
   所有颜色走语义变量；状态同时用「颜色 + 文字 + 圆点」三重编码。 */

import { icon } from './icons.js';
import { esc, fmt, money, bigMoney, deltaHtml } from './format.js';

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ---------- 业务状态 → 文案 + 语义色 ---------- */
export const ST = {
  pending: { t: '待确认', c: 'warn' },
  confirmed: { t: '已分类', c: 'ok' },
  corrected: { t: '已修正', c: 'info' },
  excluded: { t: '已排除', c: 'neutral' },
  uploaded: { t: '已上传', c: 'neutral' },
  mapped_pending: { t: '待映射', c: 'info' },
  prechecked: { t: '待确认', c: 'warn' },
  ingesting: { t: '入库中', c: 'info' },
  ingested: { t: '已入库', c: 'ok' },
  discarded: { t: '已丢弃', c: 'neutral' },
  failed: { t: '解析失败', c: 'danger' },
  cleaning: { t: '文件待清理', c: 'warn' },
};

export const stBadge = (s) => {
  const m = ST[s] || ST.confirmed;
  return `<span class="badge badge--${m.c}">${m.t}</span>`;
};

export const DIR = { income: '收入', expense: '支出', neutral: '中性' };
export const CHANNEL = { wechat: '微信', alipay: '支付宝', bank: '银行卡', other: '其他' };
export const MATCH_FIELD = { counterparty: '交易对方', item: '商品说明', txn_type: '交易类型', any: '任意字段' };

export const dirBadge = (d) =>
  d === 'income' ? '<span class="badge badge--ok">收入</span>'
    : d === 'neutral' ? '<span class="badge badge--neutral">中性</span>'
      : '<span class="badge badge--plain" style="background:var(--surface-3)">支出</span>';

/* ---------- 结构件 ---------- */
export function card({ title, sub, actions, body, raw, foot, cls = '', bodyCls = '' }) {
  return `<section class="card ${cls}">
    ${title ? `<div class="card__head">
      <div><div class="card__title">${title}</div>${sub ? `<div class="card__sub">${sub}</div>` : ''}</div>
      <div class="spacer"></div>${actions || ''}
    </div>` : ''}
    ${raw !== undefined ? raw : body !== undefined ? `<div class="card__body ${bodyCls}">${body}</div>` : ''}
    ${foot ? `<div class="card__foot">${foot}</div>` : ''}
  </section>`;
}

export function pageHead(title, sub, actions) {
  return `<div class="page-head">
    <div><h1 class="page-head__title">${title}</h1>${sub ? `<p class="page-head__sub">${sub}</p>` : ''}</div>
    <div class="page-head__actions">${actions || ''}</div>
  </div>`;
}

/* 总览带：全局唯一的「英雄数字」模板 */
export function overviewBand(period, kpi, subNote = '总收入 − 总支出') {
  const dIncome = deltaHtml(kpi.income_mom, { good: (kpi.income_mom || 0) >= 0, flag: kpi.mom_flag === 'na' ? 'na' : 'ok' });
  const dExpense = deltaHtml(kpi.expense_mom, { good: (kpi.expense_mom || 0) <= 0, flag: kpi.mom_flag === 'na' ? 'na' : 'ok' });
  const dSaving = deltaHtml(kpi.savings_mom ?? null, { good: (kpi.savings_mom || 0) >= 0, unit: 'pt' });
  const dAvg = deltaHtml(kpi.daily_avg_mom ?? null, { good: (kpi.daily_avg_mom || 0) <= 0 });
  const saving = kpi.savings_rate == null ? '—' : fmt(kpi.savings_rate, 1) + '%';
  return `<section class="overview">
    <div class="overview__main">
      <div class="overview__eyebrow">本期结余 · ${esc(period.label)}</div>
      <div class="overview__value">${bigMoney(kpi.balance_cents)}</div>
      <div class="overview__meta">
        <span class="badge badge--info badge--plain">储蓄率 ${saving}</span>
        <span class="small muted">较上期 ${dSaving}</span>
        <span class="hr--v"></span>
        <span class="small muted">${subNote}</span>
      </div>
    </div>
    <div class="overview__stats">
      <div class="ostat">
        <div class="ostat__k"><i class="dot-k" style="background:var(--fin-down)"></i>总收入</div>
        <div class="ostat__v">${money(kpi.total_income_cents)} ${dIncome}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k"><i class="dot-k" style="background:var(--fin-up)"></i>总支出</div>
        <div class="ostat__v">${money(kpi.total_expense_cents)} ${dExpense}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k">${icon('sparkles', 12)}储蓄率</div>
        <div class="ostat__v">${saving.replace('%', '')}<small>%</small> ${dSaving}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k">${icon('clock', 12)}日均支出</div>
        <div class="ostat__v">${money(kpi.daily_avg_cents ?? 0)} ${dAvg}</div>
      </div>
    </div>
  </section>`;
}

export function emptyState({ iconName = 'db', title, desc, actions = '' }) {
  return `<div class="empty">
    <div class="empty__art">${icon(iconName, 30)}</div>
    <div class="empty__title">${title}</div>
    <div class="empty__desc">${desc}</div>
    ${actions ? `<div class="empty__actions">${actions}</div>` : ''}
  </div>`;
}

export function skeletonPage() {
  return `<div class="stack" style="gap:16px">
    <div class="skeleton" style="height:22px;width:220px"></div>
    <div class="skeleton" style="height:14px;width:340px"></div>
    <div class="skeleton" style="height:150px;width:100%;border-radius:16px"></div>
    <div class="grid g-12">
      <div class="c-8"><div class="skeleton" style="height:280px;width:100%;border-radius:16px"></div></div>
      <div class="c-4"><div class="skeleton" style="height:280px;width:100%;border-radius:16px"></div></div>
    </div>
    <div class="skeleton" style="height:120px;width:100%;border-radius:16px"></div>
  </div>`;
}

export function errorPanel(err, retryAttr = 'data-act="retry"') {
  return `<section class="card"><div class="card__body">
    ${emptyState({
      iconName: 'alert',
      title: '这块内容暂时取不到',
      desc: `${esc(err?.message || '未知错误')}${err?.code ? `（${esc(err.code)}）` : ''}<br>数据没有丢失，可以重试；若持续失败，请查看服务日志。`,
      actions: `<button class="btn btn--outline" ${retryAttr}>${icon('refresh', 14)}重新加载</button>`,
    })}
  </div></section>`;
}

/* ---------- 轻提示 ---------- */
export function toast(msg, kind = '') {
  const box = $('#toasts');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ' toast--' + kind : '');
  el.innerHTML = `<i></i><span>${msg}</span>`;
  box.appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity .3s, transform .3s'; el.style.opacity = '0'; el.style.transform = 'translateY(6px)'; }, 2600);
  setTimeout(() => el.remove(), 3000);
}

/* ---------- 弹层 ---------- */
export function openLayer(html) {
  const layer = $('#layer');
  layer.innerHTML = html;
  document.body.style.overflow = 'hidden';
  const focusable = layer.querySelector('.modal, .drawer');
  if (focusable) { focusable.setAttribute('tabindex', '-1'); setTimeout(() => focusable.focus(), 30); }
  return layer;
}

export function closeLayer() {
  const layer = $('#layer');
  if (!layer) return;
  layer.innerHTML = '';
  document.body.style.overflow = '';
}

async function withLoading(btn, fn) {
  const prev = btn.innerHTML;
  btn.disabled = true;
  btn.classList.add('btn--loading');
  try { return await fn(); } finally {
    btn.disabled = false;
    btn.classList.remove('btn--loading');
    btn.innerHTML = prev;
  }
}

export function modal({ title, sub, body, foot, size = '', acts = {}, onMount }) {
  const layer = openLayer(`<div class="overlay" data-act="close-layer">
    <div class="modal ${size}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal__head">
        <div><div class="modal__title">${title}</div>${sub ? `<div class="modal__sub">${sub}</div>` : ''}</div>
        <div class="spacer"></div>
        <button class="icon-btn" data-act="close-layer" aria-label="关闭">${icon('x', 16)}</button>
      </div>
      <div class="modal__body">${body}</div>
      ${foot ? `<div class="modal__foot">${foot}</div>` : ''}
    </div>
  </div>`);

  for (const [name, fn] of Object.entries(acts)) {
    layer.querySelectorAll(`[data-act="${name}"]`).forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const isSubmit = btn.dataset.loading !== 'none';
        if (isSubmit) await withLoading(btn, () => fn(layer));
        else await fn(layer);
      });
    });
  }
  if (onMount) onMount(layer);
  return layer;
}

export function drawer({ title, sub, body, foot, acts = {} }) {
  const layer = openLayer(`<div class="overlay drawer-overlay" data-act="close-layer">
    <div class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="drawer__head">
        <div><div class="modal__title">${title}</div>${sub ? `<div class="modal__sub">${sub}</div>` : ''}</div>
        <button class="icon-btn" data-act="close-layer" aria-label="关闭">${icon('x', 16)}</button>
      </div>
      <div class="drawer__body">${body}</div>
      ${foot ? `<div class="drawer__foot">${foot}</div>` : ''}
    </div>
  </div>`);
  for (const [name, fn] of Object.entries(acts)) {
    layer.querySelectorAll(`[data-act="${name}"]`).forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await withLoading(btn, () => fn(layer));
      });
    });
  }
  return layer;
}

/* 二次确认：破坏性操作统一走这里，返回 Promise<boolean> */
export function confirmDialog({ title, sub, body, confirmText = '确认执行', danger = false }) {
  return new Promise((resolve) => {
    let settled = false;
    let observer = null;
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    const done = (v) => {
      if (settled) return;
      settled = true;
      observer?.disconnect();
      document.removeEventListener('keydown', onKey);
      resolve(v);
      closeLayer();
    };

    modal({
      title, sub, body, size: 'modal--sm',
      foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
        <button class="btn ${danger ? 'btn--danger' : 'btn--primary'}" data-act="ok">${confirmText}</button>`,
      acts: {
        cancel: () => done(false),
        ok: () => done(true),
      },
    });

    const layer = $('#layer');
    // Esc / 右上角关闭 / 点遮罩关闭都要让 Promise 落地，否则调用方会永久 pending
    document.addEventListener('keydown', onKey);
    observer = new MutationObserver(() => {
      if (!layer.querySelector('.modal') && !settled) {
        settled = true;
        observer.disconnect();
        document.removeEventListener('keydown', onKey);
        resolve(false);
      }
    });
    observer.observe(layer, { childList: true });
  });
}

export function fieldValue(layer, name) {
  const el = layer.querySelector(`[data-field="${name}"]`);
  return el ? el.value : null;
}

export function fieldChecked(layer, name) {
  const el = layer.querySelector(`[data-field="${name}"]`);
  return !!(el && el.checked);
}

/* 分类下拉选项：value 用 l1||l2，避免两级名称重复时串味 */
export function categoryOptions(nodes, { includeEmpty = false, selected = '' } = {}) {
  const opts = [];
  if (includeEmpty) opts.push(`<option value="">全部分类</option>`);
  for (const g of nodes || []) {
    for (const c of g.children || []) {
      if (c.enabled === false) continue;
      const v = `${c.l1}||${c.l2}`;
      opts.push(`<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(c.l1)} · ${esc(c.l2)}</option>`);
    }
  }
  return opts.join('');
}

export const fmtPct = (v) => (v == null ? '—' : fmt(v, 1) + '%');
