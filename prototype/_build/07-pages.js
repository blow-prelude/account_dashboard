/* ============================================================
   07 · 页面渲染
   ============================================================ */

const CMP = {
  month: {
    labels: ['第 1 周', '第 2 周', '第 3 周'],
    series: [{ name: '支出', color: 'var(--chart-1)', values: [318.4, 462.1, 706.0] }],
  },
  quarter: {
    labels: ['7 月', '8 月', '9 月'],
    series: [
      { name: '收入', color: 'var(--chart-4)', values: [2050, 1800, 2200] },
      { name: '支出', color: 'var(--chart-1)', values: [1480, 1420, 1483] },
    ],
  },
  year: {
    labels: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],
    series: [
      { name: '收入', color: 'var(--chart-4)', values: [1700,1680,1750,1700,1760,1800,2310,1800,2200,2000,null,null] },
      { name: '支出', color: 'var(--chart-1)', values: [1500,1320,1410,1380,1450,1290,1480,1420,1483,1486.3,null,null] },
    ],
  },
};

const dch = (d) => {
  if (!d) return '';
  const arrow = d.v > 0 ? '▲' : d.v < 0 ? '▼' : '—';
  const cls = d.v === 0 ? 'flat' : d.good ? 'green' : 'red';
  return `<span class="delta delta--${cls}">${arrow}${fmt(Math.abs(d.v), 1)}${d.unit === 'pt' ? ' pt' : '%'}</span>`;
};

const bigMoney = (n) => {
  const [i, d] = fmt(n).split('.');
  return `<span class="cur">¥</span>${i}<span style="font-size:.6em;color:var(--text-3);margin-left:1px">.${d}</span>`;
};

function card(o) {
  return `<section class="card ${o.cls || ''}">
    ${o.title ? `<div class="card__head ${o.headPlain ? 'card__head--plain' : ''}">
      <div><div class="card__title">${o.title}</div>${o.sub ? `<div class="card__sub">${o.sub}</div>` : ''}</div>
      <div class="spacer"></div>${o.actions || ''}
    </div>` : ''}
    ${o.raw !== undefined ? o.raw : (o.body !== undefined ? `<div class="card__body ${o.bodyCls || ''}">${o.body}</div>` : '')}
    ${o.foot ? `<div class="card__foot">${o.foot}</div>` : ''}
  </section>`;
}

function pageHead(title, sub, actions) {
  return `<div class="page-head">
    <div><h1 class="page-head__title">${title}</h1>${sub ? `<p class="page-head__sub">${sub}</p>` : ''}</div>
    <div class="page-head__actions">${actions || ''}</div>
  </div>`;
}

function overview(p) {
  return `<section class="overview">
    <div class="overview__main">
      <div class="overview__eyebrow">本期结余 · ${p.title}</div>
      <div class="overview__value">${bigMoney(p.balance)}</div>
      <div class="overview__meta">
        <span class="badge badge--info badge--plain">储蓄率 ${fmt(p.saving, 1)}%</span>
        <span class="small muted">较上期 ${dch(p.d.balance)}</span>
        <span class="hr--v"></span>
        <span class="small muted">总收入 − 总支出</span>
      </div>
    </div>
    <div class="overview__stats">
      <div class="ostat">
        <div class="ostat__k"><i class="dot-k" style="background:var(--fin-down)"></i>总收入</div>
        <div class="ostat__v">${fmt(p.income)} ${dch(p.d.income)}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k"><i class="dot-k" style="background:var(--fin-up)"></i>总支出</div>
        <div class="ostat__v">${fmt(p.expense)} ${dch(p.d.expense)}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k">${icon('sparkles', 12)}储蓄率</div>
        <div class="ostat__v">${fmt(p.saving, 1)}<small>%</small> ${dch(p.d.saving)}</div>
      </div>
      <div class="ostat">
        <div class="ostat__k">${icon('clock', 12)}日均支出</div>
        <div class="ostat__v">${fmt(p.avg)} ${dch(p.d.avg)}</div>
      </div>
    </div>
  </section>`;
}

/* ---------------- 1. 仪表盘 ---------------- */
function pageDashboard() {
  const p = P[state.period];
  const total = p.donut.reduce((a, b) => a + b.value, 0);
  const maxTop = Math.max(...p.top.map((t) => t.amount));
  const actions = `<div class="segmented" role="group" aria-label="统计周期">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${P[k].tab}</button>`).join('')}
    </div>
    <button class="icon-btn icon-btn--bordered" data-act="toast" data-msg="已从后端 /stats/overview 重新拉取" aria-label="刷新">${icon('refresh', 16)}</button>
    <button class="btn btn--primary" data-go="import">${icon('upload', 15)}导入账单</button>`;

  const notices = `<div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
    <div class="notice notice--warn">
      <span class="notice__icon">${icon('alert', 15)}</span>
      <div>有 <b>${p.pending.count} 笔</b> 待确认（合计 <b>¥${fmt(p.pending.amount)}</b>），已计入总支出并在分类中单列「未分类」。
        <button class="link-btn" data-go="pending">去处理 →</button></div>
    </div>
    <div class="notice notice--info">
      <span class="notice__icon">${icon('shield', 15)}</span>
      <div>距上次备份已 <b>9 天</b>，超过设定的 7 天提醒间隔。
        <button class="link-btn" data-go="backup">立即备份 →</button></div>
    </div>
  </div>`;

  const tvals = p.trend.expense.filter((v) => v != null);
  const tmax = Math.max(...tvals);
  const tmaxLabel = p.trend.labels[p.trend.expense.indexOf(tmax)];
  const tavg = tvals.reduce((a, b) => a + b, 0) / tvals.length;
  const tmed = [...tvals].sort((a, b) => a - b)[Math.floor(tvals.length / 2)];
  const trend = card({
    cls: 'chart-card',
    title: '支出趋势',
    sub: `${p.range} · 粒度：${state.period === 'month' ? '按日' : state.period === 'quarter' ? '按周' : '按月'}`,
    actions: `<div class="chart-legend">
        <span><i style="background:var(--chart-1)"></i>支出</span>
        <span><i style="background:var(--chart-4)"></i>收入到账</span>
      </div>`,
    body: trendChart(p, state.period) + `<div class="chart-strip">
        <div><dt>${state.period === 'month' ? '单日最高' : state.period === 'quarter' ? '单周最高' : '单月最高'}</dt>
          <dd>${fmt(tmax)}<small>${tmaxLabel}</small></dd></div>
        <div><dt>平均</dt><dd>${fmt(tavg)}</dd></div>
        <div><dt>中位数</dt><dd>${fmt(tmed)}</dd></div>
        <div style="margin-left:auto;align-self:flex-end"><dt>统计来源</dt>
          <dd style="font-family:var(--font-ui);font-size:var(--t-xs);color:var(--text-3)">后端 stats-service</dd></div>
      </div>`,
  });

  const top5 = p.donut.slice(0, 5);
  const restItems = p.donut.slice(5);
  const restSum = restItems.reduce((a, b) => a + b.value, 0);
  const donut = card({
    cls: 'chart-card',
    title: '支出结构',
    sub: `共 ${p.donut.length} 个分类 · 未分类单列`,
    actions: `<button class="btn btn--ghost btn--sm" data-go="analysis">分类分析 ${icon('chevronR', 13)}</button>`,
    body: `<div class="donut-wrap">
      <div class="donut" style="max-width:196px;margin:0 auto">${donutChart(p.donut, total, fmt(total, 0))}</div>
      <div class="legend">
        ${top5.map((d) => `<div class="legend__row" data-go="analysis">
          <i class="legend__sw" style="background:${d.color}"></i>
          <span class="legend__name">${d.name}</span>
          <span class="legend__val">${fmt(d.value)}</span>
          <span class="legend__pct">${((d.value / total) * 100).toFixed(1)}%</span>
        </div>`).join('')}
        ${restItems.length ? `<div class="legend__row" data-go="analysis">
          <i class="legend__sw" style="background:var(--chart-8)"></i>
          <span class="legend__name muted">其他 ${restItems.length} 项</span>
          <span class="legend__val">${fmt(restSum)}</span>
          <span class="legend__pct">${((restSum / total) * 100).toFixed(1)}%</span>
        </div>` : ''}
      </div>
    </div>`,
  });

  const top = card({
    title: 'Top 5 商户',
    sub: '按支出金额排序，含笔数',
    actions: `<button class="btn btn--ghost btn--sm" data-go="detail">查看明细 ${icon('chevronR', 13)}</button>`,
    body: p.top.map((t, i) => `<div class="merchant">
        <span class="merchant__idx">${i + 1}</span>
        <span class="merchant__name">${t.name}</span>
        <span class="merchant__bar"><i style="width:${((t.amount / maxTop) * 100).toFixed(0)}%"></i></span>
        <span class="merchant__amt">${fmt(t.amount)}</span>
        <span class="merchant__cnt">${t.count} 笔</span>
      </div>`).join(''),
    foot: `<span>统计口径与报表、明细页一致</span><span class="tiny">更新于 10-21 21:35</span>`,
  });

  const summary = card({
    title: '本期结论',
    sub: '由统计服务生成，非前端拼接',
    actions: `<span class="badge badge--plain badge--info">${icon('sparkles', 12)}自动摘要</span>`,
    body: `<div class="summary-list">${p.summary.map((s) => `<div class="summary-item">${s}</div>`).join('')}</div>`,
    foot: `<span>${icon('info', 12)} 结论基于 direction 口径；neutral 记录不计入任何收支。</span>`,
  });

  return pageHead('仪表盘', `一页看清本期的钱花在哪 · ${p.title}（${p.range}）`, actions) + notices + overview(p) +
    `<div class="grid g-12 g-fill" style="margin-top:16px">
      <div class="c-8">${trend}</div>
      <div class="c-4">${donut}</div>
      <div class="c-7">${summary}</div>
      <div class="c-5">${top}</div>
    </div>`;
}

/* ---------------- 2. 报表中心 ---------------- */
function pageReports() {
  const p = P[state.period];
  const total = p.donut.reduce((a, b) => a + b.value, 0);
  const actions = `<div class="segmented" role="group" aria-label="报表周期">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${P[k].tab}</button>`).join('')}
    </div>
    <button class="btn btn--outline" data-act="toast" data-msg="已生成 PDF（示例）">${icon('download', 15)}导出 PDF</button>
    <button class="btn btn--primary" data-act="toast" data-msg="已复制分享链接（本机）">${icon('file', 15)}生成报表</button>`;

  const rows = ANALYSIS.map((a) => `<tr>
      <td><div class="cell-2line"><span class="td-strong">${a.l1}${a.pending ? ' <span class="badge badge--warn" style="margin-left:6px">待处理</span>' : ''}</span>
        <div class="progress progress--sm" style="width:104px;margin-top:4px"><div class="progress__bar" style="width:${a.pct}%;background:${a.color}"></div></div></div></td>
      <td class="td-num td-strong">${fmt(a.amount)}</td>
      <td class="td-num">${fmt(a.pct, 1)}%</td>
      <td class="td-num">${a.mom === 0 ? '<span class="muted">—</span>' : dch({ v: a.mom, good: a.mom < 0 })}</td>
    </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: '分类结构',
    sub: '金额 / 占比 / 环比，点击行可下钻',
    actions: `<button class="btn btn--ghost btn--sm" data-go="analysis">下钻分析 ${icon('chevronR', 13)}</button>`,
    raw: `<div class="table-wrap"><table class="table">
        <thead><tr><th>一级分类</th><th class="right">金额</th><th class="right">占比</th><th class="right">环比</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`,
    foot: `<span>总支出 <b class="num" style="color:var(--text-1)">¥${fmt(total)}</b> · 「未分类」计入分母</span>
      <span class="tiny">口径见帮助 · 收支口径说明</span>`,
  });

  const cmp = card({
    cls: 'chart-card',
    title: state.period === 'month' ? '周度支出对比' : state.period === 'quarter' ? '季度内各月对比' : '全年各月对比',
    sub: state.period === 'year' ? '11–12 月无数据，显示为空位' : '同口径，单位：元',
    body: compareBars(CMP[state.period].labels, CMP[state.period].series, { w: 420, h: 250 }),
  });

  const sum = card({
    title: '自动摘要',
    sub: '3–5 条结论，全部数字取自后端统计服务',
    body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:var(--s-6)">
        ${p.summary.map((s) => `<div class="summary-item">${s}</div>`).join('')}
      </div>`,
    foot: `<span>${icon('lock', 12)} 报表数据仅存本机，不上传任何外部服务</span>
      <span class="tiny">生成于 2026-10-22 20:07</span>`,
  });

  return pageHead('报表中心', `月度 / 季度 / 年度三视角复用同一套统计口径 · ${p.title}`, actions) +
    `<div class="notice notice--warn" style="margin-bottom:16px">
      <span class="notice__icon">${icon('alert', 15)}</span>
      <div>本期有 <b>${p.pending.count} 笔</b> 待确认（¥${fmt(p.pending.amount)}），已计入总支出并单列「未分类」，处理后会同步刷新本页数字。</div>
    </div>` +
    overview(p) +
    `<div class="grid g-12" style="margin-top:16px">
      <div class="c-7">${table}</div>
      <div class="c-5">${cmp}</div>
      <div class="c-12">${sum}</div>
    </div>`;
}

/* ---------------- 3. 分类分析 ---------------- */
function pageAnalysis() {
  const sel = state.cat || '餐饮美食';
  const cur = ANALYSIS.find((a) => a.l1 === sel) || ANALYSIS[0];
  const total = P.month.expense;
  const actions = `<div class="segmented" role="group">
      ${['month', 'quarter', 'year'].map((k) => `<button class="segmented__item" data-period="${k}"
        aria-pressed="${state.period === k}">${P[k].tab}</button>`).join('')}
    </div>
    <button class="btn btn--outline" data-go="detail">${icon('filter', 15)}在明细中筛选</button>`;

  const list = card({
    cls: 'card--flush',
    title: '一级分类',
    sub: `总支出 ¥${fmt(total)}`,
    raw: `<div style="padding:8px 8px 12px">
      ${ANALYSIS.map((a) => `<div class="cat cat-list--lg" style="padding:10px 12px;border-radius:10px;${a.l1 === sel ? 'background:var(--primary-softer)' : ''}" data-cat="${a.l1}">
        <div class="cat__top"><i class="legend__sw" style="background:${a.color}"></i>${a.l1}
          ${a.pending ? '<span class="badge badge--warn" style="margin-left:4px">待处理</span>' : ''}</div>
        <div class="cat__val">${fmt(a.amount)}<small>${fmt(a.pct, 1)}% · ${a.mom === 0 ? '—' : (a.mom > 0 ? '+' : '') + a.mom + '%'}</small></div>
        <div class="cat__track"><div class="cat__fill" style="width:${a.pct}%;background:${a.color}"></div></div>
      </div>`).join('')}
    </div>`,
    foot: `<span>${icon('info', 12)} 分类归属不影响收支统计，统计以 direction 为准</span>`,
  });

  const detail = card({
    cls: 'card--flush',
    title: `${cur.l1} · 二级结构`,
    sub: `占总支出的 ${fmt(cur.pct, 1)}% · 环比 ${cur.mom === 0 ? '—' : (cur.mom > 0 ? '↑' : '↓') + Math.abs(cur.mom) + '%'}`,
    actions: `<button class="btn btn--soft btn--sm" data-go="detail">查看这 ${cur.l2.length} 个分类的流水</button>`,
    raw: `<div class="table-wrap"><table class="table">
        <thead><tr><th>二级分类</th><th class="right">金额</th><th class="right">占比</th><th class="right">环比</th><th style="width:140px">趋势</th></tr></thead>
        <tbody>${cur.l2.map(([n, v, pct, mom]) => `<tr>
          <td class="td-strong">${n}</td>
          <td class="td-num">${fmt(v)}</td>
          <td class="td-num">${fmt(pct, 1)}%</td>
          <td class="td-num">${mom === 0 ? '<span class="muted">—</span>' : dch({ v: mom, good: mom < 0 })}</td>
          <td>${spark([v * 0.7, v * 0.86, v * 0.62, v * 0.94, v * 0.8, v], cur.color, 120, 26)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`,
    foot: `<span>近 6 个月该分类走势见行内迷你图（右端为本期）</span>`,
  });

  const ratios = [0.72, 0.88, 0.64, 0.96, 0.82, 1];
  const months6 = ['5月', '6月', '7月', '8月', '9月', '10月'];
  const trend = card({
    title: '近 6 个月走势',
    sub: `${cur.l1} · 单位：元`,
    body: barBlocks(ratios.map((r, i) => ({ label: months6[i], value: cur.amount * r })), cur.color) +
      `<p class="tiny muted" style="margin-top:10px">本学期内 ${cur.l1} 的波动主要出现在开学与假期节点，9 月为峰值。</p>`,
  });

  return pageHead('分类分析', '按分类看支出结构与变化，支持从一级下钻到二级', actions) +
    (ANALYSIS.some((a) => a.pending) ? `<div class="notice notice--warn" style="margin-bottom:16px">
      <span class="notice__icon">${icon('alert', 15)}</span>
      <div>「未分类」¥81.00（4 笔）单独列示，不计入任何具体分类，但计入总支出分母。<button class="link-btn" data-go="pending">批量处理 →</button></div>
    </div>` : '') +
    `<div class="grid g-12">
      <div class="c-4">${list}</div>
      <div class="c-8 stack">${detail}${trend}</div>
    </div>`;
}

/* ---------------- 4. 流水明细 ---------------- */
function txRows() {
  const f = state.txFilter;
  const list = TX.filter((t) => {
    if (f.status !== 'all' && t.status !== f.status) return false;
    if (f.dir !== 'all' && t.dir !== f.dir) return false;
    if (f.cat !== 'all' && f.cat !== '全部分类' && !t.l2.startsWith(f.cat)) return false;
    if (f.q && !(t.cp + t.item + t.l2).toLowerCase().includes(f.q.toLowerCase())) return false;
    return true;
  });
  const dir = state.sort.dir === 'asc' ? 1 : -1;
  return list.sort((a, b) => {
    if (state.sort.key === 'amt') return (Math.abs(a.amt) - Math.abs(b.amt)) * dir;
    return a.time.localeCompare(b.time) * dir;
  });
}

function pageDetail() {
  const f = state.txFilter;
  const rows = txRows();
  const filtered = f.status !== 'all' || f.dir !== 'all' || !!f.q || (f.cat !== 'all' && f.cat !== '全部分类');
  const sumExpense = filtered
    ? rows.filter((t) => t.dir === 'expense' && t.status !== 'excluded').reduce((a, b) => a + Math.abs(b.amt), 0)
    : P.month.expense;
  const sumIncome = filtered
    ? rows.filter((t) => t.dir === 'income').reduce((a, b) => a + b.amt, 0)
    : P.month.income;
  const count = filtered ? rows.length : 128;
  const sel = state.txSel || new Set();

  const actions = `<button class="btn btn--outline" data-act="toast" data-msg="已导出为 CSV（示例）">${icon('download', 15)}导出</button>
    <button class="btn btn--primary" data-go="import">${icon('plus', 15)}导入</button>`;

  const filter = `<section class="card card--flush">
    <div class="filterbar">
      <div class="select select--sm" style="width:132px"><select class="select__native" data-filter="range">
        <option>本月（10-01 ~ 21）</option><option>近 3 个月</option><option>本年度</option><option>自定义…</option>
      </select></div>
      <div class="select select--sm" style="width:150px"><select class="select__native" data-filter="cat">
        <option>全部分类</option>${ANALYSIS.map((a) => `<option>${a.l1}</option>`).join('')}
      </select></div>
      <div class="row" style="gap:6px">
        ${[['all', '全部'], ['expense', '支出'], ['income', '收入'], ['neutral', '中性']].map(([k, t]) =>
          `<button class="chip" data-filter="dir" data-val="${k}" aria-pressed="${f.dir === k}">${t}</button>`).join('')}
      </div>
      <div class="select select--sm" style="width:132px"><select class="select__native" data-filter="status">
        <option value="all">全部状态</option>
        <option value="confirmed" ${f.status === 'confirmed' ? 'selected' : ''}>已分类</option>
        <option value="corrected" ${f.status === 'corrected' ? 'selected' : ''}>已修正</option>
        <option value="pending" ${f.status === 'pending' ? 'selected' : ''}>待确认</option>
        <option value="excluded" ${f.status === 'excluded' ? 'selected' : ''}>已排除</option>
      </select></div>
      <div class="input-group">
        <span class="input-group__icon">${icon('search', 15)}</span>
        <input class="input" placeholder="搜索对方 / 商品说明" value="${f.q}" data-filter="q" style="height:30px;font-size:13px">
      </div>
      <div class="filterbar__more">
        <button class="btn btn--ghost btn--sm" data-act="reset-filter">${icon('refresh', 13)}重置</button>
        <span class="tiny muted">${rows.length} / ${TX.length} 条</span>
      </div>
    </div>
    <div class="summary-strip">
      <span>${filtered ? '筛选结果' : '本期合计'}<b>${count}</b>笔</span><i class="sep"></i>
      <span>支出<b>¥${fmt(sumExpense)}</b></span><i class="sep"></i>
      <span>收入<b>¥${fmt(sumIncome)}</b></span><i class="sep"></i>
      <span>净额<b>¥${fmt(sumIncome - sumExpense)}</b></span>
      <span class="badge badge--ok" style="margin-left:auto">${icon('check', 11)}与月报同口径</span>
    </div>
    ${sel.size ? `<div class="bulkbar">
      <span class="bulkbar__count">已选 <b>${sel.size}</b> 笔</span>
      <span class="small" style="opacity:.7">按对方批量套用分类，并可直接生成规则</span>
      <div class="spacer"></div>
      <button class="btn btn--ghost btn--sm" data-act="clear-sel">取消</button>
      <button class="btn btn--outline btn--sm" data-act="bulk-cat">批量改分类</button>
      <button class="btn btn--primary btn--sm" data-act="bulk-rule">生成规则</button>
    </div>` : ''}
  </section>`;

  const table = `<section class="card card--flush" style="margin-top:16px">
    <div class="table-wrap"><table class="table">
      <thead><tr>
        <th style="width:36px"><label class="checkbox"><input type="checkbox" data-act="sel-all" ${rows.length && rows.every((r) => sel.has(r.id)) ? 'checked' : ''}><span class="checkbox__box"></span></label></th>
        <th class="is-sortable" data-sort="time">时间 <span class="sort-ind">↕</span></th>
        <th>对方 / 商品说明</th>
        <th>分类</th>
        <th>方向</th>
        <th>支付方式</th>
        <th>来源批次</th>
        <th>状态</th>
        <th class="right is-sortable" data-sort="amt">金额 <span class="sort-ind">↕</span></th>
      </tr></thead>
      <tbody>${rows.map((t) => `<tr data-id="${t.id}" class="${sel.has(t.id) ? 'is-selected' : ''}">
        <td><label class="checkbox" onclick="event.stopPropagation()"><input type="checkbox" data-act="sel-row" data-id="${t.id}" ${sel.has(t.id) ? 'checked' : ''}><span class="checkbox__box"></span></label></td>
        <td class="num" style="color:var(--text-3);font-size:12px">${t.time}</td>
        <td><div class="cell-2line"><span class="td-strong">${t.cp}</span><small>${t.item}</small></div></td>
        <td><span class="cell-edit" data-act="open-tx" data-id="${t.id}">${t.l2}${icon('edit', 11)}</span></td>
        <td>${t.dir === 'neutral' ? '<span class="badge badge--neutral">中性</span>' : t.dir === 'income' ? '<span class="badge badge--ok">收入</span>' : '<span class="badge badge--plain" style="background:var(--surface-3)">支出</span>'}</td>
        <td class="td-muted">${t.method}</td>
        <td class="td-muted mono">${t.batch}</td>
        <td>${stBadge(t.status)}</td>
        <td class="td-num td-strong" style="color:${t.dir === 'neutral' ? 'var(--text-3)' : t.amt > 0 ? 'var(--fin-down)' : 'var(--text-1)'}">${t.amt > 0 ? '+' : '−'}${fmt(Math.abs(t.amt))}</td>
      </tr>`).join('')}</tbody>
    </table></div>
    ${rows.length === 0 ? `<div class="empty">
        <div class="empty__art">${icon('search', 30)}</div>
        <div class="empty__title">没有符合条件的流水</div>
        <div class="empty__desc">试着重置筛选，或换一个关键词。筛选只影响展示，不会改动任何数据。</div>
        <div class="empty__actions"><button class="btn btn--outline" data-act="reset-filter">重置筛选</button></div>
      </div>` : `<div class="pager">
        <span>显示 ${rows.length} 条 · 共 ${count} 笔 · 每页 20 条</span>
        <div class="pager__nums">
          <button class="pager__num" aria-label="上一页">‹</button>
          <button class="pager__num" aria-current="true">1</button>
          <button class="pager__num">2</button>
          <button class="pager__num">3</button>
          <button class="pager__num" aria-label="下一页">›</button>
        </div>
      </div>`}
    <div class="card__foot">
      <span>${icon('lock', 12)} 原始事实字段（时间/金额/方向/对方/商品）只读，仅分类与备注可编辑</span>
      <button class="link-btn" data-go="help">为什么？</button>
    </div>
  </section>`;

  return pageHead('流水明细', '全量流水查询与修正 · 筛选汇总与仪表盘、报表同口径', actions) + filter + table;
}

/* ---------------- 5. 待确认队列 ---------------- */
function pagePending() {
  const groups = PEND_GROUPS.filter((g, i) => !state.pendingDone.has(i));
  const total = groups.reduce((a, g) => a + g.items.reduce((x, i) => x + Math.abs(i.amt), 0), 0);
  const count = groups.reduce((a, g) => a + g.items.length, 0);

  const actions = `<button class="btn btn--outline" data-act="toast" data-msg="已按对方名称聚合，共 3 组">${icon('filter', 15)}按对方聚合</button>
    <button class="btn btn--primary" data-go="import">${icon('upload', 15)}导入新账单</button>`;

  const list = `<section class="card">
    <div class="card__head">
      <div><div class="card__title">待确认流水</div><div class="card__sub">未命中任何规则 · 共 ${count} 笔 / ¥${fmt(total)}</div></div>
      <div class="spacer"></div>
      <span class="badge badge--warn">计入总支出</span>
    </div>
    <div class="card__body" id="pending-body" style="display:flex;flex-direction:column;gap:12px">
      ${!groups.length ? `<div class="empty">
        <div class="empty__art">${icon('checkCircle', 30)}</div>
        <div class="empty__title">全部处理完了</div>
        <div class="empty__desc">本月「未分类」金额已归零，报表与明细已同步刷新。下次导入时新的未分类流水会出现在这里。</div>
        <div class="empty__actions"><button class="btn btn--outline" data-go="reports">看看月报</button></div>
      </div>` : ''}
      ${groups.map((g) => { const gi = PEND_GROUPS.indexOf(g); return `<div class="pending-group" data-group="${gi}">
        <div class="pending-group__head" data-act="pick-group" data-g="${gi}">
          <label class="checkbox" onclick="event.stopPropagation()"><input type="checkbox" data-act="pick-cb" data-g="${gi}"><span class="checkbox__box"></span></label>
          <div><div class="pending-group__name">${g.cp}</div>
            <div class="pending-group__meta">${g.items.length} 笔${g.items.length > 1 ? ' · 同对方可一次归类' : ''}</div></div>
          <span class="pending-group__amt">¥${fmt(g.items.reduce((a, i) => a + Math.abs(i.amt), 0))}</span>
        </div>
        <div class="pending-group__body">
          ${g.items.map((i) => `<div class="pending-line">
            <span class="num">${i.time}</span>
            <span class="pending-line__item">${i.item}</span>
            <span class="pending-line__amt">−${fmt(Math.abs(i.amt))}</span>
          </div>`).join('')}
        </div>
      </div>`; }).join('')}
    </div>
    <div class="card__foot"><span>处理完成后队列清空，报表「未分类」金额归零</span>
      <span class="tiny">按规则优先级：同级取最新创建</span></div>
  </section>`;

  const aside = `<div class="stack assign-panel">
    <section class="card">
      <div class="card__head"><div><div class="card__title">批量归类</div><div class="card__sub">对已勾选的流水生效</div></div></div>
      <div class="card__body" style="display:flex;flex-direction:column;gap:16px">
        <div class="field">
          <label class="field__label">目标分类 <span class="req">*</span></label>
          <div class="select"><select class="select__native">
            <option>支出 · 餐饮美食 · 外卖</option>
            <option>支出 · 购物消费 · 日用百货</option>
            <option>支出 · 餐饮美食 · 食堂</option>
            <option>资金流转 · 个人转账</option>
          </select></div>
        </div>
        <div class="field">
          <label class="field__label">备注（可选）</label>
          <input class="input" placeholder="例如：校内便利店日常采购">
        </div>
        <label class="row" style="gap:10px;align-items:flex-start">
          <span class="switch" role="switch" aria-checked="true" data-act="toggle"></span>
          <span><span class="small strong" style="display:block">同时生成规则</span>
            <span class="tiny muted">以后导入同对方流水时自动套用该分类</span></span>
        </label>
        <div class="notice notice--info" style="padding:10px 12px">
          <span class="notice__icon">${icon('info', 14)}</span>
          <div>归类后记录状态变为「已修正」，后续重算默认不覆盖。</div>
        </div>
        <button class="btn btn--primary btn--block" data-act="apply-pending">应用并处理</button>
        <p class="tiny muted" style="text-align:center">已选 <b id="pick-count">0</b> 组</p>
      </div>
    </section>
    <section class="card card--quiet">
      <div class="card__body">
        <div class="section-label" style="margin-bottom:8px">为什么会出现待确认</div>
        <p class="small muted">导入时未命中任何分类规则、或金额/时间解析失败。你也可以先修规则，再一键重算历史流水。</p>
        <button class="btn btn--outline btn--sm btn--block" style="margin-top:12px" data-go="rules">去管理规则</button>
      </div>
    </section>
  </div>`;

  return pageHead('待确认队列', '集中处理未分类流水 · 按对方聚合，支持批量归类并生成规则', actions) +
    `<div class="grid g-12"><div class="c-8">${list}</div><div class="c-4">${aside}</div></div>`;
}

/* ---------------- 6. 导入向导 ---------------- */
const W_STEPS = ['上传文件', '字段映射', '去重预检', '确认入库', '导入报告'];

function pageImport() {
  const s = state.wStep;
  const stepBar = `<div class="wizard__bar"><div class="steps">
    ${W_STEPS.map((t, i) => `
      <div class="step ${i + 1 < s ? 'step--done' : i + 1 === s ? 'step--current' : ''}">
        <span class="step__dot">${i + 1 < s ? icon('check', 12) : i + 1}</span>
        <span class="step__label">${t}</span>
      </div>
      ${i < W_STEPS.length - 1 ? `<span class="step__line ${i + 1 < s ? 'step__line--done' : ''}"></span>` : ''}`).join('')}
  </div></div>`;

  const previewRows = [
    ['2026-10-21 12:38:04', '美团外卖', '午餐·黄焖鸡米饭', '支出', '−32.50'],
    ['2026-10-21 08:12:31', '瑞幸咖啡', '生椰拿铁', '支出', '−9.90'],
    ['2026-10-20 19:05:12', '学校食堂', '晚餐', '支出', '−12.00'],
    ['2026-10-20 15:40:55', '淘宝', 'Type-C 数据线', '支出', '−29.90'],
    ['2026-10-19 22:10:08', '滴滴出行', '快车·返校', '支出', '−18.60'],
  ];
  const previewTable = (limit = 5) => `<div class="preview-table"><div class="table-wrap"><table class="table table--compact">
      <thead><tr><th>交易时间</th><th>交易对方</th><th>商品说明</th><th>方向</th><th class="right">金额</th></tr></thead>
      <tbody>${previewRows.slice(0, limit).map((r) => `<tr>
        <td class="num" style="font-size:12px">${r[0]}</td><td class="td-strong">${r[1]}</td>
        <td class="td-muted">${r[2]}</td><td>${r[3]}</td><td class="td-num">${r[4]}</td></tr>`).join('')}
      </tbody></table></div></div>`;

  let panel = '';

  if (s === 1) {
    panel = `<div class="wizard__panel">
      ${state.uploaded ? `
        <div class="upload-row" style="margin-bottom:16px">
          <span class="file-icon">${icon('file', 18)}</span>
          <div class="file-meta"><b>微信支付账单(20261001-20261021).csv</b>
            <span>86 KB · UTF-8 · 42 行 · 已落盘至缓冲区</span></div>
          <span class="badge badge--ok">上传完成</span>
          <button class="icon-btn" data-act="reset-upload" aria-label="移除">${icon('trash', 15)}</button>
        </div>
        <div class="progress" style="margin-bottom:20px"><div class="progress__bar" style="width:100%"></div></div>
        <div class="kv-grid" style="margin-bottom:20px">
          <div class="kv"><div class="kv__k">识别行数</div><div class="kv__v">42<small>行</small></div></div>
          <div class="kv"><div class="kv__k">编码探测</div><div class="kv__v" style="font-family:var(--font-mono);font-size:13px">UTF-8</div></div>
          <div class="kv"><div class="kv__k">表头识别</div><div class="kv__v">7<small>/ 7 列</small></div></div>
          <div class="kv"><div class="kv__k">时间范围</div><div class="kv__v" style="font-size:13px">10-01 ~ 10-21</div></div>
        </div>
        <div class="section-label" style="margin-bottom:10px">解析预览 · 前 5 行（共 42 行）</div>
        ${previewTable()}
        <div class="notice notice--info" style="margin-top:16px">
          <span class="notice__icon">${icon('info', 15)}</span>
          <div>文件已在本地缓冲区落盘，<b>尚未写入原始库与主数据层</b>。关闭页面后批次仍保留，可继续处理。</div>
        </div>` : `
        <div class="dropzone" data-act="upload">
          <span class="dropzone__icon">${icon('upload', 22)}</span>
          <span class="dropzone__title">把账单文件拖到这里，或点击选择</span>
          <span class="dropzone__desc">支持 .csv / .xlsx，单文件 ≤ 5MB 且 ≤ 50,000 行 · 文件仅落盘本机</span>
          <div class="row" style="margin-top:6px">
            <span class="badge badge--neutral">微信</span><span class="badge badge--neutral">支付宝</span><span class="badge badge--neutral">银行卡</span>
          </div>
        </div>
        <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:16px;gap:12px">
          <div class="notice"><span class="notice__icon">${icon('db', 15)}</span><div><b>自动编码探测</b><br>UTF-8 / GBK / GB18030 自动识别，中文不会乱码。</div></div>
          <div class="notice"><span class="notice__icon">${icon('lock', 15)}</span><div><b>隐私优先</b><br>文件不上传任何外部服务，入库成功后原文件自动删除。</div></div>
        </div>`}
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 上传阶段不写库，可随时丢弃</div>
      <div class="spacer"></div>
      <button class="btn btn--ghost" data-go="dashboard">取消</button>
      <button class="btn btn--primary" data-act="w-next" ${state.uploaded ? '' : 'disabled'}>下一步：字段映射 ${icon('chevronR', 14)}</button>
    </div>`;
  }

  if (s === 2) {
    const map = [
      ['交易时间', '交易时间', '2026-10-21 12:38:04', true],
      ['金额', '金额(元)', '32.50', true],
      ['收支方向', '收/支', '支出', true],
      ['交易对方', '交易对方', '美团外卖', true],
      ['商品说明', '商品', '午餐·黄焖鸡米饭', true],
      ['交易类型', '交易类型', '商户消费', false],
      ['支付方式', '支付方式', '零钱', false],
    ];
    panel = `<div class="wizard__panel">
      <div class="row" style="margin-bottom:16px">
        <span class="badge badge--ok">${icon('check', 11)}5 个核心字段已自动命中</span>
        <span class="tiny muted">来源渠道：微信 · 已套用「微信支付」模板</span>
      </div>
      <div class="section-label" style="margin-bottom:6px">字段映射</div>
      <div class="map-row" style="padding-bottom:8px;border-bottom:1px solid var(--border-2)">
        <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">标准字段</span>
        <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">文件列</span>
        <span></span>
        <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">样例值</span>
      </div>
      ${map.map(([std, col, sample, req]) => `<div class="map-row">
        <span class="map-row__std">${std}${req ? '<span class="req">必填</span>' : ''}</span>
        <div class="select select--sm"><select class="select__native">
          <option>${col}</option><option>不导入此列</option><option>自定义…</option>
        </select></div>
        <span class="map-row__arrow">${icon('chevronR', 13)}</span>
        <div class="row" style="gap:8px">
          <span class="small muted num" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${sample}</span>
          ${req ? '<span class="map-auto">' + icon('check', 11) + '自动</span>' : '<span class="tiny" style="color:var(--text-4)">选填</span>'}
        </div>
      </div>`).join('')}
      <div class="row" style="margin-top:16px;justify-content:space-between">
        <label class="row" style="gap:10px">
          <span class="switch" role="switch" aria-checked="true" data-act="toggle"></span>
          <span class="small">保存为「微信」渠道模板</span>
        </label>
        <span class="tiny muted">同渠道再次保存会提示覆盖，可另存为新模板</span>
      </div>
      <div class="section-label" style="margin:20px 0 10px">按当前映射刷新预览</div>
      ${previewTable(4)}
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 五个核心字段未映射完成时无法进入下一步</div>
      <div class="spacer"></div>
      <button class="btn btn--outline" data-act="w-prev">上一步</button>
      <button class="btn btn--primary" data-act="w-next">确认映射并预检 ${icon('chevronR', 14)}</button>
    </div>`;
  }

  if (s === 3) {
    const rows = [
      ['2026-10-21 12:38:04', '美团外卖', '32.50', 'new'],
      ['2026-10-21 08:12:31', '瑞幸咖啡', '9.90', 'new'],
      ['2026-10-20 19:05:12', '学校食堂', '12.00', 'new'],
      ['2026-10-16 09:00:00', '零钱通', '500.00', 'dup'],
      ['2026-10-12 16:00:00', '学校财务处', '500.00', 'new'],
      ['2026-10-10 09:00:00', '零钱通', '500.00', 'dup'],
      ['2026-10-02 20:20:00', '万达影城', '38.00', 'warn'],
      ['2026-09-28 13:20:00', '校园超市', '18.00', 'new'],
    ];
    panel = `<div class="wizard__panel">
      <div class="kv-grid" style="margin-bottom:16px">
        <div class="kv"><div class="kv__k">总行数</div><div class="kv__v">42</div></div>
        <div class="kv"><div class="kv__k" style="color:var(--ok)">新增</div><div class="kv__v" style="color:var(--ok)">38</div></div>
        <div class="kv"><div class="kv__k" style="color:var(--warn)">重复</div><div class="kv__v" style="color:var(--warn)">3</div></div>
        <div class="kv"><div class="kv__k">待确认</div><div class="kv__v">1</div></div>
      </div>
      <div class="notice notice--info" style="margin-bottom:14px">
        <span class="notice__icon">${icon('info', 15)}</span>
        <div>预检为<b>只读</b>操作，不写任何库。若某条被误判为重复，可点「强制新增」并说明原因，入库时按新增处理并留痕。</div>
      </div>
      <div class="preview-table"><div class="table-wrap table-scroll"><table class="table table--compact">
        <thead><tr><th>交易时间</th><th>交易对方</th><th class="right">金额</th><th>判定</th><th class="right">操作</th></tr></thead>
        <tbody>${rows.map((r, i) => `<tr class="${r[3] === 'dup' ? 'is-dup' : ''}">
          <td class="num" style="font-size:12px">${r[0]}</td>
          <td class="td-strong">${r[1]}</td>
          <td class="td-num">${r[2]}</td>
          <td>${r[3] === 'new' ? '<span class="badge badge--ok">新增</span>' : r[3] === 'dup' ? '<span class="badge badge--neutral">重复 · 将跳过</span>' : '<span class="badge badge--warn">待确认</span>'}</td>
          <td class="right">${r[3] === 'dup'
            ? `<button class="btn btn--outline btn--sm" data-act="force-new">强制新增</button>`
            : r[3] === 'warn' ? '<span class="tiny muted">入库后处理</span>' : '<span class="tiny muted">—</span>'}</td>
        </tr>`).join('')}</tbody>
      </table></div></div>
      <p class="tiny muted" style="margin-top:10px">当前展示 8 / 42 行 · <button class="link-btn" data-act="toast" data-msg="已展开全部 42 行（示例）">查看全部</button> · 预检汇总为快照，最终以入库报告为准</p>
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 3 条重复将被跳过；全量重复时批次仍记为「已入库（新增 0 条）」</div>
      <div class="spacer"></div>
      <button class="btn btn--outline" data-act="w-prev">上一步</button>
      <button class="btn btn--primary" data-act="w-next">下一步：确认入库 ${icon('chevronR', 14)}</button>
    </div>`;
  }

  if (s === 4) {
    panel = `<div class="wizard__panel">
      <div class="grid" style="grid-template-columns:1.2fr 1fr;gap:24px">
        <div>
          <div class="section-label" style="margin-bottom:12px">即将写入</div>
          <div class="batch-trace" style="margin-bottom:10px">${icon('db', 14)}<b>raw_2026_10</b><span class="muted">38 条 · 归档原貌 + 批次号 + 行号</span></div>
          <div class="batch-trace" style="margin-bottom:10px">${icon('db', 14)}<b>raw_2026_09</b><span class="muted">2 条 · 跨月自动拆分</span></div>
          <div class="batch-trace" style="margin-bottom:16px">${icon('list', 14)}<b>transaction</b><span class="muted">40 条主数据 · 已清洗分类</span></div>
          <div class="notice notice--warn">
            <span class="notice__icon">${icon('alert', 15)}</span>
            <div><b>事务原子性</b>：raw 与主数据层在同一事务内写入，任一步失败整体回滚，批次回到「待确认」，原文件保留可重试。</div>
          </div>
        </div>
        <div>
          <div class="section-label" style="margin-bottom:12px">入库摘要</div>
          <div class="kv-grid" style="grid-template-columns:1fr">
            <div class="kv"><div class="kv__k">批次号</div><div class="kv__v" style="font-size:13px;font-family:var(--font-mono)">B-20261021-1</div></div>
            <div class="kv"><div class="kv__k">新增 / 跳过 / 待确认</div><div class="kv__v" style="font-size:15px">38 / 3 / 1</div></div>
            <div class="kv"><div class="kv__k">入库后动作</div><div class="kv__v" style="font-size:13px">删除缓冲区原文件</div></div>
            <div class="kv"><div class="kv__k">幂等保护</div><div class="kv__v" style="font-size:13px">仅「待确认」批次可提交</div></div>
          </div>
          <div class="notice notice--info" style="margin-top:14px">
            <span class="notice__icon">${icon('shield', 15)}</span>
            <div>删除意图先落库，即使提交后瞬间断电，重启时启动对账也会补删残留文件。</div>
          </div>
        </div>
      </div>
      ${state.importing ? `<div style="margin-top:20px">
        <div class="row" style="justify-content:space-between;margin-bottom:6px">
          <span class="small strong">正在写入数据库…</span><span class="small num muted" id="imp-pct">0%</span>
        </div>
        <div class="progress"><div class="progress__bar" id="imp-bar" style="width:0%"></div></div>
        <p class="tiny muted" style="margin-top:8px">事务执行中，请勿关闭页面（示例：约 1.2 秒完成）</p>
      </div>` : ''}
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('lock', 13)} 入库为事务操作，不允许部分成功</div>
      <div class="spacer"></div>
      <button class="btn btn--outline" data-act="w-prev" ${state.importing ? 'disabled' : ''}>上一步</button>
      <button class="btn btn--primary ${state.importing ? 'btn--loading' : ''}" data-act="confirm-import">
        ${state.importing ? '入库中' : '确认入库并删除原文件'}
      </button>
    </div>`;
  }

  if (s === 5) {
    panel = `<div class="wizard__panel">
      <div class="report-hero" style="margin-bottom:18px">
        <span class="report-hero__icon">${icon('check', 24)}</span>
        <div style="flex:1">
          <div style="font-size:var(--t-lg);font-weight:var(--w-semi)">入库完成，原始文件已删除</div>
          <div class="small muted" style="margin-top:3px">批次 B-20261021-1 · 用时 1.18s · 缓冲区已无残留</div>
        </div>
        <span class="badge badge--ok">${icon('check', 11)}事务已提交</span>
      </div>
      <div class="report-grid" style="margin-bottom:16px">
        <div><div class="kv__k">总行数</div><div class="kv__v">42</div></div>
        <div><div class="kv__k" style="color:var(--ok)">新增入库</div><div class="kv__v" style="color:var(--ok)">38</div></div>
        <div><div class="kv__k" style="color:var(--warn)">跳过重复</div><div class="kv__v" style="color:var(--warn)">3</div></div>
        <div><div class="kv__k">待确认</div><div class="kv__v">1</div></div>
      </div>
      <div class="section-label" style="margin-bottom:10px">按月归档结果</div>
      <div class="table-wrap" style="border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden">
        <table class="table table--compact">
          <thead><tr><th>归档表</th><th>记录数</th><th>批次</th><th>状态</th></tr></thead>
          <tbody>
            <tr><td class="mono td-strong">raw_2026_10</td><td class="td-num">36</td><td class="td-muted mono">B-20261021-1</td><td><span class="badge badge--ok">已写入</span></td></tr>
            <tr><td class="mono td-strong">raw_2026_09</td><td class="td-num">2</td><td class="td-muted mono">B-20261021-1</td><td><span class="badge badge--ok">已写入</span></td></tr>
          </tbody>
        </table>
      </div>
      <div class="notice notice--ok" style="margin-top:14px">
        <span class="notice__icon">${icon('shield', 15)}</span>
        <div>缓冲区原文件已物理删除（10-22 20:07:42），删除日志已记录；本次入库 1 条待确认流水已进入待确认队列。</div>
      </div>
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 报告以入库时实际执行结果为准</div>
      <div class="spacer"></div>
      <button class="btn btn--outline" data-go="pending">去处理待确认</button>
      <button class="btn btn--primary" data-go="dashboard">回到仪表盘 ${icon('chevronR', 14)}</button>
    </div>`;
  }

  return pageHead('导入账单', '上传 → 映射 → 预检 → 入库 → 报告，全程本地完成', 
    `<button class="btn btn--ghost btn--sm" data-go="help">${icon('help', 15)}导入说明</button>`) +
    `<div class="wizard">${stepBar}<section class="card card--flush">${panel}</section></div>`;
}
