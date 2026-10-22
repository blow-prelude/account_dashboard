/* 轻量 SVG 图表：只接受「已聚合的数据 + 序列名 + 颜色变量」，不做任何业务计算。
   数据换算（分 → 元）由调用方在进入图表前完成。 */

import { fmt, compactYuan } from './format.js';

function niceTicks(v, count = 4) {
  const raw = v / count;
  if (raw <= 0) return { max: count, step: 1 };
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const n = raw / pow;
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  const mult = steps.find((x) => n <= x) || 10;
  const step = mult * pow;
  return { max: step * count, step };
}

function smooth(pts) {
  if (!pts.length) return '';
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2;
    d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
  }
  return d;
}

/* 支出趋势：面积折线 + 收入到账标注条 */
export function trendArea({ labels, values, marks = [], title = '支出趋势', id = 'trend' }) {
  const W = 800, H = 306;
  const pad = { l: 52, r: 18, t: 38, b: 30 };
  if (!labels.length) return '<div class="view-load">本期没有可绘制的数据</div>';
  const tick = niceTicks(Math.max(...values, 1) * 1.08, 4);
  const max = tick.max;
  const iw = W - pad.l - pad.r;
  const ih = H - pad.t - pad.b;
  const X = (i) => pad.l + (i * iw) / Math.max(1, labels.length - 1);
  const Y = (v) => pad.t + ih - (v / max) * ih;
  const pts = values.map((v, i) => [X(i), Y(v)]);
  const line = smooth(pts);
  const area = `${line} L${X(values.length - 1)},${pad.t + ih} L${pad.l},${pad.t + ih} Z`;

  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    const y = Y(v);
    grid += `<line class="gl" x1="${pad.l}" y1="${y.toFixed(1)}" x2="${W - pad.r}" y2="${y.toFixed(1)}"/>`;
    grid += `<text x="${pad.l - 10}" y="${(y + 3.5).toFixed(1)}" text-anchor="end">${compactYuan(v)}</text>`;
  }

  const step = Math.ceil(labels.length / 7);
  let xlab = '';
  labels.forEach((l, i) => {
    if (i % step !== 0 && i !== labels.length - 1) return;
    xlab += `<text class="lbl" x="${X(i).toFixed(1)}" y="${H - 10}" text-anchor="middle">${l}</text>`;
  });

  let markHtml = '';
  marks.forEach((m) => {
    if (m.i == null || m.i < 0 || m.i >= labels.length) return;
    const x = X(m.i);
    const label = `收入 ${fmt(m.value, 0)}`;
    const w = 82, h = 20;
    const bx = Math.min(Math.max(x - w / 2, pad.l), W - pad.r - w);
    markHtml += `<line x1="${x.toFixed(1)}" y1="${pad.t - 4}" x2="${x.toFixed(1)}" y2="${(pad.t + ih).toFixed(1)}"
      stroke="var(--chart-4)" stroke-width="1" stroke-dasharray="2 4" opacity=".55"/>`;
    markHtml += `<rect x="${bx.toFixed(1)}" y="6" width="${w}" height="${h}" rx="10" fill="var(--chart-4)" opacity=".14"/>`;
    markHtml += `<circle cx="${(bx + 11).toFixed(1)}" cy="16" r="3" fill="var(--chart-4)"/>`;
    markHtml += `<text x="${(bx + 19).toFixed(1)}" y="19.5" style="fill:var(--text-2);font-size:10px;font-family:var(--font-ui)">${label}</text>`;
  });

  let hits = '';
  pts.forEach(([x, y], i) => {
    const w = iw / Math.max(1, labels.length - 1);
    hits += `<rect class="hit" data-i="${i}" x="${(x - w / 2).toFixed(1)}" y="${pad.t}" width="${w.toFixed(1)}" height="${ih}"
      data-tip="${labels[i]} · 支出 ¥${fmt(values[i])}"/>`;
    hits += `<circle class="pt" data-i="${i}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.2" fill="var(--surface)" stroke="var(--chart-1)" stroke-width="1.8" opacity="0"/>`;
  });

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${title}">
    <defs><linearGradient id="g-${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--chart-1)" stop-opacity=".26"/>
      <stop offset="100%" stop-color="var(--chart-1)" stop-opacity=".01"/>
    </linearGradient></defs>
    ${grid}
    <path d="${area}" fill="url(#g-${id})"/>
    <path class="series-line" d="${line}" stroke="var(--chart-1)"/>
    ${markHtml}${hits}${xlab}
  </svg>`;
}

/* 分组柱：收支对比 */
export function compareBars(labels, series, opt = {}) {
  const W = opt.w || 780, H = opt.h || 260;
  const small = W < 520;
  const pad = { l: small ? 42 : 52, r: 14, t: 24, b: 30 };
  const fs = small ? 12 : 10.5;
  const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
  const all = series.flatMap((s) => s.values).filter((v) => v != null);
  if (!all.length) return '<div class="view-load">本期没有可对比的数据</div>';
  const tick = niceTicks(Math.max(...all) * 1.08, 4);
  const max = tick.max;
  const Y = (v) => pad.t + ih - (v / max) * ih;
  const n = labels.length || 1;
  const groupW = iw / n;
  const gapRatio = opt.gap != null ? opt.gap : 0.3;
  const bw = (groupW * (1 - gapRatio)) / Math.max(1, series.length);

  let grid = '';
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i, y = Y(v);
    grid += `<line class="gl" x1="${pad.l}" y1="${y.toFixed(1)}" x2="${W - pad.r}" y2="${y.toFixed(1)}"/>`;
    grid += `<text x="${pad.l - 9}" y="${(y + fs * 0.35).toFixed(1)}" text-anchor="end" style="font-size:${fs}px">${compactYuan(v)}</text>`;
  }

  let bars = '', xlab = '';
  labels.forEach((l, i) => {
    const gx = pad.l + groupW * i;
    const empty = series.every((s) => s.values[i] == null);
    series.forEach((s, si) => {
      const v = s.values[i];
      if (v == null || v === 0) return;
      const h = Math.max(ih - (Y(v) - pad.t), 1.5);
      const x = gx + groupW * (gapRatio / 2) + bw * si;
      bars += `<rect class="bar" x="${x.toFixed(1)}" y="${Y(v).toFixed(1)}" width="${(bw - 1.5).toFixed(1)}" height="${h.toFixed(1)}"
        rx="${Math.min(4, bw / 3).toFixed(1)}" fill="${s.color}" data-tip="${l} · ${s.name} ¥${fmt(v)}"/>`;
    });
    xlab += `<text class="lbl" x="${(gx + groupW / 2).toFixed(1)}" y="${H - 9}" text-anchor="middle"
      style="font-size:${fs}px;${empty ? 'opacity:.45' : ''}">${l}</text>`;
  });

  return `<div class="chart-legend" style="margin-bottom:6px">
      ${series.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join('')}
    </div>
    <svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="收支对比柱状图">
      ${grid}
      <line class="axis-line" x1="${pad.l}" y1="${pad.t + ih}" x2="${W - pad.r}" y2="${pad.t + ih}"/>
      ${bars}${xlab}
    </svg>`;
}

/* 环形图 */
export function donutChart(items, total, centerLabel) {
  const S = 196, cx = S / 2, cy = S / 2, r = 74, sw = 20;
  const gap = 0.038;
  let a = 0, paths = '';
  const polar = (rad, ang) => [cx + rad * Math.sin(ang), cy - rad * Math.cos(ang)];
  items.forEach((it) => {
    if (!total || !it.value) return;
    const sweep = (it.value / total) * Math.PI * 2;
    const a0 = a + gap / 2, a1 = a + sweep - gap / 2;
    if (a1 > a0) {
      const [x0, y0] = polar(r, a0);
      const [x1, y1] = polar(r, a1);
      const large = a1 - a0 > Math.PI ? 1 : 0;
      paths += `<path d="M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)}"
        fill="none" stroke="${it.color}" stroke-width="${sw}" stroke-linecap="round"
        class="seg" data-tip="${it.name} · ¥${fmt(it.value)} · ${((it.value / total) * 100).toFixed(1)}%"/>`;
    }
    a += sweep;
  });
  return `<svg class="chart" viewBox="0 0 ${S} ${S}" role="img" aria-label="支出分类占比">
    <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="var(--surface-3)" stroke-width="${sw}"/>
    ${paths}
    <text x="${cx}" y="${cy - 4}" text-anchor="middle"
      style="font-family:var(--font-num);font-size:19px;fill:var(--text-1);letter-spacing:-.02em">${centerLabel}</text>
    <text x="${cx}" y="${cy + 14}" text-anchor="middle"
      style="font-family:var(--font-ui);font-size:10px;fill:var(--text-3)">总支出</text>
  </svg>`;
}

export function sparkline(values, color = 'var(--chart-1)', w = 92, h = 30) {
  if (!values || values.length < 2) return '<span class="tiny muted">—</span>';
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 3 - ((v - min) / span) * (h - 6)]);
  const d = smooth(pts);
  const last = pts[pts.length - 1];
  return `<svg class="kpi__spark" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" opacity=".45"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2" fill="${color}"/>
  </svg>`;
}

export function spark(values, color = 'var(--chart-1)', w = 120, h = 30) {
  if (!values || values.length < 2) return '<span class="tiny muted">—</span>';
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * (w - 6) + 3, h - 4 - ((v - min) / span) * (h - 8)]);
  const last = pts[pts.length - 1];
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:${h}px;display:block" aria-hidden="true">
    <path d="${smooth(pts)}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${last[0]}" cy="${last[1]}" r="2.2" fill="${color}"/>
  </svg>`;
}

export function barBlocks(items, color = 'var(--primary)') {
  if (!items.length) return '<div class="view-load">暂无历史数据</div>';
  const max = Math.max(...items.map((i) => i.value), 1);
  return `<div class="bblocks">
    ${items.map((it, i) => `<div class="bblock">
      <span class="bblock__v">${fmt(it.value, 0)}</span>
      <span class="bblock__bar" style="height:${Math.max(8, (it.value / max) * 118).toFixed(0)}px;background:${color};opacity:${i === items.length - 1 ? 1 : 0.32}"></span>
      <span class="bblock__l">${it.label}</span>
    </div>`).join('')}
  </div>`;
}
