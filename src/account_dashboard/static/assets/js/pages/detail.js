/* 流水明细：筛选 / 排序 / 分页 / 批量修正 / 抽屉编辑。
   汇总数字来自 /transactions/summary（与月报同源），前端不自行加总。 */

import {api} from '../core/api.js';
import {state, loadCategories} from '../core/store.js';
import {card, pageHead, stBadge, dirBadge, emptyState, toast, modal, closeLayer, categoryOptions, fieldValue} from '../core/ui.js';
import {openTransaction} from '../core/tx-drawer.js';
import {icon} from '../core/icons.js';
import {esc, money, shortDateTime, fullDateTime} from '../core/format.js';
import {} from '../core/format.js';

const sel = new Set();

function currentAnchor() {
  return state.anchors[state.filters.period] || state.anchors.month;
}

function splitCat() {
  const f = state.filters;
  if (f.category_l2 === '未分类') return { category_l2: '未分类' };
  if (f.category_l2) return { category_l1: f.category_l1, category_l2: f.category_l2 };
  if (f.category_l1) return { category_l1: f.category_l1 };
  return {};
}

function query(extra = {}) {
  const f = state.filters;
  return {
    period: f.period,
    anchor: currentAnchor(),
    direction: f.direction === 'all' ? undefined : f.direction,
    status: f.status === 'all' ? undefined : f.status,
    ...splitCat(),
    keyword: f.keyword || undefined,
    sort: f.sort,
    page: f.page,
    page_size: f.page_size,
    ...extra,
  };
}

function catValue() {
  const f = state.filters;
  if (f.category_l2 === '未分类') return '未分类';
  if (f.category_l2) return `${f.category_l1}||${f.category_l2}`;
  return '';
}

function filterLabel() {
  const f = state.filters;
  return f.direction !== 'all' || f.status !== 'all' || f.keyword || f.category_l1 || f.category_l2;
}

export async function render() {
  const nodes = await loadCategories().catch(() => []);
  const [page, summary] = await Promise.all([
    api.transactions(query()),
    api.summary(query({ page: undefined, page_size: undefined, sort: undefined })),
  ]);

  sel.forEach((id) => { if (!page.items.some((t) => t.id === id)) sel.delete(id); });

  const f = state.filters;
  const filtered = filterLabel();
  const totalPages = page.meta.total_pages || 1;

  const sortKey = f.sort.replace(/^-/, '');
  const sortDir = f.sort.startsWith('-') ? 'desc' : 'asc';
  const arrow = (k) => (sortKey === k ? (sortDir === 'desc' ? '▼' : '▲') : '');
  const ariaSort = (k) => (sortKey === k ? (sortDir === 'desc' ? 'descending' : 'ascending') : 'none');

  const actions = `<button class="btn btn--outline" data-act="export">${icon('download', 15)}导出本页</button>
    <button class="btn btn--primary" data-go="import">${icon('plus', 15)}导入</button>`;

  const filterBar = `<section class="card card--flush">
    <div class="filterbar">
      <div class="select select--sm" style="width:132px"><select class="select__native" data-filter="period">
        ${[['month', '本月'], ['quarter', '本季度'], ['year', '本年度']].map(([k, t]) =>
          `<option value="${k}" ${f.period === k ? 'selected' : ''}>${t}</option>`).join('')}
      </select></div>
      <div class="select select--sm" style="width:170px"><select class="select__native" data-filter="cat">
        <option value="">全部分类</option>
        ${categoryOptions(nodes, { selected: catValue() })}
        <option value="未分类" ${f.category_l2 === '未分类' ? 'selected' : ''}>未分类（待确认）</option>
      </select></div>
      <div class="row" style="gap:6px">
        ${[['all', '全部'], ['expense', '支出'], ['income', '收入'], ['neutral', '中性']].map(([k, t]) =>
          `<button class="chip" data-act="dir" data-val="${k}" aria-pressed="${f.direction === k}">${t}</button>`).join('')}
      </div>
      <div class="select select--sm" style="width:132px"><select class="select__native" data-filter="status">
        <option value="all">全部状态</option>
        ${[['confirmed', '已分类'], ['corrected', '已修正'], ['pending', '待确认'], ['excluded', '已排除']].map(([k, t]) =>
          `<option value="${k}" ${f.status === k ? 'selected' : ''}>${t}</option>`).join('')}
      </select></div>
      <div class="input-group">
        <span class="input-group__icon">${icon('search', 15)}</span>
        <input class="input" placeholder="搜索对方 / 商品说明" value="${esc(f.keyword)}" data-filter="q" maxlength="50" style="height:30px;font-size:13px">
      </div>
      <div class="filterbar__more">
        <button class="btn btn--ghost btn--sm" data-act="reset">${icon('refresh', 13)}重置</button>
        <span class="tiny muted">${page.items.length} / ${page.meta.total} 条</span>
      </div>
    </div>
    <div class="summary-strip">
      <span>${filtered ? '筛选结果' : '本期合计'}<b>${summary.total}</b>笔</span><i class="sep"></i>
      <span>支出<b>¥${money(summary.expense_cents)}</b></span><i class="sep"></i>
      <span>收入<b>¥${money(summary.income_cents)}</b></span><i class="sep"></i>
      <span>净额<b>¥${money(summary.net_cents)}</b></span>
      <span class="badge badge--ok" style="margin-left:auto">${icon('check', 11)}与月报同口径</span>
    </div>
    ${sel.size ? `<div class="bulkbar">
      <span class="bulkbar__count">已选 <b>${sel.size}</b> 笔</span>
      <span class="small" style="opacity:.7">批量套用分类，可同时生成规则</span>
      <div class="spacer"></div>
      <button class="btn btn--ghost btn--sm" data-act="clear-sel">取消</button>
      <button class="btn btn--outline btn--sm" data-act="bulk-cat">批量改分类</button>
      <button class="btn btn--primary btn--sm" data-act="bulk-rule">生成规则</button>
    </div>` : ''}
  </section>`;

  const rows = page.items.map((t) => `<tr data-id="${esc(t.id)}" class="${sel.has(t.id) ? 'is-selected' : ''}">
      <td><label class="checkbox" onclick="event.stopPropagation()"><input type="checkbox" data-act="sel-row" data-id="${esc(t.id)}" ${sel.has(t.id) ? 'checked' : ''}><span class="checkbox__box"></span></label></td>
      <td class="num" style="color:var(--text-3);font-size:12px">${shortDateTime(t.occurred_at)}</td>
      <td><div class="cell-2line"><span class="td-strong">${esc(t.counterparty || '—')}</span><small>${esc(t.item || '')}</small></div></td>
      <td><span class="cell-edit" data-act="open-tx" data-id="${esc(t.id)}">${esc(t.category_l1 ? `${t.category_l1} · ${t.category_l2 || ''}` : '未分类')}${icon('edit', 11)}</span></td>
      <td>${dirBadge(t.direction)}</td>
      <td class="td-muted">${esc(t.payment_method || '—')}</td>
      <td class="td-muted mono">${esc(t.batch_id)}</td>
      <td>${stBadge(t.status)}</td>
      <td class="td-num td-strong" style="color:${t.direction === 'neutral' ? 'var(--text-3)' : t.direction === 'income' ? 'var(--fin-down)' : 'var(--text-1)'}">
        ${t.direction === 'income' ? '+' : t.direction === 'expense' ? '−' : ''}${money(t.amount_cents)}</td>
    </tr>`).join('');

  const table = `<section class="card card--flush" style="margin-top:16px">
    <div class="table-wrap"><table class="table">
      <thead><tr>
        <th style="width:36px"><label class="checkbox"><input type="checkbox" data-act="sel-all" ${page.items.length && page.items.every((r) => sel.has(r.id)) ? 'checked' : ''}><span class="checkbox__box"></span></label></th>
        <th class="is-sortable" data-act="sort" data-key="occurred_at" aria-sort="${ariaSort('occurred_at')}">时间 <span class="sort-ind">${arrow('occurred_at')}</span></th>
        <th>对方 / 商品说明</th>
        <th>分类</th>
        <th>方向</th>
        <th>支付方式</th>
        <th>来源批次</th>
        <th>状态</th>
        <th class="right is-sortable" data-act="sort" data-key="amount_cents" aria-sort="${ariaSort('amount_cents')}">金额 <span class="sort-ind">${arrow('amount_cents')}</span></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    ${page.items.length === 0 ? emptyState({
      iconName: 'search',
      title: '没有符合条件的流水',
      desc: '试着重置筛选，或换一个关键词。筛选只影响展示，不会改动任何数据。',
      actions: '<button class="btn btn--outline" data-act="reset">重置筛选</button>',
    }) : `<div class="pager">
        <span>显示 ${(page.meta.page - 1) * page.meta.page_size + 1}–${Math.min(page.meta.page * page.meta.page_size, page.meta.total)} 条 · 共 ${page.meta.total} 条 · 每页 ${page.meta.page_size} 条</span>
        <div class="pager__nums">
          <button class="pager__num" data-act="page" data-page="${page.meta.page - 1}" ${page.meta.page <= 1 ? 'disabled' : ''} aria-label="上一页">‹</button>
          ${pageNumbers(page.meta.page, totalPages).map((n) => `<button class="pager__num" data-act="page" data-page="${n}" ${n === page.meta.page ? 'aria-current="true"' : ''}>${n}</button>`).join('')}
          <button class="pager__num" data-act="page" data-page="${page.meta.page + 1}" ${page.meta.page >= totalPages ? 'disabled' : ''} aria-label="下一页">›</button>
        </div>
      </div>`}
    <div class="card__foot">
      <span>${icon('lock', 12)} 原始事实字段（时间/金额/方向/对方/商品）只读，仅分类与备注可编辑</span>
      <button class="link-btn" data-go="help">为什么？</button>
    </div>
  </section>`;

  return pageHead('流水明细', '全量流水查询与修正 · 筛选汇总与仪表盘、报表同口径', actions) + filterBar + table;
}

function pageNumbers(cur, total) {
  const out = [];
  const start = Math.max(1, Math.min(cur - 2, total - 4));
  const end = Math.min(total, start + 4);
  for (let i = start; i <= end; i++) out.push(i);
  return out;
}

export async function afterRender() {
  const q = document.querySelector('[data-filter="q"]');
  if (q && state.focusQ) {
    q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
    state.focusQ = false;
  }
}

export const actions = {
  reset: (_d, _el, ctx) => {
    Object.assign(state.filters, { direction: 'all', status: 'all', category_l1: '', category_l2: '', keyword: '', page: 1 });
    sel.clear();
    ctx.refresh();
  },
  dir: (data, _el, ctx) => {
    state.filters.direction = data.val;
    state.filters.page = 1;
    sel.clear();
    ctx.refresh();
  },
  sort: (data, _el, ctx) => {
    const f = state.filters;
    const desc = f.sort === `-${data.key}`;
    f.sort = desc ? data.key : `-${data.key}`;
    f.page = 1;
    ctx.refresh();
  },
  page: (data, _el, ctx) => {
    const n = Number(data.page);
    if (n < 1) return;
    state.filters.page = n;
    ctx.refresh();
  },
  'clear-sel': (_d, _el, ctx) => { sel.clear(); ctx.refresh(); },
  'open-tx': (data, _el, ctx) => openTransaction(data.id, { onChanged: () => ctx.refresh() }),
  export: (() => {
    return async (_d, _el, ctx) => {
      const page = await api.transactions(query({ page_size: 200 }));
      const head = ['交易时间', '方向', '金额(元)', '交易对方', '商品说明', '分类', '支付方式', '状态', '来源批次'];
      const lines = [head.join(',')];
      for (const t of page.items) {
        lines.push([
          fullDateTime(t.occurred_at), t.direction, (t.amount_cents / 100).toFixed(2),
          t.counterparty || '', t.item || '', t.category_l1 ? `${t.category_l1} · ${t.category_l2}` : '未分类',
          t.payment_method || '', t.status, t.batch_id,
        ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(','));
      }
      const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `流水明细-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
      toast(`已导出当前筛选下最多 200 条（共 ${page.meta.total} 条）`, 'ok');
    };
  })(),
  'bulk-cat': (_d, _el, ctx) => bulkModal(false, ctx),
  'bulk-rule': (_d, _el, ctx) => bulkModal(true, ctx),
};

async function bulkModal(createRule, ctx) {
  const nodes = await loadCategories();
  modal({
    title: createRule ? '批量归类并生成规则' : '批量修改分类',
    sub: `将对已选的 ${sel.size} 笔待确认流水生效`,
    body: `<div class="field" style="margin-bottom:14px">
        <label class="field__label">目标分类 <span class="req">*</span></label>
        <div class="select"><select class="select__native" data-field="cat"><option value="">请选择分类</option>${categoryOptions(nodes)}</select></div>
      </div>
      <label class="row" style="gap:10px;align-items:flex-start">
        <span class="switch" role="switch" aria-checked="${createRule}" data-act="toggle-rule"></span>
        <span><span class="small strong" style="display:block">同时生成规则</span>
          <span class="tiny muted">以后导入同对方流水时自动套用；已修正记录仍可被重算覆盖（需显式勾选）</span></span>
      </label>
      <div class="notice notice--info" style="margin-top:14px">
        <span class="notice__icon">${icon('info', 14)}</span>
        <div>归类后记录状态变为「已修正」，后续重算默认不覆盖。收支总额不变。</div>
      </div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--primary" data-act="ok">应用</button>`,
    acts: {
      cancel: () => closeLayer(),
      'toggle-rule': (el) => {
        const sw = el.querySelector('.switch');
        sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
      },
      ok: async (el) => {
        const v = fieldValue(el, 'cat');
        if (!v) return toast('请选择目标分类', 'warn');
        const [l1, l2] = v.split('||');
        const ruleOn = el.querySelector('.switch').getAttribute('aria-checked') === 'true';
        try {
          const res = await api.batchCategory({ ids: [...sel], l1, l2, create_rule: ruleOn });
          closeLayer();
          sel.clear();
          toast(`已处理 ${res.updated} 笔${res.rule_id ? '，规则已保存' : ''}`, 'ok');
          ctx.refresh();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
  });
}

/* 筛选控件事件（每次渲染后重新绑定） */
document.addEventListener('change', (e) => {
  if (window.__fdRoute !== 'detail') return;
  const el = e.target;
  if (el.dataset.filter === 'status') {
    state.filters.status = el.value;
    state.filters.page = 1;
    sel.clear();
    window.__fdRefresh?.();
  }
  if (el.dataset.filter === 'period') {
    state.filters.period = el.value;
    state.filters.page = 1;
    sel.clear();
    window.__fdRefresh?.();
  }
  if (el.dataset.filter === 'cat') {
    const v = el.value;
    if (v === '未分类') {
      state.filters.category_l1 = '';
      state.filters.category_l2 = '未分类';
    } else if (v.includes('||')) {
      const [l1, l2] = v.split('||');
      state.filters.category_l1 = l1;
      state.filters.category_l2 = l2;
    } else {
      state.filters.category_l1 = '';
      state.filters.category_l2 = '';
    }
    state.filters.page = 1;
    sel.clear();
    window.__fdRefresh?.();
  }
  if (el.dataset.act === 'sel-row') {
    if (el.checked) sel.add(el.dataset.id); else sel.delete(el.dataset.id);
    window.__fdRefresh?.();
  }
  if (el.dataset.act === 'sel-all') {
    sel.clear();
    if (el.checked) document.querySelectorAll('[data-act="sel-row"]').forEach((cb) => sel.add(cb.dataset.id));
    window.__fdRefresh?.();
  }
});

let qTimer = null;
document.addEventListener('input', (e) => {
  if (window.__fdRoute !== 'detail') return;
  if (e.target.dataset.filter !== 'q') return;
  const v = e.target.value;
  clearTimeout(qTimer);
  qTimer = setTimeout(() => {
    state.filters.keyword = v;
    state.filters.page = 1;
    state.focusQ = true;
    sel.clear();
    window.__fdRefresh?.();
  }, 320);
});
