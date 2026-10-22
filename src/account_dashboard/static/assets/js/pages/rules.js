/* 分类规则：关键词 + 匹配字段 + 目标分类 + 优先级；可启停、可重算。 */

import { api } from '../core/api.js';
import { loadCategories, invalidateCategories } from '../core/store.js';
import {
  card, pageHead, toast, modal, closeLayer, confirmDialog, categoryOptions,
  fieldValue, MATCH_FIELD,
} from '../core/ui.js';
import { icon } from '../core/icons.js';
import { esc, fmt } from '../core/format.js';

export async function render() {
  const [rules, nodes] = await Promise.all([api.rules.list(), loadCategories().catch(() => [])]);
  const enabledCount = rules.filter((r) => r.enabled).length;
  const rows = rules.map((r) => `<tr>
      <td><span class="rule-kw">${esc(r.keyword)}</span></td>
      <td class="td-muted">${MATCH_FIELD[r.match_field] || esc(r.match_field)}</td>
      <td class="td-strong">${esc(r.category_l1)} · ${esc(r.category_l2)}</td>
      <td class="td-num">${r.priority}</td>
      <td class="td-num td-muted">${fmt(r.hit_count || 0, 0)}</td>
      <td><span class="switch" role="switch" aria-checked="${r.enabled}" data-act="toggle" data-id="${esc(r.id)}" aria-label="启用规则"></span></td>
      <td class="right">
        <button class="icon-btn" data-act="edit" data-id="${esc(r.id)}" aria-label="编辑" ${r.is_builtin ? 'disabled title="内置规则不可修改，可停用后新增自定义规则"' : ''}>${icon('edit', 15)}</button>
        <button class="icon-btn" data-act="remove" data-id="${esc(r.id)}" aria-label="删除" ${r.is_builtin ? 'disabled title="内置规则不可删除"' : ''}>${icon('trash', 15)}</button>
      </td>
    </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: '自动分类规则',
    sub: `共 ${rules.length} 条 · 已启用 ${enabledCount} 条 · 命中多条取优先级高者`,
    actions: `<button class="btn btn--primary btn--sm" data-act="add">${icon('plus', 13)}新增规则</button>`,
    raw: `<div class="table-wrap"><table class="table">
      <thead><tr><th>关键词</th><th>匹配字段</th><th>目标分类</th><th class="right">优先级</th><th class="right">命中</th><th>启用</th><th class="right">操作</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`,
    foot: `<span>${icon('info', 12)} 停用后新导入不再套用，历史流水不受影响</span>
      <button class="link-btn" data-act="recalc">按规则范围重算历史流水 →</button>`,
  });

  const hint = `<div class="grid" style="grid-template-columns:1fr 1fr;gap:16px">
    <div class="notice notice--info"><span class="notice__icon">${icon('info', 15)}</span>
      <div><b>优先级怎么排</b><br>数值越大越优先；同级取最新创建的规则。建议「资金流转」类规则优先级最高，避免被消费类关键词误命中。</div></div>
    <div class="notice"><span class="notice__icon">${icon('sparkles', 15)}</span>
      <div><b>规则影响哪些数据</b><br>只影响后续导入与重算；人工修正过的记录（corrected）默认保持不变，可在重算时显式选择覆盖。</div></div>
  </div>`;

  return pageHead('分类规则', '让下一次导入少一点手工 · 规则可启停、可重算',
    `<button class="btn btn--outline" data-act="recalc">${icon('refresh', 15)}重算历史</button>`)
    + table + `<div style="margin-top:16px">${hint}</div>`;
}

async function ruleModal(rule) {
  const nodes = await loadCategories();
  const isEdit = !!rule;
  modal({
    title: isEdit ? '修改分类规则' : '新增分类规则',
    sub: '命中关键词的流水将自动归入目标分类',
    body: `<div class="form-grid">
        <div class="field"><label class="field__label">关键词 <span class="req">*</span></label>
          <input class="input" data-field="keyword" value="${esc(rule?.keyword || '')}" placeholder="多个用 | 分隔，如 美团|饿了么">
          <span class="field__hint">不区分大小写；子串匹配。</span></div>
        <div class="field"><label class="field__label">匹配字段</label>
          <div class="select"><select class="select__native" data-field="field">
            ${Object.entries(MATCH_FIELD).map(([k, v]) => `<option value="${k}" ${rule?.match_field === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select></div></div>
        <div class="field"><label class="field__label">目标分类 <span class="req">*</span></label>
          <div class="select"><select class="select__native" data-field="cat">
            ${categoryOptions(nodes, { selected: rule ? `${rule.category_l1}||${rule.category_l2}` : '' })}
          </select></div></div>
        <div class="field"><label class="field__label">优先级 <span class="req">*</span></label>
          <input class="input input--num" data-field="priority" type="number" step="1" value="${rule?.priority ?? 100}">
          <span class="field__hint">数值越大越优先，同级取最新</span></div>
      </div>
      <div class="notice notice--info" style="margin-top:16px"><span class="notice__icon">${icon('info', 14)}</span>
        <div>保存后仅影响<b>后续导入</b>；历史流水需要点「重算」才会应用。</div></div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--primary" data-act="ok">${isEdit ? '保存修改' : '保存规则'}</button>`,
    acts: {
      cancel: () => closeLayer(),
      ok: async (el) => {
        const keyword = fieldValue(el, 'keyword')?.trim();
        const field = fieldValue(el, 'field');
        const cat = fieldValue(el, 'cat');
        const priority = Number(fieldValue(el, 'priority'));
        if (!keyword) return toast('关键词不能为空', 'warn');
        if (!Number.isInteger(priority)) return toast('优先级必须是整数', 'warn');
        if (!cat) return toast('请选择目标分类', 'warn');
        const [l1, l2] = cat.split('||');
        try {
          if (isEdit) await api.rules.patch(rule.id, { keyword, match_field: field, l1, l2, priority });
          else await api.rules.create({ keyword, match_field: field, l1, l2, priority });
          closeLayer();
          invalidateCategories();
          toast(isEdit ? '规则已保存' : '规则已保存，后续导入将自动套用', 'ok');
          window.__fdRefresh?.();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
  });
}

async function recalcByRules(ruleIds) {
  try {
    const preview = await api.recalc.preview({ scope: 'rules', rule_ids: ruleIds });
    modal({
      title: '按规则范围重算',
      sub: '只重算这些规则可能覆盖的流水，不影响 raw 原始库',
      body: `<div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
          <div class="kv"><div class="kv__k">将重算</div><div class="kv__v">${preview.to_recalc}<small>条</small></div></div>
          <div class="kv"><div class="kv__k">人工修正 / 排除</div><div class="kv__v" style="color:var(--primary-ink)">${preview.manual_kept}<small>条</small></div></div>
        </div>
        <div class="notice notice--info" style="margin-bottom:16px"><span class="notice__icon">${icon('info', 14)}</span>
          <div>默认不覆盖人工修正与已排除记录；重算为事务操作，失败整体回滚。</div></div>
        <label class="checkbox"><input type="checkbox" data-field="overwrite"><span class="checkbox__box"></span>同时覆盖人工修正结果（不推荐）</label>`,
      foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
        <button class="btn btn--primary" data-act="ok">开始重算</button>`,
      acts: {
        cancel: () => closeLayer(),
        ok: async (el) => {
          const overwrite = el.querySelector('[data-field="overwrite"]').checked;
          try {
            const res = await api.recalc.run({ scope: 'rules', rule_ids: ruleIds, overwrite_manual: overwrite, confirm: true });
            closeLayer();
            toast(`重算完成：更新 ${res.updated} 条，人工修正 ${res.manual_kept} 条未重算`, 'ok');
            window.__fdRefresh?.();
          } catch (err) { toast(err.message, 'warn'); }
        },
      },
    });
  } catch (err) { toast(err.message, 'warn'); }
}

export const actions = {
  add: () => ruleModal(null),
  edit: async (data) => {
    const rules = await api.rules.list();
    const r = rules.find((x) => x.id === data.id);
    if (!r) return toast('规则不存在', 'warn');
    ruleModal(r);
  },
  remove: async (data, _el, ctx) => {
    const ok = await confirmDialog({
      title: '删除这条规则？',
      sub: '删除后新导入不再套用，历史流水的分类保持不变',
      body: '<p class="small muted">内置规则不能删除；如果只是想暂停使用，关闭行内开关即可。</p>',
      confirmText: '删除规则',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.rules.remove(data.id);
      toast('规则已删除', 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  toggle: async (data, el, ctx) => {
    const on = el.getAttribute('aria-checked') === 'true';
    try {
      const r = await api.rules.toggle(data.id, !on);
      el.setAttribute('aria-checked', String(r.enabled));
      toast(r.enabled ? `已启用「${r.keyword}」` : `已停用「${r.keyword}」，新导入不再套用`, r.enabled ? 'ok' : '');
    } catch (err) { toast(err.message, 'warn'); }
  },
  recalc: async () => {
    const rules = await api.rules.list(true);
    const ids = rules.filter((r) => r.enabled).map((r) => r.id);
    if (!ids.length) return toast('没有启用的规则，无法按规则重算', 'warn');
    recalcByRules(ids);
  },
};
