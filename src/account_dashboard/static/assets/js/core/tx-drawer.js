/* 流水详情抽屉：原始事实字段只读，仅分类与备注可编辑（FR-19 / I7）。
   数据来源 GET /transactions/{id}/trace，确保能看到来源批次与原始行。 */

import {api} from './api.js';
import {loadCategories} from './store.js';
import {drawer, toast, confirmDialog, closeLayer, stBadge, DIR, CHANNEL, $} from './ui.js';
import {icon} from './icons.js';
import {esc, signedMoney, shortDateTime, fullDateTime} from './format.js';

const kv = (k, v) => `<div class="kv"><div class="kv__k">${k}</div><div class="kv__v" style="font-size:13px">${v}</div></div>`;

export async function openTransaction(id, { onChanged } = {}) {
  let trace;
  try {
    trace = await api.trace(id);
  } catch (err) {
    toast(err.message || '流水详情加载失败', 'warn');
    return;
  }
  const t = trace.transaction;
  const nodes = await loadCategories().catch(() => []);
  const selected = t.category_l1 ? `${t.category_l1}||${t.category_l2 || ''}` : '';
  const options = nodes.flatMap((g) => (g.children || []).filter((c) => c.enabled).map((c) =>
    `<option value="${esc(c.l1)}||${esc(c.l2)}" ${`${c.l1}||${c.l2}` === selected ? 'selected' : ''}>${esc(c.l1)} · ${esc(c.l2)}</option>`))
    .join('');

  const body = `
    <div class="row" style="justify-content:space-between;margin-bottom:6px">
      <span class="num" style="font-size:var(--t-3xl);font-weight:500;color:${t.direction === 'income' ? 'var(--fin-down)' : 'var(--text-1)'}">
        ${signedMoney(t)}</span>
      <div class="row" style="gap:6px">${stBadge(t.status)}
        ${t.direction === 'neutral' ? '<span class="badge badge--neutral">中性 · 不计收支</span>' : ''}</div>
    </div>
    <p class="small muted" style="margin-bottom:18px">${esc(t.item || '—')}</p>

    <div class="section-label" style="margin-bottom:10px">原始事实字段 · 只读</div>
    <div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:8px">
      ${kv('交易时间', fullDateTime(t.occurred_at))}
      ${kv('收支方向', DIR[t.direction] || t.direction)}
      ${kv('交易对方', esc(t.counterparty || '—'))}
      ${kv('支付方式', esc(t.payment_method || '—'))}
      ${kv('交易类型', esc(t.txn_type || '—'))}
      ${kv('来源渠道', CHANNEL[t.channel] || esc(t.channel))}
      ${kv('来源批次', `<span class="mono">${esc(t.batch_id)}</span>`)}
      ${kv('原始行号', `第 ${t.row_no} 行`)}
    </div>
    <div class="notice" style="margin-bottom:20px">
      <span class="notice__icon">${icon('lock', 14)}</span>
      <div>这些字段来自原始库，<b>不可编辑</b>。若原始事实有误，请重新导入正确文件并排除错误批次。</div>
    </div>

    ${trace.raw_record ? `<div class="section-label" style="margin-bottom:8px">原始行核对</div>
      <div class="batch-trace" style="margin-bottom:18px;flex-wrap:wrap;gap:6px">
        ${icon('archive', 14)}<span class="mono">raw_${esc(String(t.occurred_at).slice(0, 7).replace('-', '_'))}</span>
        <span>第 ${trace.raw_record.row_no} 行</span>
        <span class="muted">${esc(String(trace.raw_record.raw_payload || '').slice(0, 80))}</span>
      </div>` : ''}

    ${t.override_reason ? `<div class="notice notice--info" style="margin-bottom:16px">
      <span class="notice__icon">${icon('info', 14)}</span>
      <div>该记录曾被标记为「强制新增」：${esc(t.override_reason)}</div></div>` : ''}

    <div class="section-label" style="margin-bottom:10px">可编辑</div>
    <div class="field" style="margin-bottom:14px">
      <label class="field__label">分类</label>
      <div class="select"><select class="select__native" data-field="cat">
        <option value="" ${!selected ? 'selected' : ''}>未分类（待确认）</option>
        ${options}
      </select></div>
      <span class="field__hint">改分类不会改变统计归属：direction=neutral 的记录仍不计入收支。</span>
    </div>
    <div class="field">
      <label class="field__label">备注</label>
      <textarea class="textarea" data-field="note" maxlength="200" placeholder="例如：和室友拼单">${esc(t.note || '')}</textarea>
    </div>
    ${t.status === 'corrected' ? `<div class="notice notice--info" style="margin-top:16px">
      <span class="notice__icon">${icon('info', 14)}</span>
      <div>该记录已被人工修正，后续重算默认不会覆盖它。</div></div>` : ''}`;

  const layer = drawer({
    title: esc(t.counterparty || '流水详情'),
    sub: `${shortDateTime(t.occurred_at)} · 来源 ${esc(t.batch_id)} / 第 ${t.row_no} 行`,
    body,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--outline" data-act="toggle-exclude">${t.status === 'excluded' ? '恢复计入' : '排除出统计'}</button>
      <button class="btn btn--primary" data-act="save">保存修改</button>`,
    acts: {
      cancel: () => closeLayer(),
      save: async (modalEl) => {
        const v = $(`[data-field="cat"]`, modalEl).value;
        const note = $(`[data-field="note"]`, modalEl).value;
        const payload = { note };
        if (v) {
          const [l1, l2] = v.split('||');
          payload.category_l1 = l1;
          payload.category_l2 = l2;
        }
        try {
          await api.patchTransaction(t.id, payload);
          closeLayer();
          toast('已保存分类与备注（人工修正不会被重算覆盖）', 'ok');
          onChanged?.();
        } catch (err) {
          toast(err.message, 'warn');
        }
      },
      'toggle-exclude': async () => {
        if (t.status === 'excluded') {
          try {
            await api.restoreTransaction(t.id);
            closeLayer();
            toast('已恢复计入统计', 'ok');
            onChanged?.();
          } catch (err) { toast(err.message, 'warn'); }
          return;
        }
        const ok = await confirmDialog({
          title: '排除这条流水？',
          sub: '排除后不计入任何收支统计，可随时恢复',
          body: `<div class="field"><label class="field__label">原因（可选）</label>
            <input class="input" data-field="reason" placeholder="例如：公司报销，不属于个人支出"></div>
            <p class="tiny muted" style="margin-top:10px">排除不是删除：原始库与追溯链保持不变，状态筛选为「已排除」时仍可看到。</p>`,
          confirmText: '排除出统计',
        });
        if (!ok) return;
        try {
          await api.excludeTransaction(t.id, '手动排除');
          closeLayer();
          toast('已标记为「已排除」，不再计入任何收支统计', 'ok');
          onChanged?.();
        } catch (err) { toast(err.message, 'warn'); }
      },
    },
  });
  return layer;
}
