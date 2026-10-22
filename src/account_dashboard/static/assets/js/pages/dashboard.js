/* 仪表盘：结论先行，全部数字来自 /stats/* 与 /reports/*，不做前端聚合。 */

import {api} from '../core/api.js';
import {anchor, state, reportParams} from '../core/store.js';
import {card, pageHead, overviewBand, emptyState, toast} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, money, cny, shortDateTime, dateOnly} from '../core/format.js';
import {trendArea, compareBars, donutChart} from '../core/charts.js';

const TAB = { month: '本月', quarter: '本季度', year: '本年度' };

function reportForPeriod() {
  const p = reportParams();
  if (state.period === 'month') return api.monthlyReport(p);
  if (state.period === 'quarter') return api.quarterlyReport(p);
  return api.yearlyReport(p);
}

const catLabel = (c) => c.l2 || c.l1;
const catColor = (c, i) => (['未分类', '其他'].includes(c.l1) ? 'var(--chart-8)' : `var(--chart-${(i % 7) + 1})`);

function granularityLabel(g) {
  return g === 'day' ? '按日' : g === 'week' ? '按周' : '按月';
}

function bucketLabel(bucket, g) {
  if (g === 'month') return `${Number(bucket.slice(5, 7))} 月`;
  return `${bucket.slice(5, 7)}/${bucket.slice(8, 10)}`;
}

export async function render() {
  const [overview, backup, report, threshold] = await Promise.all([
    api.overview(state.period, anchor()),
    api.backup.list().catch(() => null),
    reportForPeriod().catch(() => null),
    api.dailyThreshold({ period: state.period, anchor: anchor() }).catch(() => null),
  ]);

  const p = overview.period;
  const kpi = overview.kpi;
  const trend = overview.trend;
  const cats = overview.category_top || [];
  const totalExpense = cats.reduce((s, c) => s + c.amount_cents, 0);
  const topMerchants = overview.top_counterparties || [];
  const maxTop = Math.max(...topMerchants.map((t) => t.amount_cents), 1);

  const actions = `<div class="segmented" role="group" aria-label="统计周期">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${TAB[k]}</button>`).join('')}
    </div>
    <button class="icon-btn icon-btn--bordered" data-act="refresh" aria-label="刷新">${icon('refresh', 16)}</button>
    <button class="btn btn--primary" data-go="import">${icon('upload', 15)}导入账单</button>`;

  const notices = [];
  if (kpi.pending_count > 0) {
    notices.push(`<div class="notice notice--warn">
      <span class="notice__icon">${icon('alert', 15)}</span>
      <div>有 <b>${kpi.pending_count} 笔</b> 待确认（合计 <b>${cny(kpi.uncategorized_cents)}</b>），已计入总支出并在分类中单列「未分类」。
        <button class="link-btn" data-go="pending">去处理 →</button></div>
    </div>`);
  }
  if (backup) {
    if (!backup.last_at) {
      notices.push(`<div class="notice notice--warn"><span class="notice__icon">${icon('shield', 15)}</span>
        <div>还没有任何数据库备份。建议先做一次备份，再开始长期记账。
          <button class="link-btn" data-go="backup">立即备份 →</button></div></div>`);
    } else if (backup.overdue) {
      notices.push(`<div class="notice notice--warn"><span class="notice__icon">${icon('shield', 15)}</span>
        <div>距上次备份已超过 <b>${backup.interval_days} 天</b>，备份文件只存本机，请及时更新。
          <button class="link-btn" data-go="backup">去备份 →</button></div></div>`);
    }
  }

  /* 趋势图：年度用收支分组柱，月/季用支出面积 + 收入到账标注 */
  const labels = trend.points.map((x) => bucketLabel(x.bucket, trend.granularity));
  const expenseYuan = trend.points.map((x) => x.expense_cents / 100);
  const incomeYuan = trend.points.map((x) => x.income_cents / 100);
  let chart;
  if (state.period === 'year') {
    chart = compareBars(labels, [
      { name: '收入', color: 'var(--chart-4)', values: incomeYuan },
      { name: '支出', color: 'var(--chart-1)', values: expenseYuan },
    ], { h: 250, gap: 0.34 });
  } else {
    const marks = trend.points
      .map((x, i) => ({ i, value: x.income_cents / 100, ok: x.income_cents >= 50000 }))
      .filter((x) => x.ok)
      .slice(0, 4)
      .map((x) => ({ i: x.i, value: x.value }));
    chart = trendArea({
      labels, values: expenseYuan, marks,
      title: state.period === 'month' ? '每日支出趋势' : '每周支出趋势',
      id: `t-${state.period}`,
    });
  }

  const trendCard = card({
    cls: 'chart-card',
    title: state.period === 'year' ? '每月收支' : '支出趋势',
    sub: `${dateOnly(p.start)} ~ ${dateOnly(p.end)} · 粒度：${granularityLabel(trend.granularity)}`,
    actions: `<div class="chart-legend">
      ${state.period === 'year'
        ? `<span><i style="background:var(--chart-4)"></i>收入</span><span><i style="background:var(--chart-1)"></i>支出</span>`
        : `<span><i style="background:var(--chart-1)"></i>支出</span><span><i style="background:var(--chart-4)"></i>收入到账</span>`}
    </div>`,
    body: `${chart}<div class="chart-strip">
        <div><dt>统计区间</dt><dd style="font-family:var(--font-ui);font-size:var(--text-xs)">${dateOnly(p.start)} ~ ${dateOnly(p.end)}<small>${p.days} 天</small></dd></div>
        <div><dt>数据点</dt><dd>${trend.points.length}<small>${granularityLabel(trend.granularity)}</small></dd></div>
        <div><dt>超单日阈值</dt><dd>${threshold ? threshold.days.length : '—'}<small>天</small></dd></div>
        <div style="margin-left:auto;align-self:flex-end"><dt>统计来源</dt>
          <dd style="font-family:var(--font-ui);font-size:var(--t-xs);color:var(--text-3)">后端 stats-service</dd></div>
      </div>`,
  });

  const uncat = cats.find((c) => c.l1 === '未分类');
  const named = cats.filter((c) => c.l1 !== '未分类');
  const top5 = named.slice(0, 5);
  const rest = named.slice(5);
  const restSum = rest.reduce((s, c) => s + c.amount_cents, 0);
  const donutItems = cats.map((c, i) => ({ name: catLabel(c), value: c.amount_cents / 100, color: catColor(c, i) }));
  const donutCard = card({
    cls: 'chart-card',
    title: '支出结构',
    sub: `共 ${cats.length} 个分类 · 未分类单列`,
    actions: `<button class="btn btn--ghost btn--sm" data-go="analysis">分类分析 ${icon('chevronR', 13)}</button>`,
    body: cats.length ? `<div class="donut-wrap">
      <div class="donut" style="max-width:196px;margin:0 auto">${donutChart(donutItems, totalExpense / 100, fmt(totalExpense / 100, 0))}</div>
      <div class="legend">
        ${top5.map((c, i) => `<div class="legend__row" data-go="analysis">
          <i class="legend__sw" style="background:${catColor(c, i)}"></i>
          <span class="legend__name">${esc(catLabel(c))}</span>
          <span class="legend__val">${money(c.amount_cents)}</span>
          <span class="legend__pct">${fmt(c.ratio, 1)}%</span>
        </div>`).join('')}
        ${rest.length ? `<div class="legend__row" data-go="analysis">
          <i class="legend__sw" style="background:var(--chart-8)"></i>
          <span class="legend__name muted">其他 ${rest.length} 项</span>
          <span class="legend__val">${money(restSum)}</span>
          <span class="legend__pct">${fmt(totalExpense ? (restSum / totalExpense) * 100 : 0, 1)}%</span>
        </div>` : ''}
        ${uncat ? `<div class="legend__row" data-go="pending">
          <i class="legend__sw" style="background:var(--chart-8)"></i>
          <span class="legend__name">未分类 <span class="tiny muted">待处理</span></span>
          <span class="legend__val">${money(uncat.amount_cents)}</span>
          <span class="legend__pct">${fmt(uncat.ratio, 1)}%</span>
        </div>` : ''}
      </div>
    </div>` : emptyState({ iconName: 'pie', title: '本期还没有支出记录', desc: '导入账单后，这里会按分类展示支出结构。' }),
  });

  const topCard = card({
    title: 'Top 5 商户',
    sub: '按支出金额排序，含笔数',
    actions: `<button class="btn btn--ghost btn--sm" data-go="detail">查看明细 ${icon('chevronR', 13)}</button>`,
    body: topMerchants.length ? topMerchants.map((t, i) => `<div class="merchant">
        <span class="merchant__idx">${i + 1}</span>
        <span class="merchant__name">${esc(t.counterparty)}</span>
        <span class="merchant__bar"><i style="width:${((t.amount_cents / maxTop) * 100).toFixed(0)}%"></i></span>
        <span class="merchant__amt">${money(t.amount_cents)}</span>
        <span class="merchant__cnt">${t.txn_count} 笔</span>
      </div>`).join('') : emptyState({ iconName: 'list', title: '本期没有支出商户', desc: '有支出流水后，这里会按金额排出前 5 名。' }),
    foot: `<span>统计口径与报表、明细页一致</span><span class="tiny">更新于 ${shortDateTime(overview.generated_at)}</span>`,
  });

  const summaryText = report?.summary_text || [];
  const summaryCard = card({
    title: '本期结论',
    sub: '由报表服务生成，非前端拼接',
    actions: `<span class="badge badge--plain badge--info">${icon('sparkles', 12)}自动摘要</span>`,
    body: summaryText.length
      ? `<div class="summary-list">${summaryText.map((s, i) => `<div class="summary-item"><b>${String(i + 1).padStart(2, '0')}</b>　${esc(s)}</div>`).join('')}</div>`
      : emptyState({ iconName: 'sparkles', title: '本期还没有可总结的数据', desc: '导入并确认账单后，摘要会随报表一起生成。' }),
    foot: `<span>${icon('info', 12)} 结论基于 direction 口径；neutral 记录不计入任何收支。</span>`,
  });

  return pageHead('仪表盘', `一页看清本期的钱花在哪 · ${p.label}（${dateOnly(p.start)} ~ ${dateOnly(p.end)}）`, actions)
    + (notices.length ? `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr));margin-bottom:16px">${notices.slice(0, 2).join('')}</div>` : '')
    + overviewBand(p, kpi)
    + `<div class="grid g-12 g-fill" style="margin-top:16px">
        <div class="c-8">${trendCard}</div>
        <div class="c-4">${donutCard}</div>
        <div class="c-7">${summaryCard}</div>
        <div class="c-5">${topCard}</div>
      </div>`;
}

export const actions = {
  refresh: async (_d, _el, ctx) => {
    ctx.refresh();
    toast('已重新拉取统计结果', 'ok');
  },
};
