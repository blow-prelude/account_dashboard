/* ============================================================
   05 · 图形符号 / 样例数据 / 工具函数
   ============================================================ */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ICON = {
  dashboard: '<rect x="3" y="3" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2.2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2.2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2.2"/>',
  reports: '<path d="M3 20.5h18"/><rect x="4.5" y="12" width="3.6" height="6" rx="1.4"/><rect x="10.2" y="7" width="3.6" height="11" rx="1.4"/><rect x="15.9" y="3.5" width="3.6" height="14.5" rx="1.4"/>',
  import: '<path d="M12 15.5V3.5m0 0L7.2 8.3M12 3.5l4.8 4.8"/><path d="M3.8 16v2.6a2 2 0 0 0 2 2h12.4a2 2 0 0 0 2-2V16"/>',
  buffer: '<path d="M3 11.5h4.2l1.6 2.6h6.4l1.6-2.6H21"/><path d="M4.8 5.2 3 11.5v5.2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5.2l-1.8-6.3A2 2 0 0 0 17.3 4H6.7a2 2 0 0 0-1.9 1.2Z"/>',
  archive: '<ellipse cx="12" cy="5.6" rx="8" ry="2.9"/><path d="M4 5.6v5.6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9V5.6"/><path d="M4 11.2v5.6c0 1.6 3.6 2.9 8 2.9s8-1.3 8-2.9v-5.6"/>',
  list: '<path d="M8.5 6h12M8.5 12h12M8.5 18h12"/><circle cx="3.6" cy="6" r="1.3"/><circle cx="3.6" cy="12" r="1.3"/><circle cx="3.6" cy="18" r="1.3"/>',
  pending: '<circle cx="12" cy="12" r="8.8"/><path d="M12 7.2v5.2l3.4 2"/>',
  rules: '<path d="M4 6.2h8.4M17.6 6.2h2.4M4 12h3.4M11.4 12h8.6M4 17.8h8.4M17.6 17.8h2.4"/><circle cx="15" cy="6.2" r="2.2"/><circle cx="9" cy="12" r="2.2"/><circle cx="15" cy="17.8" r="2.2"/>',
  tag: '<path d="M20.4 12.4 12.4 20.4a2 2 0 0 1-2.8 0l-6-6a2 2 0 0 1-.6-1.4V5.2a2 2 0 0 1 2-2h7.8a2 2 0 0 1 1.4.6l6 6a2 2 0 0 1 0 2.8Z"/><circle cx="8.2" cy="8.2" r="1.4"/>',
  pie: '<path d="M12 3.2a8.8 8.8 0 1 0 8.8 8.8H12V3.2Z"/><path d="M14.4 3.6a8.8 8.8 0 0 1 6 6H14.4V3.6Z"/>',
  shield: '<path d="M12 3 5.2 5.9v5.9c0 4.3 2.9 7.4 6.8 8.8 3.9-1.4 6.8-4.5 6.8-8.8V5.9L12 3Z"/><path d="m9.4 11.9 1.8 1.8 3.4-3.6"/>',
  gear: '<circle cx="12" cy="12" r="3.1"/><path d="M12 2.6v2.6M12 18.8v2.6M4.4 4.4l1.9 1.9M17.7 17.7l1.9 1.9M2.6 12h2.6M18.8 12h2.6M4.4 19.6l1.9-1.9M17.7 6.3l1.9-1.9"/>',
  help: '<circle cx="12" cy="12" r="8.8"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1.1.9-1.1 1.7v.3"/><circle cx="12" cy="16.9" r="0.9" fill="currentColor" stroke="none"/>',
  palette: '<circle cx="12" cy="12" r="8.8"/><circle cx="9" cy="9.2" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="9.2" r="1.2" fill="currentColor" stroke="none"/><circle cx="9.4" cy="14.8" r="1.2" fill="currentColor" stroke="none"/>',
  plus: '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m15.8 15.8 4 4"/>',
  upload: '<path d="M12 16.2V4.4m0 0L7.6 8.8M12 4.4l4.4 4.4"/><path d="M4.2 16.4v2.2a1.6 1.6 0 0 0 1.6 1.6h12.4a1.6 1.6 0 0 0 1.6-1.6v-2.2"/>',
  download: '<path d="M12 4.2v11.6m0 0 4.4-4.4M12 15.8l-4.4-4.4"/><path d="M4.2 16.4v2.2a1.6 1.6 0 0 0 1.6 1.6h12.4a1.6 1.6 0 0 0 1.6-1.6v-2.2"/>',
  check: '<path d="m4.8 12.6 4.6 4.6L19.2 7.4"/>',
  checkCircle: '<circle cx="12" cy="12" r="8.8"/><path d="m8.2 12.2 2.6 2.6 5-5.2"/>',
  x: '<path d="m6.4 6.4 11.2 11.2M17.6 6.4 6.4 17.6"/>',
  alert: '<path d="M12 4.2 2.8 20h18.4L12 4.2Z"/><path d="M12 10v4.2"/><circle cx="12" cy="17.3" r="0.9" fill="currentColor" stroke="none"/>',
  info: '<circle cx="12" cy="12" r="8.8"/><path d="M12 11v5.4"/><circle cx="12" cy="8" r="0.9" fill="currentColor" stroke="none"/>',
  refresh: '<path d="M20.4 11.2a8.4 8.4 0 1 0-2.2 6.6"/><path d="M20.4 4.8v6.4h-6.4"/>',
  chevronR: '<path d="m9.4 5.6 6.4 6.4-6.4 6.4"/>',
  chevronD: '<path d="m5.6 9.4 6.4 6.4 6.4-6.4"/>',
  arrowUpRight: '<path d="M7 17 17 7M9.4 7H17v7.6"/>',
  edit: '<path d="M4.4 19.6h4l10-10a2.2 2.2 0 0 0-3.1-3.1l-10 10v3.1Z"/><path d="m14.2 7.4 2.4 2.4"/>',
  trash: '<path d="M4.4 6.6h15.2M9.4 6.6V4.4h5.2v2.2M6.6 6.6l.9 12.2a1.8 1.8 0 0 0 1.8 1.6h5.4a1.8 1.8 0 0 0 1.8-1.6l.9-12.2"/>',
  lock: '<rect x="5" y="10.4" width="14" height="9.6" rx="2.4"/><path d="M8.4 10.4V7.6a3.6 3.6 0 0 1 7.2 0v2.8"/>',
  eye: '<path d="M2.6 12S6 6.4 12 6.4 21.4 12 21.4 12 18 17.6 12 17.6 2.6 12 2.6 12Z"/><circle cx="12" cy="12" r="2.8"/>',
  sparkles: '<path d="M12 3.6l1.8 4.8 4.8 1.8-4.8 1.8L12 16.8l-1.8-4.8L5.4 10.2l4.8-1.8L12 3.6Z"/><path d="M18.6 15.6l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2Z"/>',
  file: '<path d="M13.6 3.6H7.4a2 2 0 0 0-2 2v12.8a2 2 0 0 0 2 2h9.2a2 2 0 0 0 2-2V8.6l-5-5Z"/><path d="M13.4 3.8v5h5"/>',
  filter: '<path d="M3.6 5.4h16.8l-6.6 7.6v5.6l-3.6 2v-7.6L3.6 5.4Z"/>',
  clock: '<circle cx="12" cy="12" r="8.8"/><path d="M12 7.2v5.2l3.4 2"/>',
  db: '<ellipse cx="12" cy="5.6" rx="7.6" ry="2.8"/><path d="M4.4 5.6v12.8c0 1.5 3.4 2.8 7.6 2.8s7.6-1.3 7.6-2.8V5.6"/>',
  folder: '<path d="M3.6 7.4a2 2 0 0 1 2-2h3.6l2 2.4h7.2a2 2 0 0 1 2 2v8.4a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2V7.4Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>',
};

function icon(name, size = 16, stroke = 1.6) {
  const path = ICON[name] || '';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

/* ---------- 数字格式 ---------- */
const fmt = (n, d = 2) =>
  Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const cny = (n, d = 2) => '¥' + fmt(n, d);
const signed = (n, d = 2) => (n >= 0 ? '+' : '−') + fmt(Math.abs(n), d);

/* ---------- 期间数据（示例，金额为虚构脱敏） ---------- */
const P = {
  month: {
    id: 'month', tab: '本月', title: '2026 年 10 月', range: '10-01 ~ 10-21', days: 21,
    income: 2000, expense: 1486.5, balance: 513.5, saving: 25.7, avg: 70.79,
    pending: { count: 4, amount: 81 },
    d: {
      income: { v: 12.5, good: true },
      expense: { v: 8.3, good: false },
      balance: { v: -5.2, good: false },
      saving: { v: -3.1, unit: 'pt', good: false },
      avg: { v: 8.3, good: false },
    },
    trendTitle: '每日支出',
    trend: {
      labels: ['10/01','10/02','10/03','10/04','10/05','10/06','10/07','10/08','10/09','10/10','10/11','10/12','10/13','10/14','10/15','10/16','10/17','10/18','10/19','10/20','10/21'],
      expense: [32.5,58,41.2,96.8,22,145.6,18.4,63.9,88.5,27,210.3,45.2,19.9,132.4,58.6,41,76.5,63.2,24.8,158.9,61.8],
      marks: [
        { i: 2, label: '生活费到账', value: 1500 },
        { i: 11, label: '助学金到账', value: 500 },
      ],
    },
    donut: [
      { name: '餐饮美食', value: 541.6, color: 'var(--chart-1)' },
      { name: '购物消费', value: 285.0, color: 'var(--chart-2)' },
      { name: '交通出行', value: 182.4, color: 'var(--chart-3)' },
      { name: '居住缴费', value: 135.0, color: 'var(--chart-4)' },
      { name: '学习资料', value: 124.8, color: 'var(--chart-5)' },
      { name: '通讯娱乐', value: 92.1, color: 'var(--chart-6)' },
      { name: '人情往来', value: 44.6, color: 'var(--chart-7)' },
      { name: '未分类', value: 81.0, color: 'var(--chart-8)' },
    ],
    top: [
      { name: '美团外卖', amount: 218.4, count: 9 },
      { name: '学校食堂', amount: 176.3, count: 18 },
      { name: '淘宝', amount: 142.0, count: 4 },
      { name: '瑞幸咖啡', amount: 96.0, count: 6 },
      { name: '滴滴出行', amount: 88.5, count: 7 },
    ],
    summary: [
      '本月支出 <b>¥1,486.50</b>，比上月多花 <b>¥114.20</b>（+8.3%），主要增量在「购物消费」。',
      '「餐饮美食」占总支出的 <b>36.4%</b>，日均餐饮约 <b>¥25.79</b>，是最主要的固定开销。',
      '储蓄率 <b>25.7%</b>，比上月下降 <b>3.1</b> 个百分点；收入未变、支出上升是唯一原因。',
      '10/11 单日支出 <b>¥210.30</b> 为全月峰值，超过单日阈值 ¥200（可在设置中调整）。',
    ],
  },
  quarter: {
    id: 'quarter', tab: '本季度', title: '2026 年 Q3', range: '07-01 ~ 09-30', days: 92,
    income: 6050, expense: 4383, balance: 1667, saving: 27.6, avg: 47.64,
    pending: { count: 5, amount: 90 },
    d: {
      income: { v: 4.0, good: true },
      expense: { v: -2.4, good: true },
      balance: { v: 18.6, good: true },
      saving: { v: 3.2, unit: 'pt', good: true },
      avg: { v: -2.4, good: true },
    },
    trendTitle: '每周支出',
    trend: {
      labels: ['W1','W2','W3','W4','W5','W6','W7','W8','W9','W10','W11','W12','W13'],
      expense: [168,312,295,402,358,386,341,298,372,365,330,402,354],
      marks: [
        { i: 0, label: '7 月生活费', value: 2000 },
        { i: 4, label: '8 月生活费', value: 2050 },
        { i: 8, label: '9 月生活费', value: 2000 },
      ],
    },
    donut: [
      { name: '餐饮美食', value: 1682.4, color: 'var(--chart-1)' },
      { name: '购物消费', value: 872.0, color: 'var(--chart-2)' },
      { name: '交通出行', value: 545.0, color: 'var(--chart-3)' },
      { name: '居住缴费', value: 405.0, color: 'var(--chart-4)' },
      { name: '学习资料', value: 360.0, color: 'var(--chart-5)' },
      { name: '通讯娱乐', value: 268.0, color: 'var(--chart-6)' },
      { name: '人情往来', value: 160.6, color: 'var(--chart-7)' },
      { name: '未分类', value: 90.0, color: 'var(--chart-8)' },
    ],
    top: [
      { name: '学校食堂', amount: 612.4, count: 54 },
      { name: '美团外卖', amount: 528.6, count: 23 },
      { name: '淘宝', amount: 412.0, count: 11 },
      { name: '滴滴出行', amount: 236.5, count: 19 },
      { name: '京东', amount: 208.9, count: 5 },
    ],
    summary: [
      'Q3 支出 <b>¥4,383.00</b>，比 Q2 少 <b>¥107.80</b>（−2.4%），是今年首个支出下降的季度。',
      '「餐饮美食」<b>¥1,682.40</b>（38.4%）仍是最大项，但环比下降 <b>4.1%</b>，与假期回家有关。',
      '季度结余 <b>¥1,667.00</b>，储蓄率 <b>27.6%</b>，环比提升 3.2 个百分点。',
      '9 月支出 <b>¥1,483.00</b> 为季度最高，主要是开学采购与教材支出集中。',
    ],
  },
  year: {
    id: 'year', tab: '本年度', title: '2026 年度', range: '01-01 ~ 10-21', days: 294,
    income: 19850, expense: 14226.3, balance: 5623.7, saving: 28.3, avg: 48.39,
    pending: { count: 8, amount: 205 },
    d: {
      income: { v: 8.8, good: true },
      expense: { v: 6.1, good: false },
      balance: { v: 16.2, good: true },
      saving: { v: 2.0, unit: 'pt', good: true },
      avg: { v: 6.1, good: false },
    },
    trendTitle: '每月收支',
    trend: {
      labels: ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],
      income: [1700,1680,1750,1700,1760,1800,2310,1800,2200,2000,null,null],
      expense: [1500,1320,1410,1380,1450,1290,1480,1420,1483,1486.3,null,null],
      marks: [],
    },
    donut: [
      { name: '餐饮美食', value: 5432.1, color: 'var(--chart-1)' },
      { name: '购物消费', value: 2860.5, color: 'var(--chart-2)' },
      { name: '交通出行', value: 1745.2, color: 'var(--chart-3)' },
      { name: '居住缴费', value: 1260.0, color: 'var(--chart-4)' },
      { name: '学习资料', value: 1140.8, color: 'var(--chart-5)' },
      { name: '通讯娱乐', value: 862.4, color: 'var(--chart-6)' },
      { name: '人情往来', value: 410.3, color: 'var(--chart-7)' },
      { name: '未分类', value: 205.0, color: 'var(--chart-8)' },
    ],
    top: [
      { name: '学校食堂', amount: 2186.4, count: 186 },
      { name: '美团外卖', amount: 1642.8, count: 78 },
      { name: '淘宝', amount: 1288.0, count: 34 },
      { name: '京东', amount: 742.6, count: 16 },
      { name: '滴滴出行', amount: 618.5, count: 52 },
    ],
    summary: [
      '全年（截至 10-21）收入 <b>¥19,850.00</b>、支出 <b>¥14,226.30</b>，结余 <b>¥5,623.70</b>。',
      '储蓄率 <b>28.3%</b>，同比提升 2.0 个百分点，主要来自奖助学金增加。',
      '「餐饮美食」全年 <b>¥5,432.10</b>（38.2%），是唯一超过总支出三分之一的分类。',
      '支出最高的月份是 <b>10 月（¥1,486.30）</b>，最低为 <b>6 月（¥1,290.00）</b>，波动幅度 15.2%。',
    ],
  },
};

/* ---------- 分类分析（本月） ---------- */
const ANALYSIS = [
  { l1: '餐饮美食', amount: 541.6, pct: 36.4, mom: 6.2, color: 'var(--chart-1)',
    l2: [['外卖', 248.6, 45.9, 12.4], ['食堂', 176.3, 32.6, -4.1], ['咖啡茶饮', 78.6, 14.5, 22.8], ['零食水果', 38.1, 7.0, 3.2]] },
  { l1: '购物消费', amount: 285.0, pct: 19.2, mom: 28.4, color: 'var(--chart-2)',
    l2: [['日用百货', 128.0, 44.9, 18.2], ['数码配件', 89.0, 31.2, 62.5], ['服饰鞋包', 68.0, 23.9, 12.0]] },
  { l1: '交通出行', amount: 182.4, pct: 12.3, mom: -6.8, color: 'var(--chart-3)',
    l2: [['网约车', 88.5, 48.5, -11.2], ['公共交通', 63.9, 35.0, -2.4], ['共享单车', 30.0, 16.5, -0.8]] },
  { l1: '居住缴费', amount: 135.0, pct: 9.1, mom: 0, color: 'var(--chart-4)',
    l2: [['住宿费', 135.0, 100, 0]] },
  { l1: '学习资料', amount: 124.8, pct: 8.4, mom: 42.6, color: 'var(--chart-5)',
    l2: [['教材书籍', 68.0, 54.5, 42.6], ['打印复印', 32.8, 26.3, 18.0], ['文具', 24.0, 19.2, 9.4]] },
  { l1: '通讯娱乐', amount: 92.1, pct: 6.2, mom: -14.2, color: 'var(--chart-6)',
    l2: [['话费网费', 50.0, 54.3, 0], ['娱乐票务', 38.0, 41.3, -32.0], ['会员订阅', 4.1, 4.4, 0]] },
  { l1: '人情往来', amount: 44.6, pct: 3.0, mom: -22.5, color: 'var(--chart-7)',
    l2: [['红包礼金', 44.6, 100, -22.5]] },
  { l1: '未分类', amount: 81.0, pct: 5.4, mom: 12.0, color: 'var(--chart-8)', pending: true,
    l2: [['待确认餐饮', 36.3, 44.8, 0], ['未知商户', 36.7, 45.3, 0], ['自助洗衣', 8.0, 9.9, 0]] },
];

/* ---------- 流水明细 ---------- */
const TX = [
  { id: 't01', time: '10-21 12:38', cp: '美团外卖', item: '午餐·黄焖鸡米饭', amt: -32.5, dir: 'expense', l1: '支出', l2: '餐饮美食 · 外卖', method: '微信支付', batch: 'B-20261021-1', row: 12, status: 'confirmed', note: '' },
  { id: 't02', time: '10-21 08:12', cp: '瑞幸咖啡', item: '生椰拿铁', amt: -9.9, dir: 'expense', l1: '支出', l2: '餐饮美食 · 咖啡茶饮', method: '微信支付', batch: 'B-20261021-1', row: 11, status: 'confirmed', note: '' },
  { id: 't03', time: '10-20 19:05', cp: '学校食堂', item: '晚餐', amt: -12.0, dir: 'expense', l1: '支出', l2: '餐饮美食 · 食堂', method: '校园卡', batch: 'B-20261020-1', row: 8, status: 'confirmed', note: '' },
  { id: 't04', time: '10-20 15:40', cp: '淘宝', item: 'Type-C 数据线', amt: -29.9, dir: 'expense', l1: '支出', l2: '购物消费 · 数码配件', method: '支付宝', batch: 'B-20261020-1', row: 7, status: 'corrected', note: '原判为「其他支出」，手动改为数码配件' },
  { id: 't05', time: '10-19 22:10', cp: '滴滴出行', item: '快车 · 返校', amt: -18.6, dir: 'expense', l1: '支出', l2: '交通出行 · 网约车', method: '支付宝', batch: 'B-20261019-1', row: 5, status: 'confirmed', note: '' },
  { id: 't06', time: '10-18 10:02', cp: '当当网', item: '教材《数据结构》', amt: -68.0, dir: 'expense', l1: '支出', l2: '学习资料 · 教材书籍', method: '支付宝', batch: 'B-20261018-1', row: 4, status: 'confirmed', note: '' },
  { id: 't07', time: '10-17 21:30', cp: '便利店', item: '日用品', amt: -23.5, dir: 'expense', l1: '支出', l2: '未分类', method: '微信支付', batch: 'B-20261017-1', row: 3, status: 'pending', note: '' },
  { id: 't08', time: '10-17 21:34', cp: '便利店', item: '零食', amt: -12.8, dir: 'expense', l1: '支出', l2: '未分类', method: '微信支付', batch: 'B-20261017-1', row: 4, status: 'pending', note: '' },
  { id: 't09', time: '10-16 09:00', cp: '零钱通', item: '转出至银行卡', amt: -500.0, dir: 'neutral', l1: '资金流转', l2: '零钱通申购赎回', method: '微信支付', batch: 'B-20261016-1', row: 2, status: 'confirmed', note: '中性：不计入收支统计' },
  { id: 't10', time: '10-15 20:00', cp: '中国移动', item: '话费充值 50 元', amt: -50.0, dir: 'expense', l1: '支出', l2: '通讯娱乐 · 话费网费', method: '微信支付', batch: 'B-20261015-1', row: 2, status: 'confirmed', note: '' },
  { id: 't11', time: '10-14 12:20', cp: '饿了么', item: '午餐 · 麻辣烫', amt: -26.8, dir: 'expense', l1: '支出', l2: '餐饮美食 · 外卖', method: '支付宝', batch: 'B-20261014-1', row: 9, status: 'confirmed', note: '' },
  { id: 't12', time: '10-12 16:00', cp: '学校财务处', item: '秋季助学金', amt: 500.0, dir: 'income', l1: '收入', l2: '奖学金助学金', method: '银行卡', batch: 'B-20261012-1', row: 1, status: 'confirmed', note: '' },
  { id: 't13', time: '10-10 09:15', cp: '室友-张', item: 'AA 转账', amt: -45.0, dir: 'neutral', l1: '资金流转', l2: '个人转账', method: '微信支付', batch: 'B-20261010-1', row: 6, status: 'confirmed', note: '个人转账默认中性' },
  { id: 't14', time: '10-09 18:40', cp: '屈臣氏', item: '洗护用品', amt: -59.0, dir: 'expense', l1: '支出', l2: '购物消费 · 日用百货', method: '支付宝', batch: 'B-20261009-1', row: 3, status: 'confirmed', note: '' },
  { id: 't15', time: '10-08 07:50', cp: '地铁 2 号线', item: '通勤', amt: -4.0, dir: 'expense', l1: '支出', l2: '交通出行 · 公共交通', method: '支付宝', batch: 'B-20261008-1', row: 2, status: 'confirmed', note: '' },
  { id: 't16', time: '10-05 14:30', cp: '学校后勤', item: '住宿费补缴', amt: -135.0, dir: 'expense', l1: '支出', l2: '居住缴费 · 住宿费', method: '银行卡', batch: 'B-20261005-1', row: 1, status: 'confirmed', note: '' },
  { id: 't17', time: '10-03 10:00', cp: '父亲', item: '生活费转账', amt: 1500.0, dir: 'income', l1: '收入', l2: '家人资助', method: '银行卡', batch: 'B-20261003-1', row: 1, status: 'confirmed', note: '' },
  { id: 't18', time: '10-02 20:20', cp: '万达影城', item: '电影票 ×2', amt: -38.0, dir: 'expense', l1: '支出', l2: '通讯娱乐 · 娱乐票务', method: '微信支付', batch: 'B-20261002-1', row: 4, status: 'excluded', note: '公司报销，已排除出个人支出' },
  { id: 't19', time: '10-01 11:00', cp: '未知商户 8871', item: '二维码收款', amt: -36.7, dir: 'expense', l1: '支出', l2: '未分类', method: '微信支付', batch: 'B-20261001-1', row: 2, status: 'pending', note: '' },
  { id: 't20', time: '10-01 09:20', cp: '校园洗衣房', item: '自助洗衣', amt: -8.0, dir: 'expense', l1: '支出', l2: '未分类', method: '微信支付', batch: 'B-20261001-1', row: 1, status: 'pending', note: '' },
];

const PEND_GROUPS = [
  { cp: '便利店', items: [{ item: '日用品', amt: -23.5, time: '10-17 21:30' }, { item: '零食', amt: -12.8, time: '10-17 21:34' }] },
  { cp: '未知商户 8871', items: [{ item: '二维码收款', amt: -36.7, time: '10-01 11:00' }] },
  { cp: '校园洗衣房', items: [{ item: '自助洗衣', amt: -8.0, time: '10-01 09:20' }] },
];

const ST = {
  confirmed: { t: '已分类', c: 'ok' },
  corrected: { t: '已修正', c: 'info' },
  pending: { t: '待确认', c: 'warn' },
  excluded: { t: '已排除', c: 'neutral' },
  uploaded: { t: '已上传', c: 'neutral' },
  mapping: { t: '待映射', c: 'info' },
  ready: { t: '待确认', c: 'warn' },
  importing: { t: '入库中', c: 'info' },
  done: { t: '已入库', c: 'ok' },
  dropped: { t: '已丢弃', c: 'neutral' },
  failed: { t: '失败', c: 'danger' },
  cleaning: { t: '文件待清理', c: 'warn' },
};
const stBadge = (s) => {
  const m = ST[s] || ST.confirmed;
  return `<span class="badge badge--${m.c}">${m.t}</span>`;
};
const DIR = { income: '收入', expense: '支出', neutral: '中性' };

/* ---------- 批次 / 原始库 / 备份 / 规则 / 分类 ---------- */
const BATCHES = [
  { id: 'B-20261021-1', file: '微信支付账单(20261001-20261021).csv', ch: '微信', status: 'ready', rows: 42, size: '86 KB', at: '10-21 19:54', note: '新增 38 / 重复 3 / 待确认 1' },
  { id: 'B-20261020-1', file: '支付宝交易明细(20261001-20261020).csv', ch: '支付宝', status: 'ready', rows: 128, size: '214 KB', at: '10-20 21:10', note: '新增 121 / 重复 5 / 待确认 2' },
  { id: 'B-20261021-2', file: '微信支付账单_备份.xlsx', ch: '微信', status: 'mapping', rows: 42, size: '112 KB', at: '10-21 20:02', note: '5 个核心字段已自动命中' },
  { id: 'B-20261019-1', file: '招商银行流水(202609).xlsx', ch: '银行卡', status: 'failed', rows: 0, size: '64 KB', at: '10-19 10:22', note: '编码探测失败：疑似 GB18030 变体' },
  { id: 'B-20261018-1', file: '微信支付账单(202609).csv', ch: '微信', status: 'done', rows: 96, size: '168 KB', at: '10-18 09:30', note: '新增 92 / 重复 4 / 待确认 0' },
  { id: 'B-20261017-1', file: '支付宝交易明细(202609).csv', ch: '支付宝', status: 'done', rows: 142, size: '232 KB', at: '10-17 08:12', note: '新增 140 / 重复 2 / 待确认 3' },
  { id: 'B-20261015-2', file: '零钱通收益明细.csv', ch: '微信', status: 'dropped', rows: 31, size: '12 KB', at: '10-15 16:40', note: '用户丢弃（非记账范围）' },
  { id: 'B-20261014-1', file: '微信支付账单(202608).csv', ch: '微信', status: 'cleaning', rows: 88, size: '148 KB', at: '10-14 20:05', note: '文件被占用，待清理重试' },
];

const MONTHS = [
  { m: '2026-10', n: 21, batches: 6, status: '进行中' },
  { m: '2026-09', n: 118, batches: 3, status: '已归档' },
  { m: '2026-08', n: 132, batches: 4, status: '已归档' },
  { m: '2026-07', n: 141, batches: 3, status: '已归档' },
  { m: '2026-06', n: 108, batches: 2, status: '已归档' },
  { m: '2026-05', n: 126, batches: 3, status: '已归档' },
  { m: '2026-04', n: 116, batches: 2, status: '已归档' },
  { m: '2026-03', n: 124, batches: 3, status: '已归档' },
  { m: '2026-02', n: 92, batches: 2, status: '已归档' },
  { m: '2026-01', n: 103, batches: 2, status: '已归档' },
];

const RULES = [
  { kw: '美团', field: '交易对方', l1: '支出', l2: '餐饮美食 · 外卖', p: 100, on: true, hit: 128 },
  { kw: '饿了么', field: '交易对方', l1: '支出', l2: '餐饮美食 · 外卖', p: 100, on: true, hit: 64 },
  { kw: '食堂', field: '交易对方', l1: '支出', l2: '餐饮美食 · 食堂', p: 90, on: true, hit: 186 },
  { kw: '瑞幸|星巴克|Manner', field: '交易对方', l1: '支出', l2: '餐饮美食 · 咖啡茶饮', p: 90, on: true, hit: 41 },
  { kw: '滴滴|高德打车', field: '交易对方', l1: '支出', l2: '交通出行 · 网约车', p: 80, on: true, hit: 52 },
  { kw: '零钱通|余额宝', field: '交易对方', l1: '资金流转', l2: '零钱通申购赎回', p: 120, on: true, hit: 37 },
  { kw: '信用卡还款', field: '商品说明', l1: '资金流转', l2: '信用卡还款', p: 120, on: true, hit: 9 },
  { kw: '便利店', field: '交易对方', l1: '支出', l2: '购物消费 · 日用百货', p: 60, on: false, hit: 12 },
];

const CATS = [
  { l1: '收入', on: true, n: 5, l2: [['家人资助', 42], ['奖学金助学金', 8], ['兼职收入', 3], ['红包收入', 5], ['其他收入', 2]] },
  { l1: '支出', on: true, n: 9, l2: [['餐饮美食', 412], ['交通出行', 286], ['购物消费', 124], ['学习资料', 68], ['居住缴费', 24], ['通讯娱乐', 96], ['医疗健康', 6], ['人情往来', 18], ['其他支出', 11]] },
  { l1: '资金流转', on: true, n: 4, l2: [['零钱通申购赎回', 37], ['信用卡还款', 9], ['银行卡互转', 5], ['提现', 3]] },
];

const BACKUPS = [
  { name: 'finance-2026-10-13.sqlite', size: '4.2 MB', at: '10-13 21:04', kind: '数据库备份' },
  { name: 'finance-2026-10-06.sqlite', size: '4.1 MB', at: '10-06 20:11', kind: '数据库备份' },
  { name: 'export-2026-09-30.csv', size: '1.8 MB', at: '09-30 18:22', kind: '全量导出' },
  { name: 'finance-2026-09-29.sqlite', size: '3.9 MB', at: '09-29 19:40', kind: '数据库备份' },
];
