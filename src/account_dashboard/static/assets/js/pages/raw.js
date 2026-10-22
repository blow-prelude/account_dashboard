/* 原始库：按月只读归档 + 批次追溯 + 重算入口（与规则页共用同一服务）。 */

import {api} from '../core/api.js';
import {state} from '../core/store.js';
import {card, pageHead, emptyState, toast, modal, closeLayer} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, money, fullDateTime} from '../core/format.js';

export async function render() {
  const months = await api.raw.months().catch(() => []);
  if (!state.rawMonth && months.length) state.rawMonth = months[0].month;
  const current = months.find((m) => m.month === state.rawMonth) || months[0];
  const ym = current?.month || '';
  const page = ym ? await api.raw.records(ym, { page: 1, page_size: 50 }).catch(() => ({ items: [], meta: { total: 0, page: 1, page_size: 50, total_pages: 1 } })) : { items: [], meta: { total: 0 } };

  const monthList = `<section class="card">
    <div class="card__head"><div><div class="card__title">按月归档</div><div class="card__sub">raw_YYYY_MM · 只增不改</div></div></div>
    <div class="card__body" style="padding:10px">
      ${months.length ? `<div class="month-list">
        ${months.map((x) => `<button class="month-item" data-act="month" data-month="${esc(x.month)}" aria-current="${x.month === ym}">
          ${icon('db', 14)}<span>${esc(x.month.slice(0, 4))} 年 ${Number(x.month.slice(5))} 月</span><span class="month-item__n">${x.count}</span>
        </button>`).join('')}
      </div>` : emptyState({ iconName: 'archive', title: '还没有原始记录', desc: '导入并确认账单后，原始行会按月归档在这里。', actions: '<button class="btn btn--primary" data-go="import">去导入</button>' })}
    </div>
  </section>`;

  const rows = (page.items || []).map((r) => `<tr>
      <td class="td-muted num">${r.row_no}</td>
      <td class="num" style="font-size:12px">${fullDateTime(r.occurred_at)}</td>
      <td class="td-num">${r.direction === 'income' ? '+' : r.direction === 'expense' ? '−' : ''}${money(r.amount_cents)}</td>
      <td>${r.direction === 'income' ? '<span class="badge badge--ok">income</span>' : r.direction === 'neutral' ? '<span class="badge badge--neutral">neutral</span>' : '<span class="badge badge--plain" style="background:var(--surface-3)">expense</span>'}</td>
      <td class="td-strong">${esc(r.counterparty || '—')}</td>
      <td class="td-muted">${esc(r.item || '—')}</td>
      <td class="td-muted mono">${esc(r.batch_id)}</td>
    </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: ym ? `raw_${ym}` : '原始记录',
    sub: current ? `${fmt(current.count, 0)} 条原始记录 · 保留导入原貌，不可编辑` : '按月归档',
    actions: `<button class="btn btn--outline btn--sm" data-act="export">${icon('download', 13)}导出本页</button>
      <button class="btn btn--soft btn--sm" data-act="recalc">${icon('refresh', 13)}从原始库重算</button>`,
    raw: (page.items || []).length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th>行号</th><th>交易时间</th><th class="right">金额</th><th>方向</th><th>交易对方</th><th>商品说明</th><th>来源批次</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : emptyState({ iconName: 'archive', title: '这个月还没有原始记录', desc: '切换左侧月份，或先导入该月账单。' }),
    foot: `<span>${icon('lock', 12)} raw 表禁止修改，更正错误需重新导入正确文件并排除错误批次</span>
      <span>显示 ${(page.items || []).length} / ${page.meta.total} 条</span>`,
  });

  const trace = card({
    title: '批次追溯',
    sub: '任一条主数据都能回到原始行与当时的映射快照',
    body: `<div class="row" style="gap:8px;margin-bottom:12px;flex-wrap:wrap">
        <div class="input-group" style="flex:1;min-width:220px">
          <span class="input-group__icon">${icon('search', 14)}</span>
          <input class="input" data-field="txid" placeholder="输入流水 ID，例如 T-202610-0001" style="height:32px;font-size:13px">
        </div>
        <button class="btn btn--outline btn--sm" data-act="trace">${icon('arrowUpRight', 13)}追溯</button>
      </div>
      <div id="trace-result" class="stack" style="gap:10px">
        <p class="small muted">追溯会返回：主数据 → 来源批次 / 原始行号 → raw 分表 → 入库时的字段映射快照。</p>
      </div>`,
  });

  return pageHead('原始库', '按月分表归档导入原貌 · 审计与重算的唯一基础',
    `<div class="segmented"><button class="segmented__item" aria-pressed="true">按月</button><button class="segmented__item" data-go="detail">按流水查</button></div>`)
    + `<div class="grid g-12">
      <div class="c-3">${monthList}</div>
      <div class="c-9 stack">${table}
        <div class="notice notice--info">
          <span class="notice__icon">${icon('info', 15)}</span>
          <div>重算与「分类规则」页共用同一重算服务：默认只处理未经人工修正/排除的记录，执行前会提示影响范围，失败整体回滚。</div>
        </div>
      </div>
      <div class="c-12">${trace}</div>
    </div>`;
}

export const actions = {
  month: (data, _el, ctx) => { state.rawMonth = data.month; ctx.refresh(); },
  recalc: async () => {
    try {
      const preview = await api.recalc.preview({ scope: 'all' });
      modal({
        title: '重算历史流水',
        sub: '按当前规则集重新分类，不影响 raw 原始库',
        body: `<div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
            <div class="kv"><div class="kv__k">将重算</div><div class="kv__v">${preview.to_recalc}<small>条</small></div></div>
            <div class="kv"><div class="kv__k">其中人工修正 / 排除</div><div class="kv__v" style="color:var(--primary-ink)">${preview.manual_kept}<small>条</small></div></div>
          </div>
          <div class="notice notice--info" style="margin-bottom:16px">
            <span class="notice__icon">${icon('info', 14)}</span>
            <div>默认<b>只处理未经人工修正 / 排除</b>的记录；这 ${preview.manual_kept} 条保持不变，报告中单列。</div>
          </div>
          <label class="checkbox" style="margin-bottom:8px"><input type="checkbox" data-field="overwrite"><span class="checkbox__box"></span>同时覆盖人工修正结果（不推荐）</label>
          <p class="tiny muted">重算为事务操作，失败整体回滚，不会出现「半新半旧」。</p>`,
        foot: `<span class="tiny muted" style="margin-right:auto">${icon('lock', 12)} raw 表不变</span>
          <button class="btn btn--ghost" data-act="cancel">取消</button>
          <button class="btn btn--primary" data-act="ok">开始重算</button>`,
        acts: {
          cancel: () => closeLayer(),
          ok: async (el) => {
            const overwrite = el.querySelector('[data-field="overwrite"]').checked;
            try {
              const res = await api.recalc.run({ scope: 'all', overwrite_manual: overwrite, confirm: true });
              closeLayer();
              toast(`重算完成：更新 ${res.updated} 条，人工修正 ${res.manual_kept} 条未重算`, 'ok');
              window.__fdRefresh?.();
            } catch (err) { toast(err.message, 'warn'); }
          },
        },
      });
    } catch (err) { toast(err.message, 'warn'); }
  },
  trace: async () => {
    const id = document.querySelector('[data-field="txid"]')?.value?.trim();
    const box = document.getElementById('trace-result');
    if (!id) return toast('请输入要追溯的流水 ID', 'warn');
    try {
      const t = await api.trace(id);
      const snap = t.mapping_snapshot || {};
      box.innerHTML = `
        <div class="batch-trace" style="flex-wrap:wrap;gap:6px">${icon('list', 14)}
          <span>${esc(t.transaction.id)}</span>${icon('chevronR', 12)}
          <span class="mono">${esc(t.transaction.batch_id)} / row ${t.transaction.row_no}</span>${icon('chevronR', 12)}
          <span class="mono">raw_${esc(String(t.transaction.occurred_at).slice(0, 7).replace('-', '_'))}</span>
          <span class="badge badge--ok" style="margin-left:auto">链路完整</span>
        </div>
        <div class="kv-grid" style="grid-template-columns:repeat(4,1fr)">
          <div class="kv"><div class="kv__k">交易时间</div><div class="kv__v" style="font-size:13px">${fullDateTime(t.transaction.occurred_at)}</div></div>
          <div class="kv"><div class="kv__k">金额</div><div class="kv__v" style="font-size:13px">${money(t.transaction.amount_cents)}</div></div>
          <div class="kv"><div class="kv__k">对方</div><div class="kv__v" style="font-size:13px">${esc(t.transaction.counterparty || '—')}</div></div>
          <div class="kv"><div class="kv__k">原始行</div><div class="kv__v" style="font-size:13px">第 ${t.raw_record ? t.raw_record.row_no : '—'} 行</div></div>
        </div>
        ${snap.occurred_at != null ? `<div class="table-wrap" style="border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden">
          <table class="table table--compact"><thead><tr><th>映射快照（入库时）</th><th>文件列索引</th></tr></thead>
          <tbody>
            <tr><td>交易时间</td><td class="mono">${snap.occurred_at}</td></tr>
            <tr><td>金额</td><td class="mono">${snap.amount} · scale=${snap.amount_scale ?? 1}</td></tr>
            <tr><td>收支方向</td><td class="mono">${snap.direction}</td></tr>
            <tr><td>交易对方</td><td class="mono">${snap.counterparty ?? '未映射'}</td></tr>
          </tbody></table></div>` : '<p class="tiny muted">该批次没有保存映射快照（历史批次）。</p>'}`;
    } catch (err) {
      box.innerHTML = `<div class="notice notice--danger"><span class="notice__icon">${icon('alert', 14)}</span><div>${esc(err.message)}</div></div>`;
    }
  },
  export: () => {
    const rows = [...document.querySelectorAll('.table tbody tr')];
    const lines = [['行号', '交易时间', '金额', '方向', '对方', '商品', '批次'].join(',')];
    rows.forEach((tr) => {
      const cells = [...tr.querySelectorAll('td')].map((td) => `"${td.textContent.trim().replace(/"/g, '""')}"`);
      if (cells.length) lines.push(cells.join(','));
    });
    const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `raw_${state.rawMonth}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast('已导出当前页原始记录', 'ok');
  },
};
