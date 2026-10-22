/* 备份与恢复：数据库整体备份 + 全量导出；恢复前自动备份，可一键回退。 */

import {api} from '../core/api.js';
import {card, pageHead, toast, modal, closeLayer, confirmDialog, fieldValue, emptyState} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, bytes, shortDateTime, daysBetween} from '../core/format.js';

const KIND = { db: '数据库备份', export_json: '全量导出', export_csv: '全量导出', pre_restore: '恢复前自动备份', rollback: '回退点' };
let lastRestore = null;

export async function render() {
  const data = await api.backup.list();
  const items = data.items || [];
  const dbs = items.filter((b) => b.kind === 'db' || b.kind === 'pre_restore');
  const last = data.last_at;
  const days = last ? daysBetween(last, new Date().toISOString()) : null;

  const status = card({
    title: '备份状态',
    sub: '备份文件仅存本机，请自行妥善保管',
    body: `<div class="row" style="gap:16px;align-items:flex-start;margin-bottom:16px;flex-wrap:wrap">
        <div style="flex:1;min-width:160px">
          <div class="small muted">上次备份</div>
          <div class="num" style="font-size:var(--t-2xl);color:var(--text-1);margin-top:2px">${last ? shortDateTime(last) : '还没有备份'}</div>
          <div class="row" style="margin-top:6px">
            ${data.overdue ? `<span class="badge badge--warn">${days == null ? '从未备份' : `已 ${days} 天未备份`}</span>` : '<span class="badge badge--ok">备份在有效期内</span>'}
            <span class="tiny muted">提醒间隔 ${data.interval_days} 天</span>
          </div>
        </div>
        <div style="text-align:right">
          <div class="small muted">备份文件</div>
          <div class="num" style="font-size:var(--t-xl);color:var(--text-1);margin-top:4px">${dbs.length} 个</div>
          <div class="tiny muted">共 ${items.length} 个文件（含导出）</div>
        </div>
      </div>
      <div class="notice ${data.overdue ? 'notice--warn' : 'notice--info'}" style="margin-bottom:16px">
        <span class="notice__icon">${icon(data.overdue ? 'alert' : 'shield', 14)}</span>
        <div><b>${data.overdue ? '建议尽快备份。' : '当前备份状态正常。'}</b>备份文件不要上传到公开平台，也不要放在会被自动清理的目录。</div>
      </div>
      <div class="row" style="flex-wrap:wrap">
        <button class="btn btn--primary" data-act="backup">${icon('shield', 15)}立即备份数据库</button>
        <button class="btn btn--outline" data-act="export-json">${icon('download', 15)}导出 JSON</button>
        <button class="btn btn--ghost" data-act="export-csv">导出 CSV</button>
      </div>
      <p class="tiny muted" style="margin-top:12px">恢复前会自动备份当前库，失败可一键回退；全量导出是第二通道，不能直接用于恢复。</p>`,
  });

  const files = card({
    cls: 'card--flush',
    title: '本机备份文件',
    sub: `共 ${items.length} 个 · 数据库备份可恢复，导出文件仅供外部留存`,
    raw: items.length ? `<div style="padding:4px 20px 12px">
      ${items.map((b) => `<div class="backup-file">
        <span class="file-icon" style="background:var(--primary-soft);color:var(--primary-ink)">${icon(b.kind === 'db' || b.kind === 'pre_restore' ? 'db' : 'file', 16)}</span>
        <div style="flex:1;min-width:0"><b class="small strong" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(b.file_name)}</b>
          <span class="tiny muted">${bytes(b.size_bytes)} · ${shortDateTime(b.created_at)} · ${KIND[b.kind] || b.kind}</span></div>
        ${b.kind === 'db' || b.kind === 'pre_restore'
          ? `<button class="btn btn--outline btn--sm" data-act="restore" data-file="${esc(b.file_name)}">恢复</button>`
          : `<span class="badge badge--neutral">仅供留存</span>`}
      </div>`).join('')}
    </div>` : emptyState({ iconName: 'shield', title: '还没有备份文件', desc: '先做一次数据库备份，之后恢复才有依据。', actions: '<button class="btn btn--primary" data-act="backup">立即备份</button>' }),
    foot: `<span>${icon('lock', 12)} 不引导拷贝到外部介质</span><span class="tiny">最近 30 天</span>`,
  });

  const danger = card({
    cls: 'card--quiet',
    title: '恢复与回退',
    sub: '恢复是破坏性操作，务必先备份',
    body: `<div class="step" style="margin-bottom:10px"><span class="step__dot">1</span>
        <span class="small">选择备份文件 → 预览将恢复的记录数并校验完整性</span></div>
      <div class="step" style="margin-bottom:10px"><span class="step__dot">2</span>
        <span class="small">系统<b>自动备份当前库</b>，作为回退点</span></div>
      <div class="step" style="margin-bottom:14px"><span class="step__dot">3</span>
        <span class="small">输入「恢复」二次确认后执行；失败或中断可一键回退</span></div>
      <button class="btn btn--danger btn--block" data-act="default-restore">${icon('alert', 15)}从备份恢复…</button>
      ${lastRestore ? `<button class="btn btn--outline btn--block" style="margin-top:10px" data-act="rollback" data-id="${esc(lastRestore.pre_backup_id)}">${icon('refresh', 15)}回退到恢复前</button>` : ''}
      <p class="tiny muted" style="margin-top:10px;text-align:center">恢复期间服务不可用，请勿关闭页面</p>`,
  });

  return pageHead('备份与恢复', '防止数据丢失 · 双通道：数据库整体备份 + 全量导出',
    `<button class="btn btn--ghost" data-go="help">${icon('help', 15)}备份指引</button>`)
    + `<div class="grid g-12">
      <div class="c-7">${status}</div>
      <div class="c-5">${files}</div>
      <div class="c-5">${danger}</div>
      <div class="c-7"><div class="notice notice--info"><span class="notice__icon">${icon('shield', 15)}</span>
        <div><b>恢复前自动备份（EX-19）</b><br>每次恢复都会先在 backups/ 生成一个 rollback-时间戳 的副本。恢复失败时页面会出现「回退到恢复前」按钮，一键还原。</div></div>
        <div class="notice" style="margin-top:12px"><span class="notice__icon">${icon('db', 15)}</span>
        <div><b>恢复会覆盖什么</b><br>整个数据库文件（含 raw 分表、主数据、规则、分类、设置）。缓冲区文件不参与恢复。</div></div>
      </div></div>
    </div>`;
}

async function restoreFlow(fileName) {
  try {
    const v = await api.backup.validate(fileName);
    if (!v.valid) {
      toast(v.reason || '备份文件校验失败', 'warn');
      return;
    }
    modal({
      title: '从备份恢复',
      sub: '恢复会覆盖整个数据库文件',
      body: `<div class="batch-trace" style="margin-bottom:16px">${icon('db', 14)}
          <span class="mono">${esc(fileName)}</span>
          <span class="badge badge--ok" style="margin-left:auto">校验通过</span></div>
        <div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
          <div class="kv"><div class="kv__k">将恢复流水</div><div class="kv__v">${fmt(v.counts.transactions, 0)}<small>笔</small></div></div>
          <div class="kv"><div class="kv__k">raw 原始行</div><div class="kv__v">${fmt(v.counts.raw_records, 0)}<small>行</small></div></div>
          <div class="kv"><div class="kv__k">规则 / 分类</div><div class="kv__v">${v.counts.rules} / ${v.counts.categories}</div></div>
          <div class="kv"><div class="kv__k">schema 版本</div><div class="kv__v">v${v.schema_version}</div></div>
        </div>
        <div class="notice notice--ok" style="margin-bottom:16px"><span class="notice__icon">${icon('shield', 14)}</span>
          <div>恢复前会自动把当前库备份为 <b class="mono">rollback-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.sqlite</b>，失败可一键回退。</div></div>
        <div class="field"><label class="field__label">输入「恢复」以确认 <span class="req">*</span></label>
          <input class="input" data-field="confirm" placeholder="恢复"></div>`,
      foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
        <button class="btn btn--danger" data-act="ok">执行恢复</button>`,
      acts: {
        cancel: () => closeLayer(),
        ok: async (el) => {
          if (fieldValue(el, 'confirm') !== '恢复') return toast('请输入「恢复」以确认', 'warn');
          try {
            const res = await api.backup.restore(fileName);
            lastRestore = res;
            closeLayer();
            toast('恢复完成，已按备份重建数据库', 'ok');
            window.__fdRefresh?.();
          } catch (err) { toast(err.message, 'warn'); }
        },
      },
    });
  } catch (err) { toast(err.message, 'warn'); }
}

export const actions = {
  backup: async (_d, _el, ctx) => {
    try {
      const b = await api.backup.create('手动备份');
      toast(`已创建备份：${b.file_name}`, 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'export-json': async () => {
    try {
      const r = await api.backup.export('json');
      toast(`已导出 ${r.rows} 条到 ${r.file_name}`, 'ok');
    } catch (err) { toast(err.message, 'warn'); }
  },
  'export-csv': async () => {
    try {
      const r = await api.backup.export('csv');
      toast(`已导出 ${r.rows} 条到 ${r.file_name}`, 'ok');
    } catch (err) { toast(err.message, 'warn'); }
  },
  restore: (data) => restoreFlow(data.file),
  'default-restore': async () => {
    const data = await api.backup.list();
    const first = (data.items || []).find((b) => b.kind === 'db');
    if (!first) return toast('还没有可用的数据库备份', 'warn');
    restoreFlow(first.file_name);
  },
  rollback: async (data, _el, ctx) => {
    const ok = await confirmDialog({
      title: '回退到恢复前的状态？',
      sub: '会用恢复前自动生成的备份覆盖当前数据库',
      body: '<p class="small muted">如果你已经在恢复后录入了新数据，回退会丢失这些改动，请确认。</p>',
      confirmText: '一键回退',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.backup.rollback(data.id);
      toast('已回退到恢复前状态', 'ok');
      lastRestore = null;
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
};
