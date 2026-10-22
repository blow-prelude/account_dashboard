/* 分类分析：一级（支出分组）→ 二级（消费大类）下钻。
   契约只定义两级分类（PRD 附录 B），原型的第三层「外卖 / 食堂」没有数据模型支撑，
   因此右侧改为「近 6 个月走势 + 该分类最近流水」，仍保持可下钻、可核对的用途。 */

import {api} from '../core/api.js';
import {anchor, state, sixtyMonths} from '../core/store.js';
import {card, pageHead, emptyState, stBadge} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, money, shortDateTime, deltaHtml} from '../core/format.js';
import {barBlocks} from '../core/charts.js';

const catLabel = (c) => c.l2 || c.l1;
const isUncat = (c) => c.l1 === '未分类';
const colorOf = (c, i) => (isUncat(c) ? 'var(--chart-8)' : `var(--chart-${(i % 7) + 1})`);

function filterOf(c) {
  return isUncat(c)
    ? { category_l2: '未分类' }
    : c.l2 ? { category_l2: c.l2 } : { category_l1: c.l1 };
}

export async function render() {
  const six = sixtyMonths();
  const [current, ...history] = await Promise.all([
    api.statsCategories({ period: state.period, anchor: anchor(), level: 2 }),
    ...six.map((m) => api.statsCategories({ period: 'month', anchor: m, level: 2 }).catch(() => [])),
  ]);

  const cats = current || [];
  const sel = cats.find((c) => catLabel(c) === state.analysisCat) || cats[0] || null;
  if (sel) state.analysisCat = catLabel(sel);

  const total = cats.reduce((s, c) => s + c.amount_cents, 0);
  const actions = `<div class="segmented" role="group" aria-label="统计周期">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${{ month: '本月', quarter: '本季度', year: '本年度' }[k]}</button>`).join('')}
    </div>
    <button class="btn btn--outline" data-act="to-detail">${icon('filter', 15)}在明细中筛选</button>`;

  const listCard = card({
    cls: 'card--flush',
    title: '支出分类',
    sub: `共 ${cats.length} 项 · 总支出 ${'¥' + money(total)}`,
    raw: cats.length ? `<div style="padding:8px 8px 12px">
      ${cats.map((c, i) => `<div class="cat cat-list--lg" style="padding:10px 12px;border-radius:10px;${sel && catLabel(c) === catLabel(sel) ? 'background:var(--primary-softer)' : ''}" data-act="pick-cat" data-name="${esc(catLabel(c))}">
        <div class="cat__top"><i class="legend__sw" style="background:${colorOf(c, i)}"></i>${esc(catLabel(c))}
          ${isUncat(c) ? '<span class="badge badge--warn" style="margin-left:4px">待处理</span>' : ''}</div>
        <div class="cat__val">${money(c.amount_cents)}<small>${fmt(c.ratio, 1)}% · ${c.mom == null ? '—' : (c.mom > 0 ? '+' : '') + fmt(c.mom, 1) + '%'}</small></div>
        <div class="cat__track"><div class="cat__fill" style="width:${Math.min(100, c.ratio)}%;background:${colorOf(c, i)}"></div></div>
      </div>`).join('')}
    </div>` : emptyState({ iconName: 'pie', title: '本期没有支出分类', desc: '导入账单后，这里会按金额排出分类。' }),
    foot: `<span>${icon('info', 12)} 分类归属不影响收支统计，统计以 direction 为准</span>`,
  });

  if (!sel) {
    return pageHead('分类分析', '按分类看支出结构与变化', actions)
      + `<div class="grid g-12"><div class="c-4">${listCard}</div><div class="c-8">${emptyState({ iconName: 'pie', title: '还没有可分析的分类', desc: '先导入一份账单，或换一个统计周期。' })}</div></div>`;
  }

  const series = six.map((m, idx) => {
    const found = (history[idx] || []).find((x) => (isUncat(sel) ? isUncat(x) : catLabel(x) === catLabel(sel)));
    return { label: `${Number(m.slice(5, 7))} 月`, value: found ? found.amount_cents / 100 : 0 };
  });

  const q = {
    ...filterOf(sel),
    period: state.period,
    anchor: anchor(),
    page: 1,
    page_size: 10,
    sort: '-occurred_at',
  };
  const recent = await api.transactions(q).catch(() => ({ items: [], meta: { total: 0 } }));
  const recentRows = recent.items.map((t) => `<tr data-act="open-tx" data-id="${esc(t.id)}" style="cursor:pointer">
      <td class="num" style="color:var(--text-3);font-size:12px">${shortDateTime(t.occurred_at)}</td>
      <td><div class="cell-2line"><span class="td-strong">${esc(t.counterparty || '—')}</span><small>${esc(t.item || '')}</small></div></td>
      <td class="td-muted">${esc(t.category_l1 ? `${t.category_l1} · ${t.category_l2 || ''}` : '未分类')}</td>
      <td>${stBadge(t.status)}</td>
      <td class="td-num td-strong">${money(t.amount_cents)}</td>
    </tr>`).join('');

  const detailCard = card({
    cls: 'card--flush',
    title: `${esc(catLabel(sel))} · 最近流水`,
    sub: `本期 ${fmt(sel.txn_count, 0)} 笔 · 占比 ${fmt(sel.ratio, 1)}%`,
    actions: `<button class="btn btn--soft btn--sm" data-act="to-detail">查看全部 ${icon('chevronR', 12)}</button>`,
    raw: recent.items.length ? `<div class="table-wrap"><table class="table">
        <thead><tr><th>时间</th><th>对方 / 商品</th><th>分类</th><th>状态</th><th class="right">金额</th></tr></thead>
        <tbody>${recentRows}</tbody></table></div>`
      : emptyState({ iconName: 'list', title: '该分类本期没有流水', desc: '换一个分类，或切换统计周期。' }),
    foot: `<span>点击任意一行查看详情与追溯来源</span><span class="tiny">共 ${recent.meta.total} 条</span>`,
  });

  const trendCard = card({
    title: '近 6 个月走势',
    sub: `${esc(catLabel(sel))} · 单位：元`,
    body: barBlocks(series, colorOf(sel, cats.indexOf(sel)))
      + `<p class="tiny muted" style="margin-top:10px">各月数值取自后端按月的分类统计，未在前端做二次聚合。</p>`,
  });

  const momBadge = sel.mom == null
    ? '<span class="badge badge--neutral">上期无数据</span>'
    : deltaHtml(sel.mom, { good: sel.mom <= 0, flag: sel.mom_flag });

  return pageHead('分类分析', '按分类看支出结构与变化，支持从分类下钻到流水', actions)
    + (cats.some(isUncat) ? `<div class="notice notice--warn" style="margin-bottom:16px">
        <span class="notice__icon">${icon('alert', 15)}</span>
        <div>「未分类」${money(cats.find(isUncat).amount_cents)}（${cats.find(isUncat).txn_count} 笔）单独列示，不计入任何具体分类，但计入总支出分母。
          <button class="link-btn" data-go="pending">批量处理 →</button></div>
      </div>` : '')
    + `<div class="grid g-12">
      <div class="c-4">${listCard}</div>
      <div class="c-8 stack">
        <section class="card"><div class="card__body">
          <div class="row" style="justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px">
            <div>
              <div class="section-label">当前分类</div>
              <div class="row" style="gap:10px;margin-top:6px">
                <b style="font-size:var(--t-xl)">${esc(catLabel(sel))}</b>
                <span class="badge badge--info badge--plain">${icon('tag', 11)}${esc(sel.l1)}</span>
                ${momBadge}
              </div>
            </div>
            <div style="text-align:right">
              <div class="section-label">本期金额</div>
              <div class="num" style="font-size:var(--t-2xl);color:var(--text-1)">${money(sel.amount_cents)}</div>
              <div class="tiny muted">${fmt(sel.txn_count, 0)} 笔 · 占比 ${fmt(sel.ratio, 1)}%</div>
            </div>
          </div>
          <div class="chart-strip" style="margin-top:16px;padding-top:14px;border-top:1px solid var(--border)">
            <div><dt>近 6 月峰值</dt><dd>${fmt(Math.max(...series.map((s) => s.value)), 0)}<small>元</small></dd></div>
            <div><dt>近 6 月合计</dt><dd>${fmt(series.reduce((a, b) => a + b.value, 0), 0)}<small>元</small></dd></div>
            <div><dt>最近一月</dt><dd>${fmt(series[series.length - 1].value, 0)}<small>元</small></dd></div>
          </div>
        </div></section>
        ${trendCard}
        ${detailCard}
      </div>
    </div>`;
}

export const actions = {
  'pick-cat': (data, _el, ctx) => { state.analysisCat = data.name; ctx.refresh(); },
  'to-detail': (_data, _el, ctx) => {
    const cats = document.querySelectorAll('[data-act="pick-cat"]');
    const name = state.analysisCat;
    state.filters.period = state.period;
    state.filters.page = 1;
    state.filters.category_l1 = '';
    state.filters.category_l2 = name || '';
    state.filters.keyword = '';
    state.filters.status = 'all';
    state.filters.direction = 'all';
    ctx.go('detail');
  },
  'open-tx': (data, _el, ctx) => ctx.openTx(data.id),
};
