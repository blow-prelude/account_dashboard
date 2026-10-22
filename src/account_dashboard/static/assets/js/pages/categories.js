/* 分类体系：一级（收支分组）→ 二级（消费大类）。
   停用被引用的分类必须先决定「保留历史」或「迁移」，迁移不改变收支总额。 */

import {api} from '../core/api.js';
import {loadCategories, invalidateCategories, state} from '../core/store.js';
import {card, pageHead, toast, modal, closeLayer, fieldValue} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt} from '../core/format.js';

export async function render() {
  const nodes = await loadCategories(true).catch(() => []);
  if (!nodes.some((n) => n.l1 === state.catL1)) {
    state.catL1 = nodes.find((n) => n.l1 === '支出')?.l1 || nodes[0]?.l1 || '支出';
  }
  const cur = nodes.find((n) => n.l1 === state.catL1) || { l1: '支出', children: [] };
  const totalRef = cur.children.reduce((s, c) => s + (c.ref_count || 0), 0);

  const l1 = `<section class="card card--flush">
    <div class="card__head"><div><div class="card__title">一级分类</div><div class="card__sub">${nodes.length} 个收支分组 · 只用于组织二级分类</div></div></div>
    <div class="cat-tree">
      ${nodes.map((n) => `<div class="cat-tree__l1 ${n.l1 === cur.l1 ? 'is-active' : ''}" data-act="pick-l1" data-l1="${esc(n.l1)}">
        ${icon('tag', 15)}<b>${esc(n.l1)}</b>
        <span class="cat-tree__count">${n.children.length} 个二级 · ${n.children.reduce((a, b) => a + (b.ref_count || 0), 0)} 笔</span>
        <div class="spacer"></div>
        ${icon('chevronR', 13)}
      </div>`).join('')}
    </div>
    <div class="card__foot"><span>${icon('info', 12)} 分类归属不影响收支统计</span><span class="tiny">统计以 direction 为准</span></div>
  </section>`;

  const rows = cur.children.map((c) => `<tr>
      <td class="td-strong">${esc(c.l2)}</td>
      <td class="td-num td-muted">${fmt(c.ref_count || 0, 0)}</td>
      <td><span class="switch" role="switch" aria-checked="${c.enabled}" data-act="toggle" data-id="${esc(c.id)}" data-l1="${esc(c.l1)}" data-l2="${esc(c.l2)}" data-ref="${c.ref_count || 0}"></span></td>
      <td class="right">
        <button class="btn btn--ghost btn--sm" data-act="rename" data-id="${esc(c.id)}" data-l2="${esc(c.l2)}">改名</button>
        <button class="btn btn--ghost btn--sm" data-act="disable" data-id="${esc(c.id)}" data-l1="${esc(c.l1)}" data-l2="${esc(c.l2)}" data-ref="${c.ref_count || 0}" ${c.enabled ? '' : 'disabled'}>停用</button>
      </td>
    </tr>`).join('');

  const l2 = `<section class="card card--flush">
    <div class="card__head"><div><div class="card__title">${esc(cur.l1)} · 二级分类</div>
      <div class="card__sub">${cur.children.length} 个分类 · 共 ${fmt(totalRef, 0)} 笔引用</div></div>
      <div class="spacer"></div>
      <button class="btn btn--soft btn--sm" data-act="add">${icon('plus', 13)}新增</button></div>
    ${cur.children.length ? `<div class="table-wrap"><table class="table">
      <thead><tr><th>二级分类</th><th class="right">引用笔数</th><th>启用</th><th class="right">操作</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
      : `<div class="empty"><div class="empty__art">${icon('tag', 30)}</div>
          <div class="empty__title">这一组还没有二级分类</div>
          <div class="empty__desc">新增一个分类后，规则和流水就可以引用它。</div>
          <div class="empty__actions"><button class="btn btn--primary" data-act="add">新增二级分类</button></div></div>`}
    <div class="card__foot"><span>${icon('lock', 12)} 被引用的分类不会被无声删除，停用需选择迁移方式</span></div>
  </section>`;

  return pageHead('分类体系', '维护一级 / 二级分类 · 停用引用中的分类必须先迁移',
    `<button class="btn btn--ghost" data-act="refresh">${icon('refresh', 15)}刷新</button>`)
    + `<div class="grid g-12"><div class="c-5">${l1}</div><div class="c-7">${l2}</div>
      <div class="c-12"><div class="notice notice--warn"><span class="notice__icon">${icon('alert', 15)}</span>
        <div><b>停用引用中的分类会怎样？</b> 系统会要求你选择「保留历史记录」或「迁移到其他分类」。迁移只改分类归属，<b>不改变总收入 / 总支出</b>。</div></div></div>
    </div>`;
}

function addModal(nodes) {
  modal({
    title: `新增「${state.catL1}」二级分类`,
    sub: '分类名称在同一分组内必须唯一',
    size: 'modal--sm',
    body: `<div class="field"><label class="field__label">分类名称 <span class="req">*</span></label>
        <input class="input" data-field="name" placeholder="例如：健身运动"></div>
      <div class="field" style="margin-top:12px"><label class="field__label">排序</label>
        <input class="input input--num" data-field="sort" type="number" value="999">
        <span class="field__hint">数值越小越靠前。</span></div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--primary" data-act="ok">新增分类</button>`,
    acts: {
      cancel: () => closeLayer(),
      ok: async (el) => {
        const name = fieldValue(el, 'name')?.trim();
        if (!name) return toast('分类名称不能为空', 'warn');
        try {
          await api.categories.create({ l1: state.catL1, l2: name, sort: Number(fieldValue(el, 'sort')) || 999 });
          closeLayer();
          invalidateCategories();
          toast('分类已新增', 'ok');
          window.__fdRefresh?.();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
  });
}

function renameModal(id, name) {
  modal({
    title: '修改分类名称',
    sub: '改名不会影响已归类流水的统计口径',
    size: 'modal--sm',
    body: `<div class="field"><label class="field__label">新名称 <span class="req">*</span></label>
      <input class="input" data-field="name" value="${esc(name)}"></div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--primary" data-act="ok">保存</button>`,
    acts: {
      cancel: () => closeLayer(),
      ok: async (el) => {
        const v = fieldValue(el, 'name')?.trim();
        if (!v) return toast('分类名称不能为空', 'warn');
        try {
          await api.categories.patch(id, { l2: v });
          closeLayer();
          invalidateCategories();
          toast('分类已改名', 'ok');
          window.__fdRefresh?.();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
  });
}

function disableModal(id, name, refCount, nodes, l1) {
  // 迁移目标限定在同一级分组内，避免「支出 · 餐饮」被迁到「收入 · 家人资助」这种语义错位
  const targets = nodes
    .filter((g) => g.l1 === l1)
    .flatMap((g) => g.children.filter((c) => c.id !== id && c.enabled)
      .map((c) => ({ l1: c.l1, l2: c.l2, label: `${c.l1} · ${c.l2}` })));
  modal({
    title: `停用「${name}」`,
    sub: refCount ? `该分类已被 ${refCount} 笔流水引用，必须先决定这些记录的去向` : '该分类当前没有被引用',
    body: `<label class="radio" style="display:flex;margin-bottom:12px;align-items:flex-start;gap:8px">
        <input type="radio" name="mig" value="keep" checked><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">保留历史记录</b><br><span class="tiny muted">已有 ${refCount} 笔仍显示原分类，但选择器中不再可选</span></span></label>
      <label class="radio" style="display:flex;margin-bottom:14px;align-items:flex-start;gap:8px">
        <input type="radio" name="mig" value="move"><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">迁移到其他分类</b><br><span class="tiny muted">这 ${refCount} 笔会改到新分类，收支总额不变</span></span></label>
      <div class="select"><select class="select__native" data-field="target" disabled>
        ${targets.length ? targets.map((t) => `<option value="${esc(t.l1)}||${esc(t.l2)}">${esc(t.label)}</option>`).join('') : '<option value="">该分组下没有其他可用分类</option>'}
      </select></div>
      <div class="notice notice--warn" style="margin-top:14px"><span class="notice__icon">${icon('alert', 14)}</span>
        <div>分类归属<b>不影响收支统计</b>：迁移前后总收入 / 总支出完全一致。</div></div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--danger" data-act="ok">确认停用</button>`,
    acts: {
      cancel: () => closeLayer(),
      ok: async (el) => {
        const mode = el.querySelector('input[name="mig"]:checked')?.value || 'keep';
        try {
          if (mode === 'keep') {
            await api.categories.patch(id, { enabled: false });
            toast('分类已停用，历史记录保留原分类', 'ok');
          } else {
            const v = fieldValue(el, 'target');
            if (!v) return toast('请选择迁移目标分类', 'warn');
            const [l1, l2] = v.split('||');
            const res = await api.categories.disable(id, { migrate_to_l1: l1, migrate_to_l2: l2 });
            toast(`分类已停用，${res.migrated} 笔已迁移到「${l2}」`, 'ok');
          }
          closeLayer();
          invalidateCategories();
          window.__fdRefresh?.();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
    onMount: (el) => {
      const select = el.querySelector('[data-field="target"]');
      el.querySelectorAll('input[name="mig"]').forEach((r) => r.addEventListener('change', () => {
        select.disabled = el.querySelector('input[name="mig"]:checked')?.value !== 'move';
      }));
    },
  });
}

export const actions = {
  'pick-l1': (data, _el, ctx) => { state.catL1 = data.l1; ctx.refresh(); },
  add: async () => addModal(await loadCategories()),
  rename: (data) => renameModal(data.id, data.l2),
  disable: async (data) => disableModal(data.id, data.l2, Number(data.ref || 0), await loadCategories(), data.l1),
  toggle: async (data) => {
    const on = document.querySelector(`[data-act="toggle"][data-id="${CSS.escape(data.id)}"]`)?.getAttribute('aria-checked') === 'true';
    if (on && Number(data.ref) > 0) {
      disableModal(data.id, data.l2, Number(data.ref), await loadCategories(), data.l1 || state.catL1);
      return;
    }
    try {
      await api.categories.patch(data.id, { enabled: !on });
      invalidateCategories();
      toast(!on ? '分类已启用' : '分类已停用', 'ok');
      window.__fdRefresh?.();
    } catch (err) { toast(err.message, 'warn'); }
  },
  refresh: (_d, _el, ctx) => ctx.refresh(),
};
