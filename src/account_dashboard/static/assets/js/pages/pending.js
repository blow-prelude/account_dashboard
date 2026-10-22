/* 待确认队列：按对方聚合，批量归类，可同时生成规则。 */

import {api} from '../core/api.js';
import {loadCategories} from '../core/store.js';
import {card, pageHead, emptyState, toast, categoryOptions} from '../core/ui.js';
import {openTransaction} from '../core/tx-drawer.js';
import {icon} from '../core/icons.js';
import {esc, money, shortDateTime} from '../core/format.js';

export async function render() {
  const [groupsPage, nodes] = await Promise.all([
    api.pending({ page: 1, page_size: 200 }),
    loadCategories().catch(() => []),
  ]);
  const groups = groupsPage.items || [];
  const count = groups.reduce((s, g) => s + g.txn_count, 0);
  const total = groups.reduce((s, g) => s + g.amount_cents, 0);

  const actions = `<button class="btn btn--outline" data-act="refresh">${icon('refresh', 15)}刷新队列</button>
    <button class="btn btn--primary" data-go="import">${icon('upload', 15)}导入新账单</button>`;

  const list = `<section class="card" id="pending-card">
    <div class="card__head">
      <div><div class="card__title">待确认流水</div><div class="card__sub">未命中任何规则 · 共 ${count} 笔 / ${money(total)}</div></div>
      <div class="spacer"></div>
      <span class="badge badge--warn">已计入总支出</span>
    </div>
    <div class="card__body" id="pending-body" style="display:flex;flex-direction:column;gap:12px">
      ${!groups.length ? emptyState({
        iconName: 'checkCircle',
        title: '全部处理完了',
        desc: '本期「未分类」金额已归零，报表与明细已同步刷新。下次导入时新的未分类流水会出现在这里。',
        actions: '<button class="btn btn--outline" data-go="reports">看看报表</button>',
      }) : ''}
      ${groups.map((g, gi) => `<div class="pending-group" data-group="${gi}">
        <div class="pending-group__head" data-act="pick-group" data-g="${gi}">
          <label class="checkbox" onclick="event.stopPropagation()"><input type="checkbox" data-act="pick-cb" data-g="${gi}"><span class="checkbox__box"></span></label>
          <div><div class="pending-group__name">${esc(g.counterparty || '未知对方')}</div>
            <div class="pending-group__meta">${g.txn_count} 笔${g.txn_count > 1 ? ' · 同对方可一次归类' : ''}${g.hint_l2 ? ` · 平台提示「${esc(g.hint_l2)}」` : ''}</div></div>
          <span class="pending-group__amt">¥${money(g.amount_cents)}</span>
        </div>
        <div class="pending-group__body">
          ${(g.items || []).map((i) => `<div class="pending-line" data-act="open-tx" data-id="${esc(i.id)}" style="cursor:pointer">
            <span class="num">${shortDateTime(i.occurred_at)}</span>
            <span class="pending-line__item">${esc(i.item || i.txn_type || '—')}</span>
            <span class="pending-line__amt">${i.direction === 'income' ? '+' : '−'}${money(i.amount_cents)}</span>
          </div>`).join('')}
        </div>
      </div>`).join('')}
    </div>
    <div class="card__foot"><span>处理完成后队列清空，报表「未分类」金额归零</span>
      <span class="tiny">规则优先级：数值大者优先，同级取最新创建</span></div>
  </section>`;

  const aside = `<div class="stack assign-panel">
    <section class="card">
      <div class="card__head"><div><div class="card__title">批量归类</div><div class="card__sub">对已勾选的流水生效</div></div></div>
      <div class="card__body" style="display:flex;flex-direction:column;gap:16px">
        <div class="field">
          <label class="field__label">目标分类 <span class="req">*</span></label>
          <div class="select"><select class="select__native" data-field="cat"><option value="">请选择分类</option>${categoryOptions(nodes)}</select></div>
        </div>
        <label class="row" style="gap:10px;align-items:flex-start">
          <span class="switch" role="switch" aria-checked="true" data-act="toggle-rule"></span>
          <span><span class="small strong" style="display:block">同时生成规则</span>
            <span class="tiny muted">以后导入同对方流水时自动套用该分类</span></span>
        </label>
        <div class="notice notice--info" style="padding:10px 12px">
          <span class="notice__icon">${icon('info', 14)}</span>
          <div>归类后记录状态变为「已修正」，后续重算默认不覆盖。收支总额不变。</div>
        </div>
        <button class="btn btn--primary btn--block" data-act="apply">应用并处理</button>
        <p class="tiny muted" style="text-align:center">已选 <b id="pick-count">0</b> 组</p>
      </div>
    </section>
    <section class="card card--quiet">
      <div class="card__body">
        <div class="section-label" style="margin-bottom:8px">为什么会出现待确认</div>
        <p class="small muted">导入时未命中任何分类规则、或金额/时间解析失败。也可以先修规则，再一键重算历史流水。</p>
        <button class="btn btn--outline btn--sm btn--block" style="margin-top:12px" data-go="rules">去管理规则</button>
      </div>
    </section>
  </div>`;

  return pageHead('待确认队列', '集中处理未分类流水 · 按对方聚合，支持批量归类并生成规则', actions)
    + `<div class="grid g-12"><div class="c-8">${list}</div><div class="c-4">${aside}</div></div>`;
}

function checkedGroups() {
  return Array.from(document.querySelectorAll('#pending-body .pending-group'))
    .filter((g) => g.querySelector('input[type=checkbox]').checked);
}

function updateCount() {
  const n = checkedGroups().length;
  const el = document.getElementById('pick-count');
  if (el) el.textContent = n;
}

export const actions = {
  refresh: (_d, _el, ctx) => ctx.refresh(),
  'pick-group': (data) => {
    const box = document.querySelector(`.pending-group[data-group="${data.g}"]`);
    if (!box) return;
    const cb = box.querySelector('input[type=checkbox]');
    cb.checked = !cb.checked;
    box.classList.toggle('is-checked', cb.checked);
    updateCount();
  },
  'toggle-rule': (_d, el) => {
    const sw = el.classList?.contains('switch') ? el : el.querySelector('.switch');
    if (!sw) return;
    sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
  },
  'open-tx': (data, _el, ctx) => openTransaction(data.id, { onChanged: () => ctx.refresh() }),
  apply: async (_d, _el, ctx) => {
    const picked = checkedGroups();
    if (!picked.length) return toast('请先勾选要处理的流水', 'warn');
    const v = document.querySelector('[data-field="cat"]')?.value;
    if (!v) return toast('请选择目标分类', 'warn');
    const [l1, l2] = v.split('||');
    const ids = picked.flatMap((g) => Array.from(g.querySelectorAll('[data-act="open-tx"]')).map((x) => x.dataset.id));
    const ruleOn = document.querySelector('.assign-panel .switch')?.getAttribute('aria-checked') === 'true';
    try {
      const res = await api.batchCategory({ ids, l1, l2, create_rule: ruleOn });
      toast(`已处理 ${res.updated} 笔${res.rule_id ? '，规则已保存' : ''}`, 'ok');
      ctx.refresh();
    } catch (err) {
      toast(err.message, 'warn');
    }
  },
};

document.addEventListener('change', (e) => {
  if (window.__fdRoute !== 'pending') return;
  if (e.target.dataset.act !== 'pick-cb') return;
  const box = e.target.closest('.pending-group');
  box.classList.toggle('is-checked', e.target.checked);
  updateCount();
});
