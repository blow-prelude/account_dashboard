/* 数字、金额、时间与文本格式化。
   契约：API 金额恒为整数分，时间恒为 YYYY-MM-DDTHH:MM:SS（本地时间、无时区）。
   本模块是唯一做「分 → 元」换算的地方。 */

export const esc = (s) =>
  String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const fmt = (n, d = 2) =>
  Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmt0 = (n) => fmt(n, 0);
export const yuan = (cents) => Number(cents || 0) / 100;
export const money = (cents, d = 2) => fmt(yuan(cents), d);
export const cny = (cents, d = 2) => '¥' + money(cents, d);
export const signedMoney = (t) => {
  if (t.direction === 'income') return '+' + money(t.amount_cents);
  if (t.direction === 'expense') return '−' + money(t.amount_cents);
  return money(t.amount_cents);
};

export const pct = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : fmt(v, d) + '%');

/* ---------- 时间 ---------- */
export function parseLocal(iso) {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(iso);
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0));
}

export const shortDateTime = (iso) => {
  const d = parseLocal(iso);
  if (!d) return '—';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

export const fullDateTime = (iso) => {
  const d = parseLocal(iso);
  if (!d) return '—';
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

export const dateOnly = (iso) => (iso ? String(iso).slice(0, 10) : '—');
export const monthOf = (iso) => (iso ? String(iso).slice(0, 7) : '');
export const monthLabel = (ym) => (ym ? `${ym.slice(0, 4)} 年 ${Number(ym.slice(5, 7))} 月` : '—');
export const shortMonth = (ym) => (ym ? `${Number(ym.slice(5, 7))} 月` : '');

export function daysBetween(a, b) {
  const d1 = parseLocal(a), d2 = parseLocal(b);
  if (!d1 || !d2) return 0;
  return Math.max(0, Math.round((d2 - d1) / 86400000));
}

export const bytes = (n) => {
  const v = Number(n || 0);
  if (v < 1024) return v + ' B';
  if (v < 1024 ** 2) return fmt(v / 1024, 0) + ' KB';
  if (v < 1024 ** 3) return fmt(v / 1024 ** 2, 1) + ' MB';
  return fmt(v / 1024 ** 3, 2) + ' GB';
};

/* ---------- 统计周期锚点（契约 §6.4：2026-10 / 2026Q3 / 2026） ---------- */
export function anchorOf(kind, date = new Date()) {
  const y = date.getFullYear();
  const m = date.getMonth() + 1;
  if (kind === 'month') return `${y}-${String(m).padStart(2, '0')}`;
  if (kind === 'year') return String(y);
  return `${y}Q${Math.ceil(m / 3)}`;
}

export function prevAnchor(kind, anchor) {
  if (kind === 'month') {
    const [y, m] = anchor.split('-').map(Number);
    const d = new Date(y, m - 2, 1);
    return anchorOf('month', d);
  }
  if (kind === 'year') return String(Number(anchor) - 1);
  const [y, q] = anchor.split('Q').map(Number);
  return q === 1 ? `${y - 1}Q4` : `${y}Q${q - 1}`;
}

export function anchorLabel(kind, anchor) {
  if (kind === 'month') return monthLabel(anchor);
  if (kind === 'year') return `${anchor} 年度`;
  return `${anchor.slice(0, 4)} 年 Q${anchor.slice(5)}`;
}

/* 最近 N 个月的锚点（含当期），用于分类分析的 6 月走势 */
export function recentMonths(n, from = anchorOf('month')) {
  const out = [];
  let cur = from;
  for (let i = 0; i < n; i++) {
    out.unshift(cur);
    cur = prevAnchor('month', cur);
  }
  return out;
}

/* ---------- 涨跌：颜色由「是否有利」决定，而非正负（设计规范 7.3） ---------- */
export function deltaHtml(v, { good, unit = '%', flag = 'ok', d = 1 } = {}) {
  if (flag === 'na') return '<span class="delta delta--flat">—</span>';
  if (flag === 'new') return '<span class="delta delta--flat">新增</span>';
  if (v == null) return '<span class="delta delta--flat">—</span>';
  const arrow = v > 0 ? '▲' : v < 0 ? '▼' : '—';
  const cls = v === 0 ? 'flat' : good ? 'green' : 'red';
  return `<span class="delta delta--${cls}">${arrow}${fmt(Math.abs(v), d)}${unit === 'pt' ? ' pt' : '%'}</span>`;
}

export function bigMoney(cents) {
  const neg = cents < 0;
  const [i, d] = money(Math.abs(cents)).split('.');
  return `${neg ? '<span class="cur">−</span>' : ''}<span class="cur">¥</span>${i}<span style="font-size:.6em;color:var(--text-3);margin-left:1px">.${d}</span>`;
}

/* 图表轴上的紧凑金额（传入的是「元」） */
export function compactYuan(v) {
  if (v >= 10000) return fmt(v / 10000, v % 10000 === 0 ? 0 : 1) + ' 万';
  return fmt(v, 0);
}
