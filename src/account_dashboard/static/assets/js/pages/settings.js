/* 基础设置：阈值 / 提醒 / 周起始 / 日志 / 数据目录。
   类型与范围校验由后端负责（E2008），前端只做即时提示，不替代服务端校验。 */

import {api} from '../core/api.js';
import {state} from '../core/store.js';
import {card, pageHead, toast, modal, closeLayer, confirmDialog, fieldValue} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, shortDateTime} from '../core/format.js';

let dirCheck = null;

export async function render() {
  const s = await api.settings.get();
  const row = (title, desc, ctl) => `<div class="setting-row">
    <div><div class="setting-row__title">${title}</div><div class="setting-row__desc">${desc}</div></div>
    <div class="setting-row__ctl">${ctl}</div>
  </div>`;

  const form = card({
    title: '记账与提醒',
    sub: '保存后立即生效，无需重启',
    body:
      row('单日支出阈值', '超过阈值的日期在趋势图上高亮，并写入月度摘要。',
        `<input class="input input--num" data-field="threshold" type="number" min="1" step="1" value="${fmt(s.single_day_threshold_cents / 100, 0)}" style="text-align:right;width:108px"><span class="small muted">元</span>`) +
      row('备份提醒间隔', '距上次备份超过该天数时，仪表盘与报表页顶部提醒。',
        `<input class="input input--num" data-field="interval" type="number" min="1" step="1" value="${s.backup_interval_days}" style="text-align:right;width:108px"><span class="small muted">天</span>`) +
      row('每周起始日', '仅影响季度报表的按周聚合边界。',
        `<div class="select"><select class="select__native" data-field="weekstart">
          <option value="1" ${s.week_start === 1 ? 'selected' : ''}>周一</option>
          <option value="0" ${s.week_start === 0 ? 'selected' : ''}>周日</option>
        </select></div>`) +
      row('缓冲区阈值', '超过该占用时在缓冲区页提醒清理，不会自动删除文件。',
        `<input class="input input--num" data-field="buffer" type="number" min="1" step="10" value="${Math.round(s.buffer_threshold_bytes / 1024 / 1024)}" style="text-align:right;width:108px"><span class="small muted">MB</span>`) +
      row('本地事件日志', '记录导入成功率、待确认率、删除与补删次数。仅存本机，不上传。',
        `<span class="switch" role="switch" aria-checked="${s.event_log_enabled}" data-act="toggle-log"></span>`) +
      row('界面主题', '两套主题共用同一套语义变量，切换不会改变任何布局与数据。',
        `<div class="theme-switch">
          <button class="theme-switch__item" data-theme-set="pink" aria-pressed="${state.theme === 'pink'}"><i></i>玫瑰粉</button>
          <button class="theme-switch__item" data-theme-set="sky" aria-pressed="${state.theme === 'sky'}"><i></i>天青蓝</button>
        </div>`),
  });

  const dir = `<section class="card">
    <div class="card__head"><div><div class="card__title">数据目录</div><div class="card__sub">数据库 + 缓冲区 + 备份的统一根目录</div></div></div>
    <div class="card__body">
      <div class="field ${dirCheck && !dirCheck.valid ? 'is-invalid' : ''}" id="dir-field">
        <label class="field__label">当前路径</label>
        <input class="input mono" data-field="dir" value="${esc(s.data_dir)}" style="font-size:12px">
        ${dirCheck && !dirCheck.valid ? `<span class="field__error">${icon('alert', 11)} ${esc(dirCheck.reason || '路径不合法')}</span>` : ''}
        ${dirCheck && dirCheck.valid ? `<span class="field__hint" style="color:var(--ok)">${icon('check', 11)} 路径可写：${esc(dirCheck.resolved)}</span>` : ''}
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn btn--outline btn--sm" data-act="validate-dir">${icon('check', 13)}校验路径</button>
        <button class="btn btn--ghost btn--sm" data-act="migrate">${icon('folder', 13)}迁移向导</button>
      </div>
      <div class="notice notice--warn" style="margin-top:14px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div>更换目录会搬移数据库与缓冲区文件，执行前请先备份，搬移期间不要操作。</div>
      </div>
      <p class="tiny muted" style="margin-top:10px">路径合法化校验：必须是本地绝对路径；禁止系统敏感目录（C:\\Windows 等）与网络位置。</p>
    </div>
  </section>`;

  const save = card({
    cls: 'card--quiet',
    body: `<div class="section-label" style="margin-bottom:10px">保存</div>
      <p class="small muted" style="margin-bottom:14px">设置项由服务端做类型与范围校验；不合法会拒绝整批保存并给出原因。</p>
      <button class="btn btn--primary btn--block" data-act="save">${icon('check', 15)}保存全部设置</button>
      <p class="tiny muted" style="margin-top:10px;text-align:center">上次保存 ${shortDateTime(s.updated_at)}</p>`,
  });

  const logCard = card({
    cls: 'card--quiet',
    title: '本机事件日志',
    sub: s.event_log_enabled ? '已开启 · 仅记录导入与删除事件' : '未开启',
    body: `<p class="small muted">开启后可在缓冲区和导入报告里核对「失败—重试—补删」的完整链路。日志只存本机，不写任何远程服务。</p>`,
  });

  return pageHead('基础设置', '阈值、提醒、周期与数据目录 · 键值均做类型校验',
    `<button class="btn btn--ghost" data-act="reset">恢复默认</button>`)
    + `<div class="grid g-12"><div class="c-8">${form}</div>
      <div class="c-4 stack">${dir}${save}${logCard}</div></div>`;
}

function collect() {
  const num = (name) => Number(document.querySelector(`[data-field="${name}"]`)?.value);
  return {
    single_day_threshold_cents: Math.round(num('threshold') * 100),
    backup_interval_days: num('interval'),
    week_start: Number(document.querySelector('[data-field="weekstart"]')?.value),
    buffer_threshold_bytes: Math.round(num('buffer') * 1024 * 1024),
    event_log_enabled: document.querySelector('[data-act="toggle-log"]')?.getAttribute('aria-checked') === 'true',
  };
}

export const actions = {
  save: async (_d, _el, ctx) => {
    const body = collect();
    if (!Number.isFinite(body.single_day_threshold_cents) || body.single_day_threshold_cents <= 0) return toast('单日阈值必须是大于 0 的金额', 'warn');
    if (!Number.isInteger(body.backup_interval_days) || body.backup_interval_days < 1) return toast('备份提醒间隔必须 ≥ 1 天', 'warn');
    if (!Number.isFinite(body.buffer_threshold_bytes) || body.buffer_threshold_bytes <= 0) return toast('缓冲区阈值必须大于 0', 'warn');
    try {
      await api.settings.update(body);
      toast('设置已保存', 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'toggle-log': (_d, el) => {
    const sw = el.classList?.contains('switch') ? el : el.querySelector('.switch');
    if (!sw) return;
    sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
  },
  'validate-dir': async (_d, _el, ctx) => {
    const path = document.querySelector('[data-field="dir"]')?.value;
    try {
      dirCheck = await api.settings.validateDir(path);
      toast(dirCheck.valid ? '路径校验通过' : dirCheck.reason, dirCheck.valid ? 'ok' : 'warn');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
  migrate: async () => {
    const current = document.querySelector('[data-field="dir"]')?.value || '';
    modal({
      title: '数据迁移向导',
      sub: '把数据库与缓冲区搬到新目录',
      body: `<div class="stack" style="gap:14px">
          <div class="field"><label class="field__label">当前目录</label>
            <input class="input mono" value="${esc(current)}" readonly style="font-size:12px"></div>
          <div class="field"><label class="field__label">目标目录 <span class="req">*</span></label>
            <input class="input mono" data-field="to" placeholder="例如 E:\\finance-data" style="font-size:12px">
            <span class="field__hint">必须是本机绝对路径；不允许系统敏感目录与网络位置。</span></div>
          <label class="checkbox"><input type="checkbox" data-field="copyonly"><span class="checkbox__box"></span>只复制不切换（保留原目录）</label>
          <div class="notice notice--warn"><span class="notice__icon">${icon('alert', 14)}</span>
            <div>搬移期间请勿操作服务；切换后需要重启，启动对账会按新目录执行。</div></div>
        </div>`,
      foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
        <button class="btn btn--primary" data-act="ok">开始迁移</button>`,
      acts: {
        cancel: () => closeLayer(),
        ok: async (el) => {
          const to = fieldValue(el, 'to')?.trim();
          if (!to) return toast('请输入目标目录', 'warn');
          const copyOnly = el.querySelector('[data-field="copyonly"]').checked;
          try {
            const r = await api.settings.migrate({ to, confirm: true, copy_only: copyOnly });
            closeLayer();
            toast(r.restarted_required ? '迁移完成，请重启服务以应用新目录' : '已复制到新目录，当前配置未切换', 'ok');
            window.__fdRefresh?.();
          } catch (err) { toast(err.message, 'warn'); }
        },
      },
    });
  },
  reset: async (_d, _el, ctx) => {
    const ok = await confirmDialog({
      title: '恢复默认设置？',
      sub: '会把阈值、提醒间隔、周起始与日志开关改回默认值',
      body: '<p class="small muted">数据目录不受影响，账单数据不会被修改。</p>',
      confirmText: '恢复默认',
    });
    if (!ok) return;
    try {
      await api.settings.update({
        single_day_threshold_cents: 20000,
        backup_interval_days: 7,
        week_start: 1,
        event_log_enabled: false,
        buffer_threshold_bytes: 524288000,
      });
      toast('设置已恢复默认值', 'ok');
      ctx.refresh();
    } catch (err) { toast(err.message, 'warn'); }
  },
};
