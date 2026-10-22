/* 报表中心：月 / 季 / 年三视角复用同一套统计口径。 */

import {api} from '../core/api.js';
import {anchor, state, reportParams} from '../core/store.js';
import {card, pageHead, overviewBand, emptyState, toast} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, money, shortDateTime, deltaHtml} from '../core/format.js';
import {compareBars} from '../core/charts.js';

const TAB = { month: '月报', quarter: '季报', year: '年报' };
const TITLE = { month: '周度支出对比', quarter: '季度内各月对比', year: '全年各月对比' };

const catLabel = (c) => c.l2 || c.l1;

async function loadReport() {
  const p = reportParams();
  if (state.period === 'month') return api.monthlyReport(p);
  if (state.period === 'quarter') return api.quarterlyReport(p);
  return api.yearlyReport(p);
}

export async function render() {
  const [report, trend] = await Promise.all([
    loadReport(),
    api.statsTrend({
      period: state.period,
      anchor: anchor(),
      granularity: state.period === 'month' ? 'week' : 'month',
    }).catch(() => null),
  ]);

  const p = report.period;
  const cats = report.categories || [];
  const pending = report.pending || { count: 0, amount_cents: 0 };
  const total = cats.reduce((s, c) => s + c.amount_cents, 0);
  const actions = `<div class="segmented" role="group" aria-label="报表周期">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${TAB[k]}</button>`).join('')}
    </div>
    <button class="btn btn--outline" data-act="print">${icon('download', 15)}导出 PDF</button>
    <button class="btn btn--primary" data-act="refresh">${icon('file', 15)}刷新报表</button>`;

  const rows = cats.map((c, i) => {
    const color = c.l1 === '未分类' ? 'var(--chart-8)' : `var(--chart-${(i % 7) + 1})`;
    return `<tr data-act="open-cat" data-l1="${esc(c.l1)}" data-l2="${esc(c.l2 || '')}" style="cursor:pointer">
      <td><div class="cell-2line"><span class="td-strong">${esc(catLabel(c))}${c.l1 === '未分类' ? ' <span class="badge badge--warn" style="margin-left:6px">待处理</span>' : ''}</span>
        <div class="progress progress--sm" style="width:104px;margin-top:4px"><div class="progress__bar" style="width:${Math.min(100, c.ratio)}%;background:${color}"></div></div></div></td>
      <td class="td-num td-strong">${money(c.amount_cents)}</td>
      <td class="td-num">${fmt(c.txn_count, 0)}</td>
      <td class="td-num">${fmt(c.ratio, 1)}%</td>
      <td class="td-num">${deltaHtml(c.mom, { good: c.mom <= 0, flag: c.mom_flag })}</td>
    </tr>`;
  }).join('');

  const tableCard = card({
    cls: 'card--flush',
    title: '分类结构',
    sub: '金额 / 笔数 / 占比 / 环比，点击行可下钻到明细',
    actions: `<button class="btn btn--ghost btn--sm" data-go="analysis">下钻分析 ${icon('chevronR', 13)}</button>`,
    raw: cats.length
      ? `<div class="table-wrap"><table class="table">
          <thead><tr><th>分类</th><th class="right">金额</th><th class="right">笔数</th><th class="right">占比</th><th class="right">环比</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>`
      : emptyState({ iconName: 'reports', title: '本期没有支出分类', desc: '确认账单入库后，这里会按分类列出金额与占比。' }),
    foot: `<span>总支出 <b class="num" style="color:var(--text-1)">${cnyTotal(total)}</b> · 「未分类」计入分母</span>
      <span class="tiny">口径见帮助 · 收支口径说明</span>`,
  });

  const now = new Date();
  const labels = (trend?.points || []).map((x) => {
    if (trend.granularity === 'month') return `${Number(x.bucket.slice(5, 7))} 月`;
    return `${x.bucket.slice(5, 7)}/${x.bucket.slice(8, 10)}`;
  });
  const future = (trend?.points || []).map((x) => {
    if (trend.granularity !== 'month') return false;
    const [y, m] = x.bucket.split('-').map(Number);
    return y === now.getFullYear() && m > now.getMonth() + 1;
  });
  const expenseSeries = (trend?.points || []).map((x, i) => (future[i] ? null : x.expense_cents / 100));
  const incomeSeries = (trend?.points || []).map((x, i) => (future[i] ? null : x.income_cents / 100));

  const compareCard = card({
    cls: 'chart-card',
    title: TITLE[state.period],
    sub: state.period === 'year' ? '无数据的月份保留空位，不按 0 处理' : '同口径，单位：元',
    body: trend && trend.points.length
      ? (state.period === 'year'
        ? compareBars(labels, [
          { name: '收入', color: 'var(--chart-4)', values: incomeSeries },
          { name: '支出', color: 'var(--chart-1)', values: expenseSeries },
        ], { w: 430, h: 250, gap: 0.3 })
        : compareBars(labels, [{ name: '支出', color: 'var(--chart-1)', values: expenseSeries }], { w: 430, h: 250, gap: 0.34 }))
      : emptyState({ iconName: 'reports', title: '没有可对比的数据', desc: '本期区间内还没有收支记录。' }),
  });

  const summaryCard = card({
    title: '自动摘要',
    sub: '3–5 条结论，全部数字取自报表服务',
    body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:var(--s-6)">
        ${(report.summary_text || []).map((s) => `<div class="summary-item">${esc(s)}</div>`).join('') || '<span class="muted small">本期没有可总结的数据。</span>'}
      </div>`,
    foot: `<span>${icon('lock', 12)} 报表数据仅存本机，不上传任何外部服务</span>
      <span class="tiny">生成于 ${shortDateTime(report.generated_at)}</span>`,
  });

  return pageHead('报表中心', `月度 / 季度 / 年度三视角复用同一套统计口径 · ${p.label}`, actions)
    + (pending.count > 0 ? `<div class="notice notice--warn" style="margin-bottom:16px">
        <span class="notice__icon">${icon('alert', 15)}</span>
        <div>本期有 <b>${pending.count} 笔</b> 待确认（${money(pending.amount_cents)}），已计入总支出并单列「未分类」，处理后会同步刷新本页数字。
          <button class="link-btn" data-go="pending">去处理 →</button></div>
      </div>` : '')
    + overviewBand(p, report.kpi)
    + `<div class="grid g-12" style="margin-top:16px">
        <div class="c-7">${tableCard}</div>
        <div class="c-5">${compareCard}</div>
        <div class="c-12">${summaryCard}</div>
      </div>`;
}

const cnyTotal = (cents) => '¥' + money(cents);

export const actions = {
  print: () => window.print(),
  refresh: (_d, _el, ctx) => { ctx.refresh(); toast('报表已刷新', 'ok'); },
  'open-cat': (data, _el, ctx) => {
    state.filters.period = state.period;
    state.filters.page = 1;
    state.filters.category_l1 = data.l1 === '未分类' ? '' : data.l1;
    state.filters.category_l2 = data.l1 === '未分类' ? '未分类' : (data.l2 || '');
    state.filters.keyword = '';
    state.filters.status = 'all';
    state.filters.direction = 'all';
    ctx.go('detail');
  },
};
