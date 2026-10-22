/* 全局状态：路由、周期锚点、筛选条件、缓存。
   只放「跨页面共享」的状态；页面内部的临时态留在页面模块里。 */

import { anchorOf, prevAnchor, recentMonths, monthOf } from './format.js';
import { api } from './api.js';

const today = new Date();

function lastCompletedQuarter(date) {
  const y = date.getFullYear();
  const q = Math.floor(date.getMonth() / 3) + 1;
  return q === 1 ? { y: y - 1, q: 4 } : { y, q: q - 1 };
}

const lq = lastCompletedQuarter(today);

export const state = {
  route: 'dashboard',
  theme: localStorage.getItem('fd-theme') === 'sky' ? 'sky' : 'pink',
  period: 'month',
  anchors: {
    month: anchorOf('month', today),
    quarter: `${lq.y}Q${lq.q}`,
    year: String(today.getFullYear()),
  },
  filters: {
    direction: 'all',
    status: 'all',
    category_l1: '',
    keyword: '',
    period: 'month',
    page: 1,
    page_size: 20,
    sort: '-occurred_at',
  },
  rawMonth: '',
  analysisCat: '',
  importBatchId: '',
  importStep: 1,
};

export const anchor = (kind = state.period) => state.anchors[kind];

export function setPeriod(kind) {
  if (!['month', 'quarter', 'year'].includes(kind)) return;
  state.period = kind;
  state.filters.period = kind;
  state.filters.page = 1;
}

export function periodQuery(kind = state.period) {
  return { period: kind, anchor: anchor(kind) };
}

export const monthAnchor = () => state.anchors.month;
export const sixtyMonths = () => recentMonths(6, state.anchors.month);

/* 分类树缓存：多个页面的下拉都要用，避免重复请求 */
let categoryCache = null;
let categoryPromise = null;
export async function loadCategories(force = false) {
  if (categoryCache && !force) return categoryCache;
  if (categoryPromise && !force) return categoryPromise;
  categoryPromise = api.categories.list(true)
    .then((nodes) => { categoryCache = nodes; return nodes; })
    .finally(() => { categoryPromise = null; });
  return categoryPromise;
}
export const categoriesSync = () => categoryCache;
export function invalidateCategories() { categoryCache = null; }

export function applyTheme(theme) {
  state.theme = theme === 'sky' ? 'sky' : 'pink';
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem('fd-theme', state.theme);
}

/* 周期切换后的锚点上下文（报表页需要 year/month/quarter 拆分） */
export function reportParams(kind = state.period) {
  const a = anchor(kind);
  if (kind === 'month') return { year: Number(a.slice(0, 4)), month: Number(a.slice(5, 7)) };
  if (kind === 'quarter') return { year: Number(a.slice(0, 4)), quarter: Number(a.slice(5)) };
  return { year: Number(a) };
}

export const prevOf = (kind) => prevAnchor(kind, anchor(kind));
export const monthOfIso = (iso) => monthOf(iso);
