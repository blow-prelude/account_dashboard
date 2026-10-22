/* 契约化 API 客户端（SDD §6）。
 *
 * 约定（不可在页面层绕过）：
 *  - 所有响应恒为 ApiResponse{code,data,message}；失败用 ApiError 抛出；
 *  - 金额一律整数分，时间一律 YYYY-MM-DDTHH:MM:SS；
 *  - 路径前缀 /api/v1；查询参数按 §6.4 组合，数组用逗号连接；
 *  - 单页分页参数 page ≥ 1，page_size ∈ [10, 200]。
 *
 * 数据源：`?mock=1` 强制本地契约同构数据源；`?mock=0` 强制真实后端；
 * 缺省 auto —— /health 可达但统计端点未就绪（C2~C4 未交付）时自动落到本地数据源，
 * 并在顶栏明示，避免把演示数据误认为真实账单。
 */

export const API_PREFIX = '/api/v1';

let mode = 'live';
let mockHandler = null;

export class ApiError extends Error {
  constructor(code, message, status = 0, detail = null) {
    super(message || '请求失败');
    this.name = 'ApiError';
    this.code = code || 'E5001';
    this.status = status;
    this.detail = detail;
  }
  is(...codes) { return codes.includes(this.code); }
}

export const apiMode = () => mode;

function qs(query) {
  if (!query) return '';
  const parts = [];
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(Array.isArray(v) ? v.join(',') : String(v))}`);
  }
  return parts.length ? '?' + parts.join('&') : '';
}

async function rawFetch(method, path, { query, body, form, signal } = {}) {
  const url = API_PREFIX + path + qs(query);
  const init = { method, signal, headers: { Accept: 'application/json' } };
  if (form) {
    init.body = form;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  return fetch(url, init);
}

function payloadOf(json, status) {
  if (!json || typeof json !== 'object' || !('code' in json)) {
    throw new ApiError('E5001', '服务返回了无法识别的数据格式，请刷新重试', status);
  }
  if (json.code !== 'OK') {
    throw new ApiError(json.code, json.message || '请求未完成', status, json.data?.detail ?? json.data ?? null);
  }
  return json.data;
}

async function request(method, path, opts = {}) {
  if (mode === 'mock') return callMock(method, path, opts);

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), opts.timeout ?? 20000);
  let res;
  try {
    res = await rawFetch(method, path, { ...opts, signal: ctrl.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError('E5003', '请求超时，请确认本地服务仍在运行', 0);
    throw new ApiError('E5003', '无法连接本地服务，请确认后端已启动', 0);
  } finally {
    clearTimeout(timer);
  }

  let json = null;
  try { json = await res.json(); } catch { /* 非 JSON 响应按格式错误处理 */ }
  if (!res.ok && json && json.code) return payloadOf(json, res.status); // 抛 ApiError
  return payloadOf(json, res.status);
}

async function callMock(method, path, opts) {
  if (!mockHandler) mockHandler = await import('./mock.js');
  return mockHandler.handle(method, path, opts);
}

/* 供本地数据源复用同一套响应解析规则 */
export function unwrapEnvelope(json) {
  return payloadOf(json, 200);
}

/* ---------- 数据源探测 ---------- */
export async function initApi() {
  const sp = new URLSearchParams(location.search);
  const forced = sp.get('mock');
  if (forced === 'reset') {
    try { localStorage.removeItem('fd-mock-v3'); } catch { /* 隐私模式忽略 */ }
    mode = 'mock';
    return mode;
  }
  if (forced === '1') { mode = 'mock'; return mode; }
  if (forced === '0') { mode = 'live'; return mode; }

  try {
    const res = await rawFetch('GET', '/health', { signal: AbortSignal.timeout ? AbortSignal.timeout(2500) : undefined });
    if (!res.ok) { mode = 'mock'; return mode; }
    const json = await res.json().catch(() => null);
    if (!json || json.code !== 'OK') { mode = 'mock'; return mode; }
    // 探一个统计端点：后端 C4 未交付时仍是 404，此时用本地契约数据源
    const probe = await rawFetch('GET', '/stats/overview', {
      query: { period: 'month', anchor: new Date().toISOString().slice(0, 7) },
      signal: AbortSignal.timeout ? AbortSignal.timeout(2500) : undefined,
    });
    mode = probe.ok ? 'live' : 'mock';
  } catch {
    mode = 'mock';
  }
  return mode;
}

/* ---------- 端点 ---------- */
const q = (obj) => ({ query: obj });

export const api = {
  health: () => request('GET', '/health'),

  /* 统计（全部委托 stats_service，前端不做二次聚合） */
  overview: (period, anchor) => request('GET', '/stats/overview', q({ period, anchor })),
  statsCategories: ({ period, anchor, level = 1 }) =>
    request('GET', '/stats/categories', q({ period, anchor, level })),
  statsTrend: ({ period, anchor, granularity }) =>
    request('GET', '/stats/trend', q({ period, anchor, granularity })),
  topCounterparties: ({ period, anchor, limit = 5 }) =>
    request('GET', '/stats/top-counterparties', q({ period, anchor, limit })),
  dailyThreshold: ({ period, anchor }) =>
    request('GET', '/stats/daily-threshold', q({ period, anchor })),

  /* 报表 */
  monthlyReport: ({ year, month }) => request('GET', '/reports/monthly', q({ year, month })),
  quarterlyReport: ({ year, quarter }) => request('GET', '/reports/quarterly', q({ year, quarter })),
  yearlyReport: ({ year }) => request('GET', '/reports/yearly', q({ year })),

  /* 主数据层 */
  transactions: (query) => request('GET', '/transactions', q(query)),
  summary: (query) => request('GET', '/transactions/summary', q(query)),
  patchTransaction: (id, body) => request('PATCH', `/transactions/${encodeURIComponent(id)}`, { body }),
  batchCategory: (body) => request('POST', '/transactions/batch-category', { body }),
  excludeTransaction: (id, reason) => request('POST', `/transactions/${encodeURIComponent(id)}/exclude`, { body: { reason: reason || null } }),
  restoreTransaction: (id) => request('POST', `/transactions/${encodeURIComponent(id)}/restore`, { body: {} }),
  pending: ({ page = 1, page_size = 50 } = {}) => request('GET', '/pending', q({ page, page_size })),
  pendingCount: () => request('GET', '/pending/count'),
  trace: (id) => request('GET', `/transactions/${encodeURIComponent(id)}/trace`),

  /* 缓冲区 / 导入链路 */
  staging: {
    list: ({ status, page = 1, page_size = 50 } = {}) =>
      request('GET', '/staging/batches', q({ status, page, page_size })),
    create: (file, channel) => {
      const form = new FormData();
      form.append('file', file, file.name);
      if (channel && channel !== 'auto') form.append('channel', channel);
      return request('POST', '/staging/batches', { form, timeout: 60000 });
    },
    get: (id) => request('GET', `/staging/batches/${encodeURIComponent(id)}`),
    parse: (id) => request('POST', `/staging/batches/${encodeURIComponent(id)}/parse`, { body: {} }),
    preview: (id, limit = 20) =>
      request('GET', `/staging/batches/${encodeURIComponent(id)}/preview`, q({ limit })),
    saveMapping: (id, body) =>
      request('PUT', `/staging/batches/${encodeURIComponent(id)}/mapping`, { body }),
    templates: (channel) => request('GET', '/staging/templates', q({ channel })),
    saveTemplate: (body) => request('POST', '/staging/templates', { body }),
    precheck: (id) => request('POST', `/staging/batches/${encodeURIComponent(id)}/precheck`, { body: {} }),
    addOverride: (id, body) =>
      request('POST', `/staging/batches/${encodeURIComponent(id)}/overrides`, { body }),
    removeOverride: (id, rowNo) =>
      request('DELETE', `/staging/batches/${encodeURIComponent(id)}/overrides/${rowNo}`),
    confirm: (id) => request('POST', `/staging/batches/${encodeURIComponent(id)}/confirm`, { body: {} }),
    report: (id, includeSkipped = true) =>
      request('GET', `/staging/batches/${encodeURIComponent(id)}/report`, q({ include_skipped: includeSkipped })),
    discard: (id) =>
      request('POST', `/staging/batches/${encodeURIComponent(id)}/discard`, { body: { confirm: true } }),
    orphans: () => request('GET', '/staging/orphans'),
    cleanupOrphans: (names) => request('POST', '/staging/orphans/cleanup', { body: { names } }),
    usage: () => request('GET', '/staging/usage'),
    ensureDir: () => request('POST', '/staging/ensure-dir', { body: {} }),
  },

  /* 原始库 */
  raw: {
    months: () => request('GET', '/raw/months'),
    records: (yyyyMm, { page = 1, page_size = 50 } = {}) =>
      request('GET', `/raw/${encodeURIComponent(yyyyMm)}/records`, q({ page, page_size })),
    record: (id) => request('GET', `/raw/records/${encodeURIComponent(id)}`),
  },

  /* 规则 / 分类 / 重算 */
  rules: {
    list: (enabled) => request('GET', '/rules', q({ enabled })),
    create: (body) => request('POST', '/rules', { body }),
    patch: (id, body) => request('PATCH', `/rules/${encodeURIComponent(id)}`, { body }),
    toggle: (id, enabled) => request('POST', `/rules/${encodeURIComponent(id)}/toggle`, { body: { enabled } }),
    remove: (id) => request('DELETE', `/rules/${encodeURIComponent(id)}`),
  },
  categories: {
    list: (enabled) => request('GET', '/categories', q({ enabled })),
    create: (body) => request('POST', '/categories', { body }),
    patch: (id, body) => request('PATCH', `/categories/${encodeURIComponent(id)}`, { body }),
    disable: (id, body) => request('POST', `/categories/${encodeURIComponent(id)}/disable`, { body }),
  },
  recalc: {
    preview: (body) => request('POST', '/recalc/preview', { body }),
    run: (body) => request('POST', '/recalc', { body }),
  },

  /* 设置 / 数据目录 / 备份 */
  settings: {
    get: () => request('GET', '/settings'),
    update: (body) => request('PUT', '/settings', { body }),
    validateDir: (path) => request('POST', '/settings/data-dir/validate', { body: { path } }),
    migrate: (body) => request('POST', '/settings/data-dir/migrate', { body }),
  },
  backup: {
    list: () => request('GET', '/backup'),
    create: (note) => request('POST', '/backup/db', { body: { note: note || null } }),
    validate: (fileName) => request('POST', '/backup/restore/validate', { body: { file_name: fileName } }),
    restore: (fileName) => request('POST', '/backup/restore', { body: { file_name: fileName, confirm: true } }),
    rollback: (preBackupId) => request('POST', '/backup/restore/rollback', { body: { pre_backup_id: preBackupId } }),
    export: (format) => request('POST', '/backup/export', { body: { format } }),
  },

  /* 维护 */
  maintenance: {
    cleanup: (status = 'pending') => request('GET', '/maintenance/cleanup', q({ status })),
    retryCleanup: (id) => request('POST', `/maintenance/cleanup/${encodeURIComponent(id)}/retry`, { body: {} }),
    events: (limit = 100) => request('GET', '/maintenance/events', q({ limit })),
  },
};
