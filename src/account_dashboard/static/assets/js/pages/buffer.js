/* 缓冲区：批次表 + 目录占用 + 待清理 / 孤儿文件。 */

import {api} from '../core/api.js';
import {state} from '../core/store.js';
import {card, pageHead, stBadge, emptyState, toast, confirmDialog} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, bytes, shortDateTime} from '../core/format.js';

const WAITING = new Set(['uploaded', 'mapped_pending', 'prechecked', 'failed']);

function resumeStep(status) {
  if (status === 'mapped_pending') return 2;
  if (status === 'prechecked') return 3;
  if (status === 'ingested') return 5;
  return 1;
}

export async function render() {
  const [batchesPage, usage, cleanup, orphans] = await Promise.all([
    api.staging.list({ page: 1, page_size: 100 }),
    api.staging.usage(),
    api.maintenance.cleanup('pending').catch(() => []),
    api.staging.orphans().catch(() => []),
  ]);
  const batches = batchesPage.items || [];
  const waiting = batches.filter((b) => WAITING.has(b.status)).length;
  const pct = usage.threshold ? Math.min(100, (usage.total_bytes / usage.threshold) * 100) : 0;
  const near = pct >= 90;

  const rowActions = (b) => {
    const parts = [];
    if (b.status === 'failed') parts.push(`<button class="btn btn--outline btn--sm" data-act="reparse" data-id="${esc(b.id)}">重新解析</button>`);
    if (['uploaded', 'mapped_pending', 'prechecked'].includes(b.status)) {
      parts.push(`<button class="btn btn--soft btn--sm" data-act="resume" data-id="${esc(b.id)}" data-status="${b.status}">继续处理</button>`);
    }
    if (b.status === 'ingested') parts.push(`<button class="btn btn--ghost btn--sm" data-act="resume" data-id="${esc(b.id)}" data-status="ingested">查看报告</button>`);
    if (!['ingested', 'discarded'].includes(b.status)) parts.push(`<button class="btn btn--ghost btn--sm" data-act="discard" data-id="${esc(b.id)}">丢弃</button>`);
    return parts.join('') || '<span class="tiny muted">—</span>';
  };

  const note = (b) => {
    if (b.status === 'failed') return `<span style="color:var(--danger)">${esc(b.fail_reason || '解析失败')}</span>`;
    if (b.status === 'prechecked') return `新增 ${b.new_count} / 重复 ${b.dup_count} / 待确认 ${b.pending_count}`;
    if (b.status === 'ingested') return `已入库 · ${b.pending_delete_flag ? '原文件待清理' : '原文件已删除'}`;
    if (b.status === 'discarded') return '用户丢弃（非记账范围）';
    if (b.status === 'mapped_pending') return '字段已识别，待确认映射';
    if (b.status === 'uploaded') return '已落盘，待解析';
    return '—';
  };

  const rows = batches.map((b) => `<tr>
    <td><div class="cell-2line"><span class="td-strong">${esc(b.file_name)}</span><small class="mono">${esc(b.id)}</small></div></td>
    <td><span class="badge badge--plain badge--neutral">${esc({ wechat: '微信', alipay: '支付宝', bank: '银行卡', other: '其他' }[b.channel] || b.channel)}</span></td>
    <td>${stBadge(b.status)}</td>
    <td class="td-num">${b.total_rows || '—'}</td>
    <td class="td-num">${bytes(b.file_size)}</td>
    <td class="td-muted num">${shortDateTime(b.created_at)}</td>
    <td class="td-muted" style="max-width:240px">${note(b)}</td>
    <td class="right nowrap">${rowActions(b)}</td>
  </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: '缓冲区批次',
    sub: `共 ${batches.length} 个批次 · 文件落盘于本地缓冲区，确认入库后删除`,
    actions: `<button class="btn btn--outline btn--sm" data-act="scan">${icon('search', 13)}重新扫描</button>
      <button class="btn btn--primary btn--sm" data-go="import">${icon('upload', 13)}上传新文件</button>`,
    raw: batches.length
      ? `<div class="table-wrap"><table class="table">
        <thead><tr><th>文件</th><th>渠道</th><th>状态</th><th class="right">行数</th><th class="right">大小</th><th>上传时间</th><th>预检 / 说明</th><th class="right">操作</th></tr></thead>
        <tbody>${rows}</tbody></table></div>`
      : emptyState({ iconName: 'buffer', title: '缓冲区是空的', desc: '导入账单时文件会先落在这里，确认入库后才写入数据库。', actions: '<button class="btn btn--primary" data-go="import">去导入账单</button>' }),
    foot: `<span>${icon('info', 12)} 状态单向流转，不接受从「已入库」回退</span>
      <span>等待处理 <b style="color:var(--text-1)">${waiting}</b> 个批次</span>`,
  });

  const space = card({
    title: '缓冲区目录',
    sub: '数据目录下的 buffer/ 子目录',
    body: `<div class="batch-trace" style="font-family:var(--font-mono);font-size:11.5px;margin-bottom:14px">
        ${icon('folder', 14)} ${esc(usage.path || `${state.health?.data_dir || '数据目录'}\\buffer`)}
      </div>
      <div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span class="small">已用 <b class="num">${bytes(usage.total_bytes)}</b> / ${bytes(usage.threshold)}</span>
        <span class="badge badge--${near ? 'warn' : 'ok'}">${near ? '接近阈值' : '容量充足'}</span>
      </div>
      <div class="progress"><div class="progress__bar" style="width:${pct.toFixed(1)}%;${near ? 'background:linear-gradient(90deg,var(--warn),var(--accent))' : ''}"></div></div>
      <p class="tiny muted" style="margin-top:10px">超过阈值会提醒清理；阈值可在设置中调整。目录被移动或删除时，启动自检会引导重建。</p>
      <div class="row" style="margin-top:14px">
        <button class="btn btn--outline btn--sm" data-act="ensure-dir">${icon('check', 13)}校验可读写</button>
        <button class="btn btn--ghost btn--sm" data-go="settings">修改数据目录</button>
      </div>`,
  });

  const cleanList = cleanup.map((c) => `<div class="backup-file">
      <span class="file-icon" style="background:var(--warn-soft);color:var(--warn)">${icon('file', 16)}</span>
      <div style="flex:1;min-width:0"><b class="small strong">${esc(c.file_name || c.file_path)}</b>
        <div class="tiny muted">${esc(c.reason)} · 尝试 ${c.attempts} 次</div></div>
      <button class="btn btn--outline btn--sm" data-act="retry-cleanup" data-id="${esc(c.id)}">重试</button>
    </div>`).join('');

  const orphanList = orphans.map((o) => `<div class="backup-file">
      <span class="file-icon" style="background:var(--surface-3);color:var(--text-3)">${icon('file', 16)}</span>
      <div style="flex:1;min-width:0"><b class="small strong">${esc(o.name)}</b>
        <div class="tiny muted">${bytes(o.size ?? o.size_bytes ?? 0)} · 无对应批次的孤儿文件</div></div>
      <button class="btn btn--ghost btn--sm" data-act="cleanup-orphan" data-name="${esc(o.name)}">清理</button>
    </div>`).join('');

  const clean = card({
    title: '待清理',
    sub: '删除失败或孤儿文件',
    body: `${cleanup.length || orphans.length ? '' : '<p class="small muted">没有待清理的文件，缓冲区很干净。</p>'}
      ${cleanup.length ? `<div class="notice notice--warn" style="margin-bottom:12px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div><b>${cleanup.length} 个文件待清理</b><br>数据已入库，物理删除时文件被占用。关闭占用程序后重试即可，数据不受影响。</div>
      </div>${cleanList}` : ''}
      ${orphans.length ? `<div class="section-label" style="margin:${cleanup.length ? '16px' : '0'} 0 8px">孤儿文件 · ${orphans.length} 个</div>${orphanList}` : ''}`,
    foot: `<span class="tiny">启动对账会在每次启动时自动重试</span>`,
  });

  return pageHead('缓冲区', '上传后的文件暂存于此，确认入库前不入库、不外传',
    `<button class="btn btn--ghost btn--sm" data-act="scan">${icon('refresh', 13)}刷新</button>`)
    + `<div class="grid g-12">
      <div class="c-12">${table}</div>
      <div class="c-7">${space}</div>
      <div class="c-5">${clean}</div>
    </div>`;
}

export const actions = {
  scan: (_d, _el, ctx) => { ctx.refresh(); toast('已重新扫描缓冲区', 'ok'); },
  resume: (data, _el, ctx) => {
    state.importBatchId = data.id;
    state.importStep = resumeStep(data.status);
    ctx.go('import', { keepBatch: true });
  },
  reparse: async (data, _el, ctx) => {
    try {
      await api.staging.parse(data.id);
      toast('重新解析完成，请继续确认映射', 'ok');
      state.importBatchId = data.id;
      state.importStep = 2;
      ctx.go('import', { keepBatch: true });
    } catch (err) { toast(err.message, 'warn'); }
  },
  discard: async (data, _el, ctx) => {
    const ok = await confirmDialog({
      title: '丢弃这个批次？',
      sub: '会删除缓冲区文件，已入库的主数据不受影响',
      body: '<p class="small muted">丢弃后状态变为「已丢弃」，不能继续处理。</p>',
      confirmText: '丢弃批次',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.staging.discard(data.id);
      toast('批次已丢弃', 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'retry-cleanup': async (data, _el, ctx) => {
    try {
      const res = await api.maintenance.retryCleanup(data.id);
      toast(res.status === 'abandoned' ? '多次重试仍失败，需手动删除' : '已重试删除，请稍后刷新', res.status === 'abandoned' ? 'warn' : 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'cleanup-orphan': async (data, _el, ctx) => {
    try {
      const res = await api.staging.cleanupOrphans([data.name]);
      toast(`已清理 ${res.deleted} 个孤儿文件`, 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'ensure-dir': async () => {
    try {
      const res = await api.staging.ensureDir();
      toast(`缓冲区目录可用：${res.path}`, 'ok');
    } catch (err) { toast(err.message, 'warn'); }
  },
};
