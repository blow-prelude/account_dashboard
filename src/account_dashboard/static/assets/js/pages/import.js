/* 导入向导：上传 → 映射 → 预检 → 入库 → 报告。
   与契约对齐的关键点：
   - 硬三字段（时间/金额/方向）缺失 → E1007；对方/商品缺失只给警告（D-2）；
   - PUT /mapping 成功即 prechecked，POST /precheck 在其上可重复（D-1）；
   - 模板冲突 409 E2003 后走「覆盖 / 另存 / 取消」，不覆盖用户已有模板；
   - 入库单事务语义由后端保证，前端只处理 409 E2002 与回滚提示。 */

import {api} from '../core/api.js';
import {state} from '../core/store.js';
import {card, pageHead, toast, modal, closeLayer, emptyState, confirmDialog, fieldValue, CHANNEL} from '../core/ui.js';
import {icon} from '../core/icons.js';
import {esc, fmt, money, bytes, shortDateTime} from '../core/format.js';

const STEPS = ['上传文件', '字段映射', '去重预检', '确认入库', '导入报告'];
const FIELDS = [
  ['occurred_at', '交易时间', true],
  ['amount', '金额', true],
  ['direction', '收支方向', true],
  ['counterparty', '交易对方', false],
  ['item', '商品说明', false],
  ['txn_type', '交易类型', false],
  ['payment_method', '支付方式', false],
  ['platform_category', '平台分类', false],
  ['platform_status', '平台状态', false],
];

const wiz = {
  step: 1,
  batch: null,
  preview: null,
  precheck: null,
  report: null,
  saveTemplate: false,
  templateName: '',
  showAllRows: false,
  busy: false,
};

export function onEnter() {
  const id = state.importBatchId;
  if (!id) {
    wiz.step = 1; wiz.batch = null; wiz.preview = null; wiz.precheck = null; wiz.report = null;
  } else if (wiz.batch?.id !== id) {
    wiz.step = Math.max(1, Math.min(4, state.importStep || 1));
    wiz.batch = null; wiz.preview = null; wiz.precheck = null; wiz.report = null;
  }
}

export async function render() {
  const id = state.importBatchId;
  if (id) {
    try {
      const batch = await api.staging.get(id);
      wiz.batch = batch;
      if (batch.status === 'ingested') { wiz.step = 5; wiz.report = batch.report || await api.staging.report(id); }
      else if (batch.status === 'failed' || batch.status === 'uploaded') { wiz.step = 1; }
      else if (batch.status === 'mapped_pending') { wiz.step = 2; }
      else if (batch.status === 'prechecked' && wiz.step < 2) { wiz.step = 3; }

      if (batch.status !== 'failed' && batch.status !== 'discarded') {
        wiz.preview = await api.staging.preview(id, 50).catch(() => null);
      }
      if (wiz.step >= 3 && batch.status === 'prechecked' && !wiz.precheck) {
        wiz.precheck = await api.staging.precheck(id);
      }
    } catch (err) {
      toast(err.message, 'warn');
      state.importBatchId = '';
      wiz.step = 1;
    }
  }

  const stepBar = `<div class="wizard__bar"><div class="steps">
    ${STEPS.map((t, i) => `
      <div class="step ${i + 1 < wiz.step ? 'step--done' : i + 1 === wiz.step ? 'step--current' : ''}">
        <span class="step__dot">${i + 1 < wiz.step ? icon('check', 12) : i + 1}</span>
        <span class="step__label">${t}</span>
      </div>
      ${i < STEPS.length - 1 ? `<span class="step__line ${i + 1 < wiz.step ? 'step__line--done' : ''}"></span>` : ''}`).join('')}
  </div></div>`;

  let panel = '';
  if (wiz.step === 1) panel = stepUpload();
  else if (wiz.step === 2) panel = stepMapping();
  else if (wiz.step === 3) panel = stepPrecheck();
  else if (wiz.step === 4) panel = stepConfirm();
  else panel = stepReport();

  return pageHead('导入账单', '上传 → 映射 → 预检 → 入库 → 报告，全程本地完成',
    `<button class="btn btn--ghost btn--sm" data-go="help">${icon('help', 15)}导入说明</button>
     ${state.importBatchId ? `<button class="btn btn--ghost btn--sm" data-act="new-import">${icon('plus', 13)}换一个文件</button>` : ''}`)
    + `<div class="wizard">${stepBar}<section class="card card--flush">${panel}</section></div>`;
}

/* ---------------- Step 1 ---------------- */
function stepUpload() {
  const b = wiz.batch;
  if (!b) {
    return `<div class="wizard__panel">
      <div class="dropzone" id="dropzone" data-act="pick-file">
        <span class="dropzone__icon">${icon('upload', 22)}</span>
        <span class="dropzone__title">把账单文件拖到这里，或点击选择</span>
        <span class="dropzone__desc">支持 .csv / .xlsx，单文件 ≤ 5MB 且 ≤ 50,000 行 · 文件仅落盘本机</span>
        <div class="row" style="margin-top:6px">
          <span class="badge badge--neutral">微信</span><span class="badge badge--neutral">支付宝</span><span class="badge badge--neutral">银行卡</span>
        </div>
        <input type="file" accept=".csv,.xlsx" data-file>
      </div>
      <div class="row" style="margin-top:14px;gap:10px;flex-wrap:wrap">
        <span class="small muted">渠道</span>
        <div class="select select--sm" style="width:160px"><select class="select__native" data-field="channel">
          <option value="auto">自动识别</option>
          <option value="wechat">微信</option>
          <option value="alipay">支付宝</option>
          <option value="bank">银行卡</option>
          <option value="other">其他</option>
        </select></div>
        <span class="tiny muted">识别失败时可在映射页手动指定；渠道只影响模板套用，不影响解析结果。</span>
      </div>
      <div class="grid" style="grid-template-columns:1fr 1fr;margin-top:16px;gap:12px">
        <div class="notice"><span class="notice__icon">${icon('db', 15)}</span><div><b>自动编码探测</b><br>UTF-8 / GBK / GB18030 自动识别，中文不会乱码。</div></div>
        <div class="notice"><span class="notice__icon">${icon('lock', 15)}</span><div><b>隐私优先</b><br>文件不上传任何外部服务，入库成功后原文件自动删除。</div></div>
      </div>
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 上传阶段不写库，可随时丢弃</div>
      <div class="spacer"></div>
      <button class="btn btn--ghost" data-go="dashboard">取消</button>
      <button class="btn btn--primary" data-act="next" disabled>下一步：字段映射 ${icon('chevronR', 14)}</button>
    </div>`;
  }

  if (b.status === 'failed') {
    return `<div class="wizard__panel">
      <div class="upload-row" style="margin-bottom:16px">
        <span class="file-icon">${icon('file', 18)}</span>
        <div class="file-meta"><b>${esc(b.file_name)}</b><span>${bytes(b.file_size)} · ${esc(CHANNEL[b.channel] || b.channel)} · 批次 ${esc(b.id)}</span></div>
        <span class="badge badge--danger">解析失败</span>
      </div>
      <div class="notice notice--danger" style="margin-bottom:16px">
        <span class="notice__icon">${icon('alert', 15)}</span>
        <div><b>${esc(b.fail_reason || '解析失败')}</b><br>
          文件已保留在缓冲区，不会丢。可以用 Excel 另存为「CSV UTF-8」后重新上传，或直接重试解析。</div>
      </div>
      <div class="kv-grid">
        <div class="kv"><div class="kv__k">批次号</div><div class="kv__v mono" style="font-size:13px">${esc(b.id)}</div></div>
        <div class="kv"><div class="kv__k">文件大小</div><div class="kv__v">${bytes(b.file_size)}</div></div>
        <div class="kv"><div class="kv__k">渠道</div><div class="kv__v" style="font-size:13px">${esc(CHANNEL[b.channel] || b.channel)}</div></div>
        <div class="kv"><div class="kv__k">上传时间</div><div class="kv__v" style="font-size:13px">${shortDateTime(b.created_at)}</div></div>
      </div>
    </div>
    <div class="wizard__foot">
      <div class="wizard__hint">${icon('info', 13)} 重新解析不会重复落盘</div>
      <div class="spacer"></div>
      <button class="btn btn--ghost" data-act="discard">丢弃批次</button>
      <button class="btn btn--outline" data-act="reparse">${icon('refresh', 14)}重新解析</button>
      <button class="btn btn--primary" data-act="pick-file">换一个文件 ${icon('chevronR', 14)}</button>
      <input type="file" accept=".csv,.xlsx" data-file hidden>
    </div>`;
  }

  const pv = wiz.preview;
  const mapped = pv?.suggested_mapping || wiz.batch?.mapped_fields || {};
  const previewRows = (pv?.rows || []).slice(0, 5);
  const previewTable = `<div class="preview-table"><div class="table-wrap"><table class="table table--compact">
      <thead><tr><th>交易时间</th><th>交易对方</th><th>商品说明</th><th>方向</th><th class="right">金额</th></tr></thead>
      <tbody>${previewRows.map((r) => `<tr>
        <td class="num" style="font-size:12px">${esc(cell(r, mapped.occurred_at) || '—')}</td>
        <td class="td-strong">${esc(cell(r, mapped.counterparty) || '—')}</td>
        <td class="td-muted">${esc(cell(r, mapped.item) || '—')}</td>
        <td>${esc(cell(r, mapped.direction) || '—')}</td>
        <td class="td-num">${esc(cell(r, mapped.amount) || '—')}</td>
      </tr>`).join('')}</tbody></table></div></div>`;

  return `<div class="wizard__panel">
    <div class="upload-row" style="margin-bottom:16px">
      <span class="file-icon">${icon('file', 18)}</span>
      <div class="file-meta"><b>${esc(b.file_name)}</b>
        <span>${bytes(b.file_size)} · ${esc(b.encoding || '编码待探测')} · ${fmt(b.total_rows, 0)} 行 · 已落盘至缓冲区</span></div>
      <span class="badge badge--ok">上传完成</span>
      <button class="icon-btn" data-act="discard" aria-label="丢弃批次">${icon('trash', 15)}</button>
    </div>
    <div class="progress" style="margin-bottom:20px"><div class="progress__bar" style="width:100%"></div></div>
    <div class="kv-grid" style="margin-bottom:20px">
      <div class="kv"><div class="kv__k">识别行数</div><div class="kv__v">${fmt(b.total_rows, 0)}<small>行</small></div></div>
      <div class="kv"><div class="kv__k">编码探测</div><div class="kv__v" style="font-family:var(--font-mono);font-size:13px">${esc(b.encoding || '—')}</div></div>
      <div class="kv"><div class="kv__k">表头识别</div><div class="kv__v">${pv ? pv.columns : 0}<small>/ ${pv ? pv.columns : 0} 列</small></div></div>
      <div class="kv"><div class="kv__k">解析问题</div><div class="kv__v" style="color:${issueCount(pv) ? 'var(--warn)' : 'var(--text-1)'}">${issueCount(pv)}<small>条</small></div></div>
    </div>
    <div class="section-label" style="margin-bottom:10px">解析预览 · 前 5 行（共 ${fmt(b.total_rows, 0)} 行）</div>
    ${previewTable}
    <div class="notice notice--info" style="margin-top:16px">
      <span class="notice__icon">${icon('info', 15)}</span>
      <div>文件已在本地缓冲区落盘，<b>尚未写入原始库与主数据层</b>。关闭页面后批次仍保留，可继续处理。</div>
    </div>
  </div>
  <div class="wizard__foot">
    <div class="wizard__hint">${icon('info', 13)} 上传阶段不写库，可随时丢弃</div>
    <div class="spacer"></div>
    <button class="btn btn--ghost" data-go="dashboard">取消</button>
    <button class="btn btn--primary" data-act="next">下一步：字段映射 ${icon('chevronR', 14)}</button>
  </div>`;
}

function cell(row, index) {
  if (index == null || index < 0) return '';
  return row.cells?.[index] ?? '';
}

function issueCount(pv) {
  return (pv?.rows || []).reduce((n, r) => n + (r.issues?.length || 0), 0);
}

/* ---------------- Step 2 ---------------- */
function stepMapping() {
  const b = wiz.batch;
  const pv = wiz.preview;
  if (!b || !pv) {
    return `<div class="wizard__panel">${emptyState({ iconName: 'alert', title: '预览不可用', desc: '批次可能已被清理，请重新上传。', actions: '<button class="btn btn--outline" data-act="new-import">重新上传</button>' })}</div>`;
  }
  const m = pv.suggested_mapping || wiz.batch?.mapped_fields || {};
  const headers = pv.headers || [];
  const sampleOf = (index) => (index >= 0 ? (pv.rows[0]?.cells?.[index] ?? '') : '');
  const colOptions = (selected) => `<option value="-1">不导入此列</option>${headers.map((name, index) =>
    `<option value="${index}" ${selected === index ? 'selected' : ''}>${esc(name)} · 例 ${esc(String(sampleOf(index)).slice(0, 12))}</option>`).join('')}`;

  const dirIndex = m.direction;
  const dirValues = [...new Set((pv.rows || []).map((r) => cell(r, dirIndex)).filter((x) => x !== ''))];
  const dirMap = m.direction_map || {};
  const dirOptions = ['income', 'expense', 'neutral'];

  const previewRows = (pv.rows || []).slice(0, 4).map((r) => `<tr>
    <td class="num" style="font-size:12px">${esc(cell(r, selIndex('occurred_at')) || '—')}</td>
    <td class="td-strong">${esc(cell(r, selIndex('counterparty')) || '—')}</td>
    <td class="td-muted">${esc(cell(r, selIndex('item')) || '—')}</td>
    <td>${esc(cell(r, selIndex('direction')) || '—')}</td>
    <td class="td-num">${esc(cell(r, selIndex('amount')) || '—')}</td>
  </tr>`).join('');

  return `<div class="wizard__panel">
    <div class="row" style="margin-bottom:16px;flex-wrap:wrap;gap:8px">
      <span class="badge badge--ok">${icon('check', 11)}${m.occurred_at != null && m.amount != null && m.direction != null ? '硬三字段已自动命中' : '请补齐时间 / 金额 / 方向'}</span>
      <span class="tiny muted">来源渠道：${esc(CHANNEL[b.channel] || b.channel)} · 文件 ${esc(b.file_name)}</span>
    </div>
    <div class="section-label" style="margin-bottom:6px">字段映射</div>
    <div class="map-row" style="padding-bottom:8px;border-bottom:1px solid var(--border-2)">
      <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">标准字段</span>
      <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">文件列</span>
      <span></span>
      <span class="tiny" style="color:var(--text-3);letter-spacing:.06em">样例值</span>
    </div>
    ${FIELDS.map(([key, label, req]) => `<div class="map-row">
      <span class="map-row__std">${label}${req ? '<span class="req">必填</span>' : ''}</span>
      <div class="select select--sm"><select class="select__native" data-map="${key}">${colOptions(m[key] ?? -1)}</select></div>
      <span class="map-row__arrow">${icon('chevronR', 13)}</span>
      <div class="row" style="gap:8px">
        <span class="small muted num" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(String(sampleOf(m[key]) || '—'))}</span>
        ${req ? `<span class="map-auto">${icon('check', 11)}必填</span>` : `<span class="tiny" style="color:var(--text-4)">选填</span>`}
      </div>
    </div>`).join('')}

    <div class="grid" style="grid-template-columns:1fr 1fr;gap:16px;margin-top:18px">
      <div>
        <div class="section-label" style="margin-bottom:8px">收支方向映射</div>
        ${dirValues.length ? dirValues.map((v) => `<div class="row" style="justify-content:space-between;margin-bottom:8px;gap:10px">
          <span class="rule-kw" style="max-width:120px;overflow:hidden;text-overflow:ellipsis">${esc(v)}</span>
          <div class="select select--sm" style="width:130px"><select class="select__native" data-dirmap="${esc(v)}">
            ${dirOptions.map((k) => `<option value="${k}" ${(dirMap[v] || (v.includes('收入') ? 'income' : v.includes('/') ? 'neutral' : 'expense')) === k ? 'selected' : ''}>${{ income: '收入 income', expense: '支出 expense', neutral: '中性 neutral' }[k]}</option>`).join('')}
          </select></div>
        </div>`).join('') : '<p class="tiny muted">方向列尚未映射。</p>'}
      </div>
      <div>
        <div class="section-label" style="margin-bottom:8px">金额单位</div>
        <div class="select select--sm" style="width:180px"><select class="select__native" data-field="scale">
          <option value="1" ${m.amount_scale !== 100 ? 'selected' : ''}>账单单位是「元」</option>
          <option value="100" ${m.amount_scale === 100 ? 'selected' : ''}>账单单位是「分」</option>
        </select></div>
        <p class="tiny muted" style="margin-top:8px">单位换算只在服务端做，前端不做浮点乘除，避免 0.1+0.2 类误差。</p>
        <div class="row" style="margin-top:14px;justify-content:space-between;gap:10px">
          <label class="row" style="gap:10px">
            <span class="switch" role="switch" aria-checked="${wiz.saveTemplate}" data-act="toggle-template"></span>
            <span class="small">保存为「${esc(CHANNEL[b.channel] || b.channel)}」渠道模板</span>
          </label>
        </div>
        <input class="input" data-field="template-name" placeholder="模板名称（另存时需要）" value="${esc(wiz.templateName)}" style="margin-top:10px;height:32px;font-size:13px">
        <p class="tiny muted" style="margin-top:6px">同渠道已有默认模板时会提示覆盖或另存，不会静默覆盖。</p>
      </div>
    </div>

    <div class="section-label" style="margin:20px 0 10px">按当前映射刷新预览</div>
    <div class="preview-table"><div class="table-wrap"><table class="table table--compact">
      <thead><tr><th>交易时间</th><th>交易对方</th><th>商品说明</th><th>方向</th><th class="right">金额</th></tr></thead>
      <tbody>${previewRows}</tbody></table></div></div>
  </div>
  <div class="wizard__foot">
    <div class="wizard__hint">${icon('info', 13)} 时间 / 金额 / 方向三项必须映射；对方与商品可选，但会影响规则与聚合</div>
    <div class="spacer"></div>
    <button class="btn btn--outline" data-act="prev">上一步</button>
    <button class="btn btn--primary" data-act="save-mapping">确认映射并预检 ${icon('chevronR', 14)}</button>
  </div>`;
}

function selIndex(key) {
  const el = document.querySelector(`[data-map="${key}"]`);
  if (el) return Number(el.value);
  return wiz.preview?.suggested_mapping?.[key] ?? -1;
}

/* ---------------- Step 3 ---------------- */
function stepPrecheck() {
  const b = wiz.batch;
  const pc = wiz.precheck;
  if (!pc) {
    return `<div class="wizard__panel">${emptyState({ iconName: 'alert', title: '预检结果不可用', desc: '批次状态可能已变化，请返回上一步重新确认映射。', actions: '<button class="btn btn--outline" data-act="prev">返回映射</button>' })}</div>`;
  }
  const s = pc.summary;
  const rows = wiz.showAllRows ? pc.rows : pc.rows.slice(0, 12);
  const label = (r) => {
    if (r.label === 'new' && r.override) return '<span class="badge badge--ok">新增 · 强制</span>';
    if (r.label === 'new') return '<span class="badge badge--ok">新增</span>';
    if (r.label === 'dup') return '<span class="badge badge--neutral">重复 · 将跳过</span>';
    return '<span class="badge badge--warn">待确认</span>';
  };
  return `<div class="wizard__panel">
    <div class="kv-grid" style="margin-bottom:16px">
      <div class="kv"><div class="kv__k">总行数</div><div class="kv__v">${s.total}</div></div>
      <div class="kv"><div class="kv__k" style="color:var(--ok)">新增</div><div class="kv__v" style="color:var(--ok)">${s.new}</div></div>
      <div class="kv"><div class="kv__k" style="color:var(--warn)">重复</div><div class="kv__v" style="color:var(--warn)">${s.dup}</div></div>
      <div class="kv"><div class="kv__k">待人工确认</div><div class="kv__v">${s.pending_manual}</div></div>
    </div>
    <div class="notice notice--info" style="margin-bottom:14px">
      <span class="notice__icon">${icon('info', 15)}</span>
      <div>预检为<b>只读</b>操作，不写任何库。若某条被误判为重复，可点「强制新增」并说明原因，入库时按新增处理并留痕。</div>
    </div>
    <div class="preview-table"><div class="table-wrap table-scroll"><table class="table table--compact">
      <thead><tr><th>交易时间</th><th>交易对方</th><th class="right">金额</th><th>判定</th><th class="right">操作</th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="${r.label === 'dup' ? 'is-dup' : ''}">
        <td class="num" style="font-size:12px">${esc(r.occurred_at ? String(r.occurred_at).replace('T', ' ') : '—')}</td>
        <td class="td-strong">${esc(r.counterparty || '—')}<div class="tiny muted">${esc(r.item || '')}</div></td>
        <td class="td-num">${r.amount_cents == null ? '—' : money(r.amount_cents)}</td>
        <td>${label(r)}${(r.issues || []).length ? ` <span class="tiny muted">${esc(r.issues[0].code)}</span>` : ''}</td>
        <td class="right">${r.label === 'dup' || (r.label === 'new' && r.override)
          ? (r.override
            ? `<button class="btn btn--ghost btn--sm" data-act="undo-override" data-row="${r.row_no}">撤销</button>`
            : `<button class="btn btn--outline btn--sm" data-act="force-new" data-row="${r.row_no}">强制新增</button>`)
          : (r.label === 'pending_manual' ? '<span class="tiny muted">入库后处理</span>' : '<span class="tiny muted">—</span>')}</td>
      </tr>`).join('')}</tbody>
    </table></div></div>
    <p class="tiny muted" style="margin-top:10px">当前展示 ${rows.length} / ${pc.rows.length} 行 ·
      ${pc.rows.length > 12 ? `<button class="link-btn" data-act="show-all">${wiz.showAllRows ? '收起' : '查看全部'}</button>` : ''}
      · 预检汇总为快照，最终以入库报告为准</p>
  </div>
  <div class="wizard__foot">
    <div class="wizard__hint">${icon('info', 13)} ${s.dup} 条重复将被跳过；全量重复时批次仍记为「已入库（新增 0 条）」</div>
    <div class="spacer"></div>
    <button class="btn btn--outline" data-act="prev">上一步</button>
    <button class="btn btn--primary" data-act="to-confirm">下一步：确认入库 ${icon('chevronR', 14)}</button>
  </div>`;
}

/* ---------------- Step 4 ---------------- */
function stepConfirm() {
  const b = wiz.batch;
  const pc = wiz.precheck;
  const s = pc?.summary || { total: 0, new: 0, dup: 0, pending_manual: 0 };
  const accepted = (pc?.rows || []).filter((r) => r.label === 'new' && r.occurred_at);
  const monthly = {};
  accepted.forEach((r) => {
    const k = `raw_${String(r.occurred_at).slice(0, 7).replace('-', '_')}`;
    monthly[k] = (monthly[k] || 0) + 1;
  });
  return `<div class="wizard__panel">
    <div class="grid" style="grid-template-columns:1.2fr 1fr;gap:24px">
      <div>
        <div class="section-label" style="margin-bottom:12px">即将写入</div>
        ${Object.entries(monthly).length ? Object.entries(monthly).map(([t, n]) => `<div class="batch-trace" style="margin-bottom:10px">
          ${icon('db', 14)}<b>${t}</b><span class="muted">${n} 条 · 归档原貌 + 批次号 + 行号</span></div>`).join('')
          : '<div class="batch-trace" style="margin-bottom:10px">' + icon('db', 14) + '<b>无新增行</b><span class="muted">本次将不写入 raw</span></div>'}
        <div class="batch-trace" style="margin-bottom:16px">${icon('list', 14)}<b>transaction</b><span class="muted">${s.new} 条主数据 · 已清洗分类</span></div>
        <div class="notice notice--warn">
          <span class="notice__icon">${icon('alert', 15)}</span>
          <div><b>事务原子性</b>：raw 与主数据层在同一事务内写入，任一步失败整体回滚，批次回到「待确认」，原文件保留可重试。</div>
        </div>
      </div>
      <div>
        <div class="section-label" style="margin-bottom:12px">入库摘要</div>
        <div class="kv-grid" style="grid-template-columns:1fr">
          <div class="kv"><div class="kv__k">批次号</div><div class="kv__v" style="font-size:13px;font-family:var(--font-mono)">${esc(b.id)}</div></div>
          <div class="kv"><div class="kv__k">新增 / 跳过 / 待确认</div><div class="kv__v" style="font-size:15px">${s.new} / ${s.dup} / ${s.pending_manual}</div></div>
          <div class="kv"><div class="kv__k">入库后动作</div><div class="kv__v" style="font-size:13px">删除缓冲区原文件</div></div>
          <div class="kv"><div class="kv__k">幂等保护</div><div class="kv__v" style="font-size:13px">仅「待确认」批次可提交</div></div>
        </div>
        <div class="notice notice--info" style="margin-top:14px">
          <span class="notice__icon">${icon('shield', 15)}</span>
          <div>删除意图先落库，即使提交后瞬间断电，重启时启动对账也会补删残留文件。</div>
        </div>
      </div>
    </div>
  </div>
  <div class="wizard__foot">
    <div class="wizard__hint">${icon('lock', 13)} 入库为事务操作，不允许部分成功</div>
    <div class="spacer"></div>
    <button class="btn btn--outline" data-act="prev">上一步</button>
    <button class="btn btn--primary" data-act="confirm-ingest">确认入库并删除原文件</button>
  </div>`;
}

/* ---------------- Step 5 ---------------- */
function stepReport() {
  const b = wiz.batch;
  const r = wiz.report || b?.report;
  if (!r) {
    return `<div class="wizard__panel">${emptyState({ iconName: 'alert', title: '报告不可用', desc: '可以到缓冲区查看批次状态。', actions: '<button class="btn btn--outline" data-go="buffer">去缓冲区</button>' })}</div>`;
  }
  const monthly = Object.entries(r.monthly || {});
  return `<div class="wizard__panel">
    <div class="report-hero" style="margin-bottom:18px">
      <span class="report-hero__icon">${icon('check', 24)}</span>
      <div style="flex:1">
        <div style="font-size:var(--t-lg);font-weight:var(--w-semi)">${r.inserted > 0 ? '入库完成，原始文件已删除' : '未发现新流水，批次已归档'}</div>
        <div class="small muted" style="margin-top:3px">批次 ${esc(r.batch_id)} · ${shortDateTime(r.finished_at)} · ${r.files_deleted ? '缓冲区已无残留' : '原文件待清理'}</div>
      </div>
      <span class="badge badge--ok">${icon('check', 11)}事务已提交</span>
    </div>
    <div class="report-grid" style="margin-bottom:16px">
      <div><div class="kv__k">总行数</div><div class="kv__v">${r.total}</div></div>
      <div><div class="kv__k" style="color:var(--ok)">新增入库</div><div class="kv__v" style="color:var(--ok)">${r.inserted}</div></div>
      <div><div class="kv__k" style="color:var(--warn)">跳过重复</div><div class="kv__v" style="color:var(--warn)">${r.skipped_dup}</div></div>
      <div><div class="kv__k">待确认</div><div class="kv__v">${r.pending}</div></div>
    </div>
    ${monthly.length ? `<div class="section-label" style="margin-bottom:10px">按月归档结果</div>
      <div class="table-wrap" style="border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden">
        <table class="table table--compact">
          <thead><tr><th>归档表</th><th class="right">记录数</th><th>批次</th><th>状态</th></tr></thead>
          <tbody>${monthly.map(([t, n]) => `<tr><td class="mono td-strong">${esc(t)}</td><td class="td-num">${n}</td>
            <td class="td-muted mono">${esc(r.batch_id)}</td><td><span class="badge badge--ok">已写入</span></td></tr>`).join('')}</tbody>
        </table></div>` : ''}
    ${r.skipped_invalid ? `<div class="notice notice--warn" style="margin-top:14px">
      <span class="notice__icon">${icon('alert', 14)}</span>
      <div>有 ${r.skipped_invalid} 行因时间/金额无法解析而未入库，已在预检中标记为待人工确认。</div></div>` : ''}
    <div class="notice notice--ok" style="margin-top:14px">
      <span class="notice__icon">${icon('shield', 15)}</span>
      <div>${r.files_deleted ? '缓冲区原文件已物理删除，删除日志已记录。' : '原文件删除失败，已加入待清理列表，数据不受影响。'}
        ${r.pending > 0 ? `本次入库 ${r.pending} 条待确认流水已进入待确认队列。` : ''}</div>
    </div>
  </div>
  <div class="wizard__foot">
    <div class="wizard__hint">${icon('info', 13)} 报告以入库时实际执行结果为准</div>
    <div class="spacer"></div>
    <button class="btn btn--ghost" data-act="new-import">再导入一份</button>
    <button class="btn btn--outline" data-go="pending">去处理待确认</button>
    <button class="btn btn--primary" data-go="dashboard">回到仪表盘 ${icon('chevronR', 14)}</button>
  </div>`;
}

/* ---------------- 读取表单 ---------------- */
function readMapping() {
  const read = (key) => {
    const el = document.querySelector(`[data-map="${key}"]`);
    return el ? Number(el.value) : -1;
  };
  const direction_map = {};
  document.querySelectorAll('[data-dirmap]').forEach((el) => { direction_map[el.dataset.dirmap] = el.value; });
  const scaleEl = document.querySelector('[data-field="scale"]');
  return {
    occurred_at: read('occurred_at'),
    amount: read('amount'),
    direction: read('direction'),
    counterparty: read('counterparty') === -1 ? null : read('counterparty'),
    item: read('item') === -1 ? null : read('item'),
    txn_type: read('txn_type') === -1 ? null : read('txn_type'),
    payment_method: read('payment_method') === -1 ? null : read('payment_method'),
    platform_category: read('platform_category') === -1 ? null : read('platform_category'),
    platform_status: read('platform_status') === -1 ? null : read('platform_status'),
    direction_map,
    amount_scale: Number(scaleEl?.value || 1),
    save_template: wiz.saveTemplate,
  };
}

async function uploadFile(file) {
  if (!file) return;
  if (wiz.busy) return;
  wiz.busy = true;
  let channel = document.querySelector('[data-field="channel"]')?.value || 'auto';
  if (channel === 'auto') {
    channel = /支付宝|alipay/i.test(file.name) ? 'alipay'
      : /微信|wechat|零钱/i.test(file.name) ? 'wechat'
        : /银行|bank|招商|工商|建设/i.test(file.name) ? 'bank' : 'auto';
  }
  toast(`正在写入本地缓冲区：${file.name}`, '');
  try {
    const batch = await api.staging.create(file, channel);
    state.importBatchId = batch.id;
    state.importStep = 2;
    wiz.batch = batch;
    wiz.step = 2;
    wiz.precheck = null;
    wiz.report = null;
    toast('文件已落盘缓冲区，尚未入库', 'ok');
    window.__fdRefresh?.();
  } catch (err) {
    // 解析失败时后端已建批次并保留文件（detail.batch_id），必须进入失败态而不是丢掉上下文
    const batchId = err?.detail?.batch_id;
    if (batchId) {
      state.importBatchId = batchId;
      state.importStep = 1;
      wiz.batch = null;
      wiz.step = 1;
      toast(`${err.message}（文件已保留在缓冲区，可重试解析）`, 'warn');
      window.__fdRefresh?.();
    } else {
      toast(err.message, 'warn');
    }
  } finally {
    wiz.busy = false;
  }
}

async function saveMappingFlow(ctx) {
  const body = readMapping();
  wiz.templateName = document.querySelector('[data-field="template-name"]')?.value || '';
  if (body.occurred_at < 0 || body.amount < 0 || body.direction < 0) {
    toast('请先映射交易时间、金额、收支方向三列', 'warn');
    return;
  }
  const spec = templateSpec(body);
  try {
    const res = await api.staging.saveMapping(wiz.batch.id, { ...body, save_template: false });
    if (res.batch) wiz.batch = res.batch;
    (res.warnings || []).forEach((w) => toast(w, 'warn'));

    if (!wiz.saveTemplate) {
      await enterPrecheck(ctx);
      return;
    }

    const templates = await api.staging.templates(wiz.batch.channel);
    const existing = (templates || []).find((t) => t.is_default);
    if (!existing) {
      await api.staging.saveTemplate({
        channel: wiz.batch.channel,
        name: wiz.templateName || defaultTemplateName(),
        spec,
        policy: 'abort',
      });
      toast('已保存为该渠道的默认模板', 'ok');
      wiz.saveTemplate = false;
      await enterPrecheck(ctx);
      return;
    }
    openTemplateConflict(existing, spec, ctx);
  } catch (err) {
    toast(err.message, 'warn');
  }
}

function templateSpec(body) {
  return {
    occurred_at: body.occurred_at,
    amount: body.amount,
    direction: body.direction,
    counterparty: body.counterparty,
    item: body.item,
    txn_type: body.txn_type,
    payment_method: body.payment_method,
    platform_category: body.platform_category,
    platform_status: body.platform_status,
    direction_map: body.direction_map,
    amount_scale: body.amount_scale,
  };
}

function defaultTemplateName() {
  return { wechat: '微信支付', alipay: '支付宝', bank: '银行卡', other: '通用模板' }[wiz.batch.channel] || '通用模板';
}

function openTemplateConflict(existing, spec, ctx) {
  modal({
    title: '该渠道已有默认模板',
    sub: `当前默认模板「${esc(existing.name)}」，本次映射要怎么保存？`,
    size: 'modal--sm',
    body: `<div class="stack" style="gap:10px">
      <label class="radio" style="display:flex;gap:10px;align-items:flex-start"><input type="radio" name="tpl" value="overwrite" checked><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">覆盖默认模板</b><br><span class="tiny muted">下次同渠道上传会自动套用本次映射</span></span></label>
      <label class="radio" style="display:flex;gap:10px;align-items:flex-start"><input type="radio" name="tpl" value="save_as"><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">另存为新模板</b><br><span class="tiny muted">保留原有默认模板，本次另存一份</span></span></label>
      <div class="field" style="margin-top:6px"><label class="field__label">新模板名称</label>
        <input class="input" data-field="new-name" placeholder="例如：微信支付 · 2026 新版" value="${esc(wiz.templateName || '')}"></div>
      <p class="tiny muted">取消则只保存本次映射，不写入模板。</p>
    </div>`,
    foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
      <button class="btn btn--primary" data-act="ok">继续</button>`,
    acts: {
      cancel: async () => {
        closeLayer();
        wiz.saveTemplate = false;
        await enterPrecheck(ctx);
      },
      ok: async (el) => {
        const policy = el.querySelector('input[name="tpl"]:checked')?.value || 'overwrite';
        const name = policy === 'save_as'
          ? (fieldValue(el, 'new-name') || `${existing.name} · 新版`)
          : existing.name;
        closeLayer();
        try {
          await api.staging.saveTemplate({ channel: wiz.batch.channel, name, spec, policy });
          wiz.saveTemplate = false;
          toast(policy === 'overwrite' ? '已覆盖渠道默认模板' : '已另存为新模板', 'ok');
          await enterPrecheck(ctx);
        } catch (e) { toast(e.message, 'warn'); }
      },
    },
  });
}

async function enterPrecheck(ctx) {
  wiz.step = 3;
  state.importStep = 3;
  wiz.precheck = await api.staging.precheck(wiz.batch.id);
  ctx.refresh();
}

export const actions = {
  'pick-file': () => {
    const input = document.querySelector('[data-file]');
    if (input) input.click();
  },
  next: (_d, _el, ctx) => {
    if (wiz.batch && wiz.batch.status !== 'failed') {
      wiz.step = 2;
      state.importStep = 2;
      ctx.refresh();
    }
  },
  prev: (_d, _el, ctx) => {
    wiz.step = Math.max(1, wiz.step - 1);
    state.importStep = wiz.step;
    ctx.refresh();
  },
  'save-mapping': (_d, _el, ctx) => saveMappingFlow(ctx),
  'to-confirm': (_d, _el, ctx) => { wiz.step = 4; state.importStep = 4; ctx.refresh(); },
  'force-new': (data) => {
    modal({
      title: '强制新增这条记录？',
      sub: '判定为重复，但你确认它是真实消费',
      size: 'modal--sm',
      body: `<div class="notice notice--warn" style="margin-bottom:16px">
          <span class="notice__icon">${icon('alert', 14)}</span>
          <div>该行与库内记录指纹一致（时间 + 金额 + 方向 + 对方 + 说明）。强制新增会留痕，可在明细中追溯。</div>
        </div>
        <div class="field"><label class="field__label">原因 <span class="req">*</span></label>
          <textarea class="textarea" data-field="reason" placeholder="例如：当天确实有两笔相同的转入，重复属实"></textarea>
          <span class="field__hint">原因与操作时间会写入 override 记录，可在明细与入库报告中追溯。</span></div>`,
      foot: `<button class="btn btn--ghost" data-act="cancel">取消</button>
        <button class="btn btn--primary" data-act="ok">确认强制新增</button>`,
      acts: {
        cancel: () => closeLayer(),
        ok: async (el) => {
          const reason = fieldValue(el, 'reason');
          if (!reason?.trim()) return toast('请填写强制新增的原因', 'warn');
          try {
            await api.staging.addOverride(wiz.batch.id, { row_no: Number(data.row), reason });
            closeLayer();
            wiz.precheck = await api.staging.precheck(wiz.batch.id);
            toast('已标记「强制新增」，入库时按新增处理并留痕', 'ok');
            window.__fdRefresh?.();
          } catch (err) { toast(err.message, 'warn'); }
        },
      },
    });
  },
  'undo-override': async (data) => {
    try {
      await api.staging.removeOverride(wiz.batch.id, Number(data.row));
      wiz.precheck = await api.staging.precheck(wiz.batch.id);
      toast('已撤销强制新增标记', 'ok');
      window.__fdRefresh?.();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'show-all': (_d, _el, ctx) => { wiz.showAllRows = !wiz.showAllRows; ctx.refresh(); },
  'toggle-template': (_d, el) => {
    const sw = el.classList?.contains('switch') ? el : el.querySelector('.switch');
    if (!sw) return;
    const next = sw.getAttribute('aria-checked') !== 'true';
    sw.setAttribute('aria-checked', String(next));
    wiz.saveTemplate = next;
  },
  'confirm-ingest': async (_d, el, ctx) => {
    if (wiz.busy) return;
    wiz.busy = true;
    el.disabled = true;
    el.classList.add('btn--loading');
    try {
      const report = await api.staging.confirm(wiz.batch.id);
      wiz.report = report;
      wiz.step = 5;
      state.importStep = 5;
      toast('入库完成，原始文件已删除', 'ok');
      ctx.refresh();
    } catch (err) {
      if (err.is('E2002')) toast(err.message, 'warn');
      else toast(`${err.message}（已回滚，可重试）`, 'warn');
      wiz.batch = await api.staging.get(wiz.batch.id).catch(() => wiz.batch);
      ctx.refresh();
    } finally {
      wiz.busy = false;
      el.disabled = false;
      el.classList.remove('btn--loading');
    }
  },
  reparse: async () => {
    try {
      const res = await api.staging.parse(wiz.batch.id);
      wiz.batch = { ...wiz.batch, ...res.batch };
      wiz.preview = await api.staging.preview(wiz.batch.id, 50);
      toast('重新解析完成', 'ok');
      window.__fdRefresh?.();
    } catch (err) { toast(err.message, 'warn'); }
  },
  discard: async () => {
    const ok = await confirmDialog({
      title: '丢弃这个批次？',
      sub: '会删除缓冲区文件，已入库的主数据不受影响',
      body: '<p class="small muted">丢弃后该批次状态变为「已丢弃」，不能继续处理。若只是暂时不想处理，可以留着批次稍后再来。</p>',
      confirmText: '丢弃批次',
      danger: true,
    });
    if (!ok) return;
    try {
      await api.staging.discard(wiz.batch.id);
      state.importBatchId = '';
      wiz.step = 1; wiz.batch = null; wiz.preview = null; wiz.precheck = null; wiz.report = null;
      toast('批次已丢弃，缓冲区文件已删除', 'ok');
      window.__fdRefresh?.();
    } catch (err) { toast(err.message, 'warn'); }
  },
  'new-import': (_d, _el, ctx) => {
    state.importBatchId = '';
    state.importStep = 1;
    wiz.step = 1; wiz.batch = null; wiz.preview = null; wiz.precheck = null; wiz.report = null;
    ctx.refresh();
  },
};

export async function afterRender() {
  const dz = document.getElementById('dropzone');
  if (dz) {
    ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('is-over'); }));
    dz.addEventListener('drop', (e) => {
      const file = e.dataTransfer?.files?.[0];
      if (file) uploadFile(file);
    });
  }
  const input = document.querySelector('[data-file]');
  if (input) input.addEventListener('change', (e) => uploadFile(e.target.files?.[0]));
}

/* 映射改动后把值写回预览状态并重绘：预览与提交使用同一份 mapping */
document.addEventListener('change', (e) => {
  if (window.__fdRoute !== 'import') return;
  const el = e.target;
  if (el.dataset.map) {
    const key = el.dataset.map;
    const v = Number(el.value);
    if (!wiz.preview) return;
    wiz.preview.suggested_mapping[key] = v < 0 ? null : v;
    window.__fdRefresh?.();
  }
  if (el.dataset.dirmap) {
    if (!wiz.preview) return;
    wiz.preview.suggested_mapping.direction_map = { ...(wiz.preview.suggested_mapping.direction_map || {}), [el.dataset.dirmap]: el.value };
    window.__fdRefresh?.();
  }
  if (el.dataset.field === 'scale') {
    if (!wiz.preview) return;
    wiz.preview.suggested_mapping.amount_scale = Number(el.value);
    window.__fdRefresh?.();
  }
});
