/* 前端契约冒烟（零依赖）。
 *
 * 用法：node --experimental-default-type=module scripts/check-frontend.mjs
 *
 * 做两件事：
 *   1. 对 static/assets/js 下所有模块做语法检查；
 *   2. 直接调用本地契约数据源，断言「统计三入口同源」「导入链路幂等」「模板/重算/备份」。
 * 真实后端的同一组断言在 C4/C5 交付后应由 pytest 承担，本脚本只守前端契约消费面。
 */

import { spawnSync } from 'node:child_process';
import { readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
const jsRoot = join(root, 'src/account_dashboard/static/assets/js');

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith('.js')) out.push(p);
  }
  return out;
}

let failed = 0;
for (const file of walk(jsRoot)) {
  const r = spawnSync(process.execPath, ['--check', file], { encoding: 'utf8' });
  if (r.status !== 0) {
    console.error(`✗ 语法错误 ${file}\n${r.stderr}`);
    failed = 1;
  }
}
if (failed) process.exit(1);
console.log(`✓ 语法检查：${walk(jsRoot).length} 个模块`);

const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};

const { handle } = await import(pathToFileURL(join(jsRoot, 'core/mock.js')).href);
const assert = (cond, message) => { if (!cond) throw new Error(message); };
const get = (path, query) => handle('GET', path, { query });
const post = (path, body) => handle('POST', path, { body });

const now = new Date();
const anchor = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
const overview = await get('/stats/overview', { period: 'month', anchor });
const summary = await get('/transactions/summary', { period: 'month', anchor });
const report = await get('/reports/monthly', { year: +anchor.slice(0, 4), month: +anchor.slice(5, 7) });
assert(overview.kpi.balance_cents === overview.kpi.total_income_cents - overview.kpi.total_expense_cents, '结余 ≠ 收入 − 支出');
assert(summary.expense_cents === overview.kpi.total_expense_cents, '明细汇总与统计口径不一致');
assert(report.kpi.total_expense_cents === overview.kpi.total_expense_cents, '月报与仪表盘口径不一致');
console.log('✓ 统计三入口同源');

const created = await handle('POST', '/staging/batches', {
  form: { get: (k) => (k === 'file' ? { name: '微信支付账单(20261001-20261021).csv', size: 88000 } : k === 'channel' ? 'wechat' : null) },
});
const preview = await get(`/staging/batches/${created.id}/preview`, { limit: 20 });
assert(Array.isArray(preview.headers) && preview.headers.length > 0, 'PreviewDTO 缺少 headers');
assert(preview.rows.every((r) => Array.isArray(r.cells)), 'PreviewRowDTO 缺少 cells');
assert(preview.suggested_mapping && preview.suggested_mapping.occurred_at >= 0, '缺少 suggested_mapping');

const mapped = await handle('PUT', `/staging/batches/${created.id}/mapping`, {
  body: { ...preview.suggested_mapping, save_template: false },
});
assert(mapped.batch.status === 'prechecked', 'PUT /mapping 未置 prechecked（D-1）');
const precheck = await post(`/staging/batches/${created.id}/precheck`, {});
assert(precheck.summary.total === preview.total_rows, '预检总行数与文件行数不一致');
const dup = precheck.rows.find((r) => r.label === 'dup');
if (dup) {
  await post(`/staging/batches/${created.id}/overrides`, { row_no: dup.row_no, reason: '冒烟测试' });
  const again = await post(`/staging/batches/${created.id}/precheck`, {});
  assert(again.rows.find((r) => r.row_no === dup.row_no).label === 'new', '强制新增未翻转为 new');
}
const ing = await post(`/staging/batches/${created.id}/confirm`, {});
let idempotent = false;
try { await post(`/staging/batches/${created.id}/confirm`, {}); } catch (err) { idempotent = err.code === 'E2002'; }
assert(idempotent, '重复确认未返回 E2002');
assert(ing.inserted >= 0 && ing.finished_at, 'IngestReportDTO 字段不完整');
console.log(`✓ 导入链路：total=${ing.total} inserted=${ing.inserted} dup=${ing.skipped_dup} pending=${ing.pending}`);

const templates = await get('/staging/templates', { channel: 'wechat' });
assert(templates.some((t) => 'spec' in t), 'TemplateDTO 缺少 spec 字段');
let conflict = false;
try {
  await post('/staging/templates', { channel: 'wechat', name: '冒烟模板', spec: preview.suggested_mapping, policy: 'abort' });
} catch (err) { conflict = err.code === 'E2003'; }
assert(conflict, '模板 abort 未返回 E2003');
console.log('✓ 模板三策略与 E2003');

const recalc = await post('/recalc/preview', { scope: 'all' });
assert(typeof recalc.to_recalc === 'number', 'RecalcPreview 字段缺失');
const run = await post('/recalc', { scope: 'all', confirm: true });
assert(typeof run.updated === 'number', 'RecalcReportDTO 字段缺失');

const backup = await post('/backup/db', { note: '冒烟' });
const valid = await post('/backup/restore/validate', { file_name: backup.file_name });
assert(valid.valid, '备份校验失败');
const restored = await post('/backup/restore', { file_name: backup.file_name, confirm: true });
assert(restored.pre_backup_id, '恢复未返回回退点');
await post('/backup/restore/rollback', { pre_backup_id: restored.pre_backup_id });
console.log('✓ 重算 / 备份 / 恢复 / 回退');

console.log('FRONTEND CONTRACT CHECK PASSED');
