/* ============================================================
   09 · 应用：路由 / 主题 / 交互 / 弹层
   ============================================================ */

const state = {
  route: 'dashboard',
  theme: localStorage.getItem('fd-theme') || 'pink',
  period: 'month',
  wStep: 1,
  uploaded: false,
  importing: false,
  txFilter: { status: 'all', dir: 'all', q: '', cat: 'all' },
  txSel: new Set(),
  sort: { key: 'time', dir: 'desc' },
  cat: '餐饮美食',
  catL1: '支出',
  rawMonth: '2026-10',
  pendingDone: new Set(),
  focus: null,
};

const ROUTES = [
  { k: 'dashboard', n: '仪表盘', g: '总览', i: 'dashboard', f: pageDashboard, d: '本期收支全貌' },
  { k: 'reports', n: '报表中心', g: '总览', i: 'reports', f: pageReports, d: '月度 / 季度 / 年度' },
  { k: 'analysis', n: '分类分析', g: '总览', i: 'pie', f: pageAnalysis, d: '分类结构与下钻' },
  { k: 'import', n: '导入账单', g: '数据', i: 'import', f: pageImport, d: '缓冲区五步链路' },
  { k: 'buffer', n: '缓冲区', g: '数据', i: 'buffer', f: pageBuffer, d: '批次与残留管理' },
  { k: 'raw', n: '原始库', g: '数据', i: 'archive', f: pageRaw, d: '按月归档与追溯' },
  { k: 'detail', n: '流水明细', g: '数据', i: 'list', f: pageDetail, d: '查询与分类修正' },
  { k: 'pending', n: '待确认', g: '分类', i: 'pending', f: pagePending, d: '未分类流水' },
  { k: 'rules', n: '分类规则', g: '分类', i: 'rules', f: pageRules, d: '自动归类规则' },
  { k: 'categories', n: '分类体系', g: '分类', i: 'tag', f: pageCategories, d: '一级 / 二级分类' },
  { k: 'backup', n: '备份与恢复', g: '系统', i: 'shield', f: pageBackup, d: '本机备份与回退' },
  { k: 'settings', n: '基础设置', g: '系统', i: 'gear', f: pageSettings, d: '阈值 / 目录 / 主题' },
  { k: 'help', n: '帮助说明', g: '系统', i: 'help', f: pageHelp, d: '口径与引导' },
  { k: 'ds', n: '设计规范', g: '系统', i: 'palette', f: pageDS, d: '变量 / 组件 / 状态' },
];

/* ---------- 主题 ---------- */
function setTheme(t, silent) {
  state.theme = t;
  document.documentElement.dataset.theme = t;
  localStorage.setItem('fd-theme', t);
  $$('[data-theme-set]').forEach((el) => el.setAttribute('aria-pressed', String(el.dataset.themeSet === t)));
  if (!silent) {
    if (state.route === 'ds' || state.route === 'settings') render();
    showToast(t === 'pink' ? '已切换到「玫瑰粉」主题' : '已切换到「天青蓝」主题', 'ok');
  }
}

/* ---------- 外壳 ---------- */
function renderRail() {
  const groups = ['总览', '数据', '分类', '系统'];
  const pend = PEND_GROUPS.filter((g, i) => !state.pendingDone.has(i))
    .reduce((a, g) => a + g.items.length, 0);
  $('#rail').innerHTML = `
    <div class="brand">
      <span class="brand__mark">账</span>
      <span class="brand__text">
        <span class="brand__name" style="display:block">记账簿</span>
        <span class="brand__sub">finance.local</span>
      </span>
    </div>
    <nav class="nav" aria-label="主导航">
      ${groups.map((g) => `<div class="nav__group">
        <div class="nav__label">${g}</div>
        ${ROUTES.filter((r) => r.g === g).map((r) => `
          <button class="nav__item" data-go="${r.k}" ${state.route === r.k ? 'aria-current="page"' : ''}
            title="${r.n} · ${r.d}">
            ${icon(r.i, 17)}<span>${r.n}</span>
            ${r.k === 'pending' && pend > 0 ? `<span class="nav__badge">${pend}</span>` : ''}
          </button>`).join('')}
      </div>`).join('')}
    </nav>
    <div class="rail__foot">
      <div class="rail__card">
        <b>数据目录</b>
        D:\\finance-data<br>
        数据库 <code>4.2 MB</code> · 缓冲 486 MB
      </div>
      <div class="rail__ver"><span class="rail__dot">本地运行</span><span>v1.0.0</span></div>
    </div>`;
}

function renderTopbar() {
  const r = ROUTES.find((x) => x.k === state.route);
  $('#topbar').innerHTML = `
    <div class="topbar__crumb">
      <span>个人财务分析</span><span class="sep">/</span><b>${r.n}</b>
      <span class="sep">·</span><span>${r.d}</span>
    </div>
    <span class="topbar__date">2026-10-22 周四 · 仅监听 127.0.0.1</span>
    <div class="topbar__right">
      <div class="theme-switch" role="group" aria-label="界面主题">
        <button class="theme-switch__item" data-theme-set="pink" aria-pressed="${state.theme === 'pink'}" title="玫瑰粉 · 少女感"><i></i>粉</button>
        <button class="theme-switch__item" data-theme-set="sky" aria-pressed="${state.theme === 'sky'}" title="天青蓝 · 自然清新"><i></i>蓝</button>
      </div>
      <button class="icon-btn" data-go="help" aria-label="帮助">${icon('help', 17)}</button>
      <button class="icon-btn" data-go="settings" aria-label="设置">${icon('gear', 17)}</button>
    </div>`;
}

let lastRoute = null;
function render() {
  const r = ROUTES.find((x) => x.k === state.route) || ROUTES[0];
  renderRail();
  renderTopbar();
  $('#view').innerHTML = r.f();
  if (lastRoute !== state.route) {
    window.scrollTo(0, 0);
    lastRoute = state.route;
  }
  if (state.focus === 'q') {
    const el = $('[data-filter="q"]');
    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    state.focus = null;
  }
}

function go(route) {
  if (!ROUTES.some((r) => r.k === route)) return;
  state.route = route;
  if (location.hash.slice(1) !== route) history.replaceState(null, '', '#' + route);
  render();
}

/* ---------- 轻提示 ---------- */
function showToast(msg, kind) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ' toast--' + kind : '');
  el.innerHTML = `<i></i><span>${msg}</span>`;
  box.appendChild(el);
  setTimeout(() => { el.style.transition = 'opacity .3s, transform .3s'; el.style.opacity = '0'; el.style.transform = 'translateY(6px)'; }, 2600);
  setTimeout(() => el.remove(), 3000);
}

/* ---------- 弹层 ---------- */
function openLayer(html) {
  const layer = $('#layer');
  layer.innerHTML = html;
  document.body.style.overflow = 'hidden';
  const focusable = layer.querySelector('.modal, .drawer');
  if (focusable) focusable.setAttribute('tabindex', '-1');
  setTimeout(() => focusable && focusable.focus(), 30);
}
function closeLayer() {
  $('#layer').innerHTML = '';
  document.body.style.overflow = '';
}

function modal({ title, sub, body, foot, size }) {
  openLayer(`<div class="overlay" data-act="close-layer">
    <div class="modal ${size || ''}" role="dialog" aria-modal="true" aria-label="${title}">
      <div class="modal__head">
        <div><div class="modal__title">${title}</div>${sub ? `<div class="modal__sub">${sub}</div>` : ''}</div>
        <div class="spacer"></div>
        <button class="icon-btn" data-act="close-layer" aria-label="关闭">${icon('x', 16)}</button>
      </div>
      <div class="modal__body">${body}</div>
      <div class="modal__foot">${foot}</div>
    </div>
  </div>`);
}

function drawer({ title, sub, body, foot }) {
  openLayer(`<div class="overlay drawer-overlay" data-act="close-layer">
    <div class="drawer" role="dialog" aria-modal="true" aria-label="${title}">
      <div class="drawer__head">
        <div><div class="modal__title">${title}</div>${sub ? `<div class="modal__sub">${sub}</div>` : ''}</div>
        <button class="icon-btn" data-act="close-layer" aria-label="关闭">${icon('x', 16)}</button>
      </div>
      <div class="drawer__body">${body}</div>
      <div class="drawer__foot">${foot}</div>
    </div>
  </div>`);
}

/* ---------- 明细抽屉 ---------- */
function openTx(id) {
  const t = TX.find((x) => x.id === id);
  if (!t) return;
  const ro = (k, v) => `<div class="kv"><div class="kv__k">${k}</div><div class="kv__v" style="font-size:13px">${v}</div></div>`;
  drawer({
    title: t.cp,
    sub: `${t.time} · 来源 ${t.batch} / 第 ${t.row} 行`,
    body: `
      <div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span class="num" style="font-size:var(--t-3xl);font-weight:500;color:${t.amt > 0 ? 'var(--fin-down)' : 'var(--text-1)'}">
          ${t.amt > 0 ? '+' : '−'}${fmt(Math.abs(t.amt))}</span>
        <div class="row" style="gap:6px">${stBadge(t.status)}
          ${t.dir === 'neutral' ? '<span class="badge badge--neutral">中性 · 不计收支</span>' : ''}</div>
      </div>
      <p class="small muted" style="margin-bottom:18px">${t.item}</p>

      <div class="section-label" style="margin-bottom:10px">原始事实字段 · 只读</div>
      <div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:8px">
        ${ro('交易时间', t.time)}
        ${ro('收支方向', DIR[t.dir])}
        ${ro('交易对方', t.cp)}
        ${ro('支付方式', t.method)}
        ${ro('商品说明', t.item)}
        ${ro('来源批次', `<span class="mono">${t.batch}</span>`)}
      </div>
      <div class="notice" style="margin-bottom:20px">
        <span class="notice__icon">${icon('lock', 14)}</span>
        <div>这些字段来自原始库，<b>不可编辑</b>。若原始事实有误，请重新导入正确文件并排除错误批次。</div>
      </div>

      <div class="section-label" style="margin-bottom:10px">可编辑</div>
      <div class="field" style="margin-bottom:14px">
        <label class="field__label">分类</label>
        <div class="select"><select class="select__native">
          <option>${t.l2}</option><option>支出 · 餐饮美食 · 外卖</option><option>支出 · 购物消费 · 日用百货</option>
          <option>支出 · 交通出行 · 网约车</option><option>收入 · 家人资助</option><option>资金流转 · 个人转账</option>
        </select></div>
        <span class="field__hint">改分类不会改变统计归属：direction=neutral 的记录仍不计入收支。</span>
      </div>
      <div class="field">
        <label class="field__label">备注</label>
        <textarea class="textarea" placeholder="例如：和室友拼单">${t.note || ''}</textarea>
      </div>
      ${t.status === 'corrected' ? `<div class="notice notice--info" style="margin-top:16px">
        <span class="notice__icon">${icon('info', 14)}</span>
        <div>该记录已被人工修正，后续重算默认不会覆盖它。</div></div>` : ''}`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--outline" data-act="toggle-exclude">${t.status === 'excluded' ? '恢复计入' : '排除出统计'}</button>
      <button class="btn btn--primary" data-act="save-tx">保存修改</button>`,
  });
}

/* ---------- 弹窗内容 ---------- */
function mForceNew() {
  modal({
    title: '强制新增这条记录？',
    sub: '判定为重复，但你确认它是真实消费',
    size: 'modal--sm',
    body: `<div class="notice notice--warn" style="margin-bottom:16px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div>2026-10-16 09:00 · 零钱通 · ¥500.00<br>与库内记录指纹一致（时间 + 金额 + 方向 + 对方 + 说明）。</div>
      </div>
      <div class="field">
        <label class="field__label">原因 <span class="req">*</span></label>
        <textarea class="textarea" placeholder="例如：当天确实有两笔相同的转入，重复属实"></textarea>
        <span class="field__hint">原因与操作时间会写入 override 记录，可在明细与入库报告中追溯。</span>
      </div>`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--primary" data-act="force-ok">确认强制新增</button>`,
  });
}

function mRecalc() {
  modal({
    title: '重算历史流水',
    sub: '按当前规则集重新分类，不影响 raw 原始库',
    body: `<div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
        <div class="kv"><div class="kv__k">将重算</div><div class="kv__v">128<small>条</small></div></div>
        <div class="kv"><div class="kv__k">其中人工修正</div><div class="kv__v" style="color:var(--primary-ink)">4<small>条</small></div></div>
      </div>
      <div class="notice notice--info" style="margin-bottom:16px">
        <span class="notice__icon">${icon('info', 14)}</span>
        <div>默认<b>只处理未经人工修正 / 排除</b>的记录；4 条人工修正将保持不变，报告中单列。</div>
      </div>
      <label class="checkbox" style="margin-bottom:8px"><input type="checkbox"><span class="checkbox__box"></span>同时覆盖人工修正结果（不推荐）</label>
      <p class="tiny muted">重算为事务操作，失败整体回滚，不会出现「半新半旧」。</p>`,
    foot: `<span class="tiny muted" style="margin-right:auto">${icon('lock', 12)} raw 表不变</span>
      <button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--primary" data-act="recalc-ok">开始重算</button>`,
  });
}

function mAddRule() {
  modal({
    title: '新增分类规则',
    sub: '命中关键词的流水将自动归入目标分类',
    body: `<div class="grid" style="grid-template-columns:1fr 1fr;gap:14px">
        <div class="field"><label class="field__label">关键词 <span class="req">*</span></label>
          <input class="input" placeholder="多个用 | 分隔，如 美团|饿了么"></div>
        <div class="field"><label class="field__label">匹配字段</label>
          <div class="select"><select class="select__native"><option>交易对方</option><option>商品说明</option><option>交易类型</option></select></div></div>
        <div class="field"><label class="field__label">目标分类 <span class="req">*</span></label>
          <div class="select"><select class="select__native"><option>支出 · 餐饮美食 · 外卖</option><option>支出 · 购物消费 · 日用百货</option><option>资金流转 · 个人转账</option></select></div></div>
        <div class="field"><label class="field__label">优先级 <span class="req">*</span></label>
          <input class="input input--num" value="100"><span class="field__hint">数值越大越优先，同级取最新</span></div>
      </div>
      <div class="notice notice--info" style="margin-top:16px"><span class="notice__icon">${icon('info', 14)}</span>
        <div>保存后仅影响<b>后续导入</b>；历史流水需要点「重算」才会应用。</div></div>`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--primary" data-act="toast-close" data-msg="规则已保存，后续导入将自动套用">保存规则</button>`,
  });
}

function mDisableCat(name, count) {
  modal({
    title: `停用「${name}」`,
    sub: `该分类已被 ${count} 笔流水引用，必须先决定这些记录的去向`,
    body: `<label class="radio" style="display:flex;margin-bottom:12px;align-items:flex-start">
        <input type="radio" name="mig" checked><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">保留历史记录</b><br><span class="tiny muted">已有 ${count} 笔仍显示原分类，但选择器中不再可选</span></span></label>
      <label class="radio" style="display:flex;margin-bottom:14px;align-items:flex-start">
        <input type="radio" name="mig"><span class="radio__box" style="margin-top:2px"></span>
        <span><b class="small">迁移到其他分类</b><br><span class="tiny muted">这 ${count} 笔会改到新分类，收支总额不变</span></span></label>
      <div class="select"><select class="select__native" disabled><option>支出 · 餐饮美食 · 其他餐饮</option><option>支出 · 其他支出</option></select></div>
      <div class="notice notice--warn" style="margin-top:14px"><span class="notice__icon">${icon('alert', 14)}</span>
        <div>分类归属<b>不影响收支统计</b>：迁移前后总收入 / 总支出完全一致。</div></div>`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--danger" data-act="toast-close" data-msg="分类已停用，${count} 笔记录按「保留历史」处理">确认停用</button>`,
  });
}

function mRestore(file) {
  modal({
    title: '从备份恢复',
    sub: '恢复会覆盖整个数据库文件',
    body: `<div class="batch-trace" style="margin-bottom:16px">${icon('db', 14)}
        <span class="mono">${file || 'finance-2026-10-13.sqlite'}</span>
        <span class="badge badge--ok" style="margin-left:auto">校验通过</span></div>
      <div class="kv-grid" style="grid-template-columns:1fr 1fr;margin-bottom:16px">
        <div class="kv"><div class="kv__k">将恢复</div><div class="kv__v">1,086<small>笔</small></div></div>
        <div class="kv"><div class="kv__k">raw 分表</div><div class="kv__v">10<small>个</small></div></div>
        <div class="kv"><div class="kv__k">规则 / 分类</div><div class="kv__v">8 / 18</div></div>
        <div class="kv"><div class="kv__k">备份时间</div><div class="kv__v" style="font-size:13px">10-13 21:04</div></div>
      </div>
      <div class="notice notice--ok" style="margin-bottom:16px"><span class="notice__icon">${icon('shield', 14)}</span>
        <div>恢复前会自动把当前库备份为 <b class="mono">rollback-20261022-2007.sqlite</b>，失败可一键回退。</div></div>
      <div class="field"><label class="field__label">输入「恢复」以确认 <span class="req">*</span></label>
        <input class="input" placeholder="恢复"></div>`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--danger" data-act="restore-ok">执行恢复</button>`,
  });
}

function mMigrate() {
  modal({
    title: '数据迁移向导',
    sub: '把数据库与缓冲区搬到新目录',
    body: `<div class="stack" style="gap:14px">
        <div class="field"><label class="field__label">目标目录 <span class="req">*</span></label>
          <input class="input mono" value="E:\\finance-data" style="font-size:12px">
          <span class="field__hint">必须是本机绝对路径；不允许系统敏感目录与网络位置。</span></div>
        <div class="kv-grid" style="grid-template-columns:1fr 1fr">
          <div class="kv"><div class="kv__k">将搬移</div><div class="kv__v" style="font-size:13px">4.2 MB 数据库</div></div>
          <div class="kv"><div class="kv__k">缓冲区</div><div class="kv__v" style="font-size:13px">3 个待处理批次</div></div>
        </div>
        <div class="notice notice--warn"><span class="notice__icon">${icon('alert', 14)}</span>
          <div>搬移期间请勿操作服务；完成后需要重启，启动对账会按新目录执行。</div></div>
      </div>`,
    foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button>
      <button class="btn btn--primary" data-act="toast-close" data-msg="迁移完成，请重启服务以应用新目录">开始迁移</button>`,
  });
}

/* ---------- 导入向导 ---------- */
function simulateImport() {
  state.importing = true;
  render();
  let p = 0;
  const bar = $('#imp-bar'), pct = $('#imp-pct');
  const timer = setInterval(() => {
    p = Math.min(100, p + Math.random() * 26 + 12);
    if (bar) bar.style.width = p + '%';
    if (pct) pct.textContent = Math.round(p) + '%';
    if (p >= 100) {
      clearInterval(timer);
      setTimeout(() => {
        state.importing = false;
        state.wStep = 5;
        render();
        showToast('入库完成，原始文件已删除', 'ok');
      }, 380);
    }
  }, 200);
}

function simulateUpload() {
  const dz = $('.dropzone');
  if (!dz) return;
  dz.innerHTML = `<span class="dropzone__icon">${icon('upload', 22)}</span>
    <span class="dropzone__title">正在写入本地缓冲区…</span>
    <span class="dropzone__desc">流式落盘 · 同步检测磁盘余量</span>
    <div class="progress" style="width:220px;margin-top:8px"><div class="progress__bar" id="up-bar" style="width:6%"></div></div>`;
  let p = 6;
  const t = setInterval(() => {
    p = Math.min(100, p + 18);
    const b = $('#up-bar');
    if (b) b.style.width = p + '%';
    if (p >= 100) {
      clearInterval(t);
      setTimeout(() => {
        state.uploaded = true;
        render();
        showToast('文件已落盘缓冲区，尚未入库', 'ok');
      }, 260);
    }
  }, 130);
}

/* ---------- 事件 ---------- */
document.addEventListener('click', (e) => {
  const goEl = e.target.closest('[data-go]');
  if (goEl) { e.preventDefault(); go(goEl.dataset.go); return; }

  const th = e.target.closest('[data-theme-set]');
  if (th) { setTheme(th.dataset.themeSet); return; }

  const per = e.target.closest('[data-period]');
  if (per) { state.period = per.dataset.period; render(); return; }

  const mon = e.target.closest('[data-month]');
  if (mon) { state.rawMonth = mon.dataset.month; render(); return; }

  const catEl = e.target.closest('[data-cat]');
  if (catEl && !e.target.closest('[data-cat-l1]')) { state.cat = catEl.dataset.cat; render(); return; }

  const catL1 = e.target.closest('[data-cat-l1]');
  if (catL1 && !e.target.closest('[data-act="toggle"]')) { state.catL1 = catL1.dataset.catL1; render(); return; }

  const dirChip = e.target.closest('[data-filter="dir"]');
  if (dirChip) { state.txFilter.dir = dirChip.dataset.val; render(); return; }

  const sortEl = e.target.closest('[data-sort]');
  if (sortEl) {
    const k = sortEl.dataset.sort;
    state.sort = { key: k, dir: state.sort.key === k && state.sort.dir === 'desc' ? 'asc' : 'desc' };
    render(); return;
  }

  const actEl = e.target.closest('[data-act]');
  if (!actEl) {
    const row = e.target.closest('tr[data-id]');
    if (row && $('#pending-body') === null) openTx(row.dataset.id);
    return;
  }
  const act = actEl.dataset.act;

  switch (act) {
    case 'toast': showToast(actEl.dataset.msg || '已完成'); break;
    case 'toast-close': closeLayer(); showToast(actEl.dataset.msg || '已完成', 'ok'); break;
    case 'toggle': {
      const on = actEl.getAttribute('aria-checked') === 'true';
      actEl.setAttribute('aria-checked', String(!on));
      break;
    }
    case 'rule-toggle': {
      const i = +actEl.dataset.i;
      RULES[i].on = !RULES[i].on;
      actEl.setAttribute('aria-checked', String(RULES[i].on));
      showToast(RULES[i].on ? `已启用「${RULES[i].kw}」` : `已停用「${RULES[i].kw}」，新导入不再套用`);
      break;
    }
    case 'close-layer': {
      /* 点遮罩才关闭；点面板内部不关闭 */
      if (actEl.classList.contains('overlay') && e.target.closest('.modal, .drawer')) break;
      closeLayer();
      break;
    }
    case 'open-tx': openTx(actEl.dataset.id); break;
    case 'save-tx': closeLayer(); showToast('已保存分类与备注（人工修正不会被重算覆盖）', 'ok'); break;
    case 'toggle-exclude': closeLayer(); showToast('已标记为「已排除」，不再计入任何收支统计'); break;
    case 'reset-filter': state.txFilter = { status: 'all', dir: 'all', q: '', cat: 'all' }; render(); break;
    case 'clear-sel': state.txSel.clear(); render(); break;
    case 'bulk-cat': showToast('批量改分类：已选 ' + state.txSel.size + ' 笔（示例）'); break;
    case 'bulk-rule': showToast('已生成规则「按对方自动归类」，后续导入生效', 'ok'); break;
    case 'upload': simulateUpload(); break;
    case 'reset-upload': state.uploaded = false; render(); break;
    case 'w-next': state.wStep = Math.min(5, state.wStep + 1); render(); break;
    case 'w-prev': state.wStep = Math.max(1, state.wStep - 1); render(); break;
    case 'force-new': mForceNew(); break;
    case 'force-ok': closeLayer(); showToast('已标记「强制新增」，入库时按新增处理并留痕', 'ok'); break;
    case 'confirm-import': if (!state.importing) simulateImport(); break;
    case 'pick-group': {
      const box = actEl.closest('.pending-group');
      const cb = box.querySelector('input[type=checkbox]');
      cb.checked = !cb.checked;
      box.classList.toggle('is-checked', cb.checked);
      const n = $$('#pending-body .pending-group input:checked').length;
      const c = $('#pick-count'); if (c) c.textContent = n;
      break;
    }
    case 'apply-pending': {
      const picked = $$('#pending-body .pending-group').filter((g) => g.querySelector('input').checked);
      if (!picked.length) { showToast('请先勾选要处理的流水', 'warn'); break; }
      picked.forEach((g) => state.pendingDone.add(+g.dataset.group));
      render();
      const left = $$('#pending-body .pending-group').length;
      showToast(`已处理 ${picked.length} 组${left ? '，剩余 ' + left + ' 组待确认' : '，队列已清空'}`, 'ok');
      break;
    }
    case 'drop': showToast('已丢弃批次并删除缓冲区文件（示例）'); break;
    case 'recalc': mRecalc(); break;
    case 'recalc-ok': closeLayer(); showToast('重算完成：更新 124 条，人工修正 4 条未重算', 'ok'); break;
    case 'add-rule': mAddRule(); break;
    case 'disable-cat': mDisableCat(actEl.dataset.name, actEl.dataset.count); break;
    case 'restore': mRestore(); break;
    case 'restore-ok': closeLayer(); showToast('恢复完成，已按备份重建数据库（示例）', 'ok'); break;
    case 'backup': showToast('正在备份数据库到 D:\\finance-data\\backups\\（示例）', 'ok'); break;
    case 'migrate': mMigrate(); break;
    case 'save-settings': showToast('保存被拒绝：数据目录不能指向网络位置', 'warn'); break;
    case 'modal-demo': modal({
      title: '这是一个标准弹窗',
      sub: '用于二次确认与轻表单，最大宽度 560px',
      body: `<p class="small muted" style="line-height:1.9;margin-bottom:14px">弹窗出现时背景模糊 3px，按 Esc 或点击遮罩关闭。破坏性操作会把主按钮换成 danger 变体，并要求二次确认。</p>
        <div class="field"><label class="field__label">备注</label><input class="input" placeholder="可选"></div>`,
      foot: `<button class="btn btn--ghost" data-act="close-layer">取消</button><button class="btn btn--primary" data-act="close-layer">确定</button>`,
    }); break;
    case 'drawer-demo': drawer({
      title: '抽屉面板',
      sub: '右侧 480px，用于详情与轻编辑',
      body: `<p class="small muted" style="line-height:1.9">抽屉适合「不离开列表上下文」的查看与编辑，例如流水详情、批次追溯。抽屉内可以再叠一层弹窗做确认。</p>`,
      foot: `<button class="btn btn--ghost" data-act="close-layer">关闭</button>`,
    }); break;
    default: break;
  }
});

document.addEventListener('change', (e) => {
  const el = e.target;
  if (el.dataset.filter === 'status') { state.txFilter.status = el.value; render(); }
  if (el.dataset.filter === 'cat') { state.txFilter.cat = el.value; render(); }

  /* 复选：明细行选择 / 全选 / 待确认分组 */
  if (el.dataset.act === 'sel-row') {
    const id = el.dataset.id;
    if (el.checked) state.txSel.add(id); else state.txSel.delete(id);
    render();
  }
  if (el.dataset.act === 'sel-all') {
    state.txSel.clear();
    if (el.checked) txRows().forEach((t) => state.txSel.add(t.id));
    render();
  }
  if (el.dataset.act === 'pick-cb') {
    const box = el.closest('.pending-group');
    box.classList.toggle('is-checked', el.checked);
    const n = $$('#pending-body .pending-group input:checked').length;
    const c = $('#pick-count'); if (c) c.textContent = n;
  }
});

document.addEventListener('input', (e) => {
  if (e.target.dataset.filter === 'q') {
    state.txFilter.q = e.target.value;
    state.focus = 'q';
    render();
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeLayer();
});

/* ---------- 图表 tooltip ---------- */
const tip = { el: null, raf: 0 };
document.addEventListener('mousemove', (e) => {
  const el = e.target.closest('[data-tip]');
  if (!el) {
    if (tip.el) tip.el.classList.remove('is-on');
    $$('.chart .pt').forEach((p) => (p.style.opacity = '0'));
    return;
  }
  tip.el = tip.el || $('#tip');
  tip.el.innerHTML = el.dataset.tip;
  tip.el.classList.add('is-on');
  tip.el.style.left = e.clientX + 'px';
  tip.el.style.top = e.clientY + 'px';
  if (el.classList.contains('hit')) {
    const i = el.dataset.i;
    const svg = el.closest('svg');
    if (svg) {
      svg.querySelectorAll('.pt').forEach((p) => (p.style.opacity = p.dataset.i === i ? '1' : '0'));
    }
  }
});

/* ---------- 启动 ---------- */
const sp = new URLSearchParams(location.search);
const qTheme = sp.get('theme');
if (qTheme === 'pink' || qTheme === 'sky') state.theme = qTheme;
const qStep = Number(sp.get('step'));            /* 演示用：直接跳到导入向导某一步 */
if (qStep >= 1 && qStep <= 5) { state.wStep = qStep; state.uploaded = qStep > 1; }
const qPeriod = sp.get('period');                /* 演示用：指定统计周期 */
if (P[qPeriod]) state.period = qPeriod;
document.documentElement.dataset.theme = state.theme;
const initial = decodeURIComponent(location.hash.slice(1));
if (ROUTES.some((r) => r.k === initial)) state.route = initial;
window.addEventListener('hashchange', () => {
  const k = decodeURIComponent(location.hash.slice(1));
  if (ROUTES.some((r) => r.k === k) && k !== state.route) { state.route = k; render(); }
});
render();
