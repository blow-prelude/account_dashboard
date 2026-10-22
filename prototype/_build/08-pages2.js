/* ============================================================
   08 · 页面渲染（续）：缓冲区 / 原始库 / 规则 / 分类 / 备份 / 设置 / 帮助 / 设计系统
   ============================================================ */

/* ---------------- 7. 缓冲区 ---------------- */
function pageBuffer() {
  const act = (status, id) => {
    if (status === 'ready') return `<button class="btn btn--soft btn--sm" data-go="import">继续处理</button><button class="btn btn--ghost btn--sm" data-act="drop">丢弃</button>`;
    if (status === 'mapping') return `<button class="btn btn--soft btn--sm" data-go="import">继续映射</button><button class="btn btn--ghost btn--sm" data-act="drop">丢弃</button>`;
    if (status === 'failed') return `<button class="btn btn--outline btn--sm" data-act="toast" data-msg="已重新解析（示例：编码仍失败，建议另存为 UTF-8）">重新解析</button><button class="btn btn--ghost btn--sm" data-act="drop">丢弃</button>`;
    if (status === 'done') return `<button class="btn btn--ghost btn--sm" data-go="raw">查看报告</button>`;
    if (status === 'cleaning') return `<button class="btn btn--outline btn--sm" data-act="toast" data-msg="已重试删除，文件仍被占用">重试删除</button>`;
    return `<button class="btn btn--ghost btn--sm" data-act="toast" data-msg="请重新上传该文件">重新上传</button>`;
  };

  const rows = BATCHES.map((b) => `<tr>
    <td><div class="cell-2line"><span class="td-strong">${b.file}</span><small class="mono">${b.id}</small></div></td>
    <td><span class="badge badge--plain badge--neutral">${b.ch}</span></td>
    <td>${stBadge(b.status)}</td>
    <td class="td-num">${b.rows || '—'}</td>
    <td class="td-num">${b.size}</td>
    <td class="td-muted num">${b.at}</td>
    <td class="td-muted" style="max-width:220px">${b.note}</td>
    <td class="right nowrap">${act(b.status, b.id)}</td>
  </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: '缓冲区批次',
    sub: `共 ${BATCHES.length} 个批次 · 文件落盘于本地缓冲区，确认入库后删除`,
    actions: `<button class="btn btn--outline btn--sm" data-act="toast" data-msg="残留扫描完成：发现 1 个孤儿文件">${icon('search', 13)}残留扫描</button>
      <button class="btn btn--primary btn--sm" data-go="import">${icon('upload', 13)}上传新文件</button>`,
    raw: `<div class="table-wrap"><table class="table">
      <thead><tr><th>文件</th><th>渠道</th><th>状态</th><th class="right">行数</th><th class="right">大小</th><th>上传时间</th><th>预检 / 说明</th><th class="right">操作</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`,
    foot: `<span>${icon('info', 12)} 状态单向流转，不接受从「已入库」回退</span>
      <span>等待处理 <b style="color:var(--text-1)">3</b> 个批次</span>`,
  });

  const space = card({
    title: '缓冲区目录',
    sub: '数据目录下的 staging/ 子目录',
    body: `<div class="batch-trace" style="font-family:var(--font-mono);font-size:11.5px;margin-bottom:14px">
        ${icon('folder', 14)} D:\\finance-data\\staging
      </div>
      <div class="row" style="justify-content:space-between;margin-bottom:6px">
        <span class="small">已用 <b class="num">486 MB</b> / 500 MB</span>
        <span class="badge badge--warn">接近阈值</span>
      </div>
      <div class="progress"><div class="progress__bar" style="width:97.2%;background:linear-gradient(90deg,var(--warn),var(--accent))"></div></div>
      <p class="tiny muted" style="margin-top:10px">超过默认 500MB 阈值会提醒清理；阈值可在设置中调整。目录被移动或删除时，启动自检会引导重建。</p>
      <div class="row" style="margin-top:14px">
        <button class="btn btn--outline btn--sm" data-act="toast" data-msg="目录可读写（校验通过）">${icon('check', 13)}校验可读写</button>
        <button class="btn btn--ghost btn--sm" data-go="settings">修改数据目录</button>
      </div>`,
  });

  const clean = card({
    title: '待清理',
    sub: '删除失败或孤儿文件',
    body: `<div class="notice notice--warn" style="margin-bottom:12px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div><b>1 个文件待清理</b><br>批次 B-20261014-1 已入库，物理删除时文件被占用。</div>
      </div>
      <div class="backup-file">
        <span class="file-icon" style="background:var(--surface-3);color:var(--text-3)">${icon('file', 16)}</span>
        <div style="flex:1;min-width:0"><b class="small strong">微信支付账单(202608).csv</b><div class="tiny muted">148 KB · 已入库 · 待删除</div></div>
        <button class="btn btn--outline btn--sm" data-act="toast" data-msg="已重试删除，文件仍被占用">重试</button>
      </div>
      <div class="backup-file">
        <span class="file-icon" style="background:var(--warn-soft);color:var(--warn)">${icon('file', 16)}</span>
        <div style="flex:1;min-width:0"><b class="small strong">tmp_upload_9f2a.part</b><div class="tiny muted">2.4 MB · 无对应批次的孤儿文件</div></div>
        <button class="btn btn--ghost btn--sm" data-act="toast" data-msg="已清理孤儿文件（示例）">清理</button>
      </div>`,
    foot: `<span class="tiny">启动对账会在每次启动时自动重试</span>`,
  });

  return pageHead('缓冲区', '上传后的文件暂存于此，确认入库前不入库、不外传',
    `<button class="btn btn--ghost btn--sm" data-act="toast" data-msg="已重新扫描缓冲区目录">${icon('refresh', 13)}刷新</button>`) +
    `<div class="grid g-12">
      <div class="c-12">${table}</div>
      <div class="c-7">${space}</div>
      <div class="c-5">${clean}</div>
    </div>`;
}

/* ---------------- 8. 原始库 ---------------- */
function pageRaw() {
  const m = state.rawMonth || '2026-10';
  const rows = TX.slice(0, 10).map((t, i) => `<tr>
    <td class="td-muted num">${i + 1}</td>
    <td class="num" style="font-size:12px">2026-${t.time.replace(' ', ' ')}:0${i % 6}</td>
    <td class="td-num">${t.amt > 0 ? '+' : '−'}${fmt(Math.abs(t.amt))}</td>
    <td>${t.dir === 'income' ? '<span class="badge badge--ok">income</span>' : t.dir === 'neutral' ? '<span class="badge badge--neutral">neutral</span>' : '<span class="badge badge--plain" style="background:var(--surface-3)">expense</span>'}</td>
    <td class="td-strong">${t.cp}</td>
    <td class="td-muted">${t.item}</td>
    <td class="td-muted mono">${t.batch}</td>
  </tr>`).join('');

  const monthList = `<section class="card">
    <div class="card__head"><div><div class="card__title">按月归档</div><div class="card__sub">raw_YYYY_MM · 只增不改</div></div></div>
    <div class="card__body" style="padding:10px">
      <div class="month-list">
        ${MONTHS.map((x) => `<button class="month-item" data-month="${x.m}" aria-current="${x.m === m}">
          ${icon('db', 14)}<span>${x.m.replace('-', ' 年 ')} 月</span><span class="month-item__n">${x.n}</span>
        </button>`).join('')}
      </div>
    </div>
  </section>`;

  const table = card({
    cls: 'card--flush',
    title: `raw_${m.replace('-', '_')}`,
    sub: `${MONTHS.find((x) => x.m === m).n} 条原始记录 · 保留导入原貌，不可编辑`,
    actions: `<button class="btn btn--outline btn--sm" data-act="toast" data-msg="已导出该月原始记录 CSV">${icon('download', 13)}导出</button>
      <button class="btn btn--soft btn--sm" data-act="recalc">${icon('refresh', 13)}从原始库重算</button>`,
    raw: `<div class="table-wrap"><table class="table">
      <thead><tr><th>行号</th><th>交易时间</th><th class="right">金额</th><th>方向</th><th>交易对方</th><th>商品说明</th><th>来源批次</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`,
    foot: `<span>${icon('lock', 12)} raw 表禁止修改，更正错误需重新导入正确文件并排除错误批次</span>
      <span>显示 10 / ${MONTHS.find((x) => x.m === m).n} 条</span>`,
  });

  const trace = card({
    title: '批次追溯',
    sub: '任一条主数据都能回到原始行',
    body: `<div class="batch-trace" style="margin-bottom:10px">${icon('list', 14)}
        <span>transaction #8821</span>${icon('chevronR', 12)}
        <span class="mono">B-20261019-1 / row 5</span>${icon('chevronR', 12)}
        <span class="mono">raw_2026_10</span>
        <span class="badge badge--ok" style="margin-left:auto">链路完整</span>
      </div>
      <div class="table-wrap" style="border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden">
        <table class="table table--compact">
          <thead><tr><th>映射快照（入库时）</th><th>文件列</th><th>清洗规则</th></tr></thead>
          <tbody>
            <tr><td>交易时间</td><td class="mono">交易时间</td><td class="td-muted">ISO 8601 本地时间</td></tr>
            <tr><td>金额</td><td class="mono">金额(元)</td><td class="td-muted">去符号 → ×100 → 整数分</td></tr>
            <tr><td>收支方向</td><td class="mono">收/支</td><td class="td-muted">枚举映射 + 关键词判定</td></tr>
          </tbody>
        </table>
      </div>
      <p class="tiny muted" style="margin-top:10px">mapping_snapshot 保证重算与追溯可还原当时的清洗口径。</p>`,
  });

  return pageHead('原始库', '按月分表归档导入原貌 · 审计与重算的唯一基础',
    `<div class="segmented"><button class="segmented__item" aria-pressed="true">按月</button><button class="segmented__item" data-act="toast" data-msg="按批次视图（示例）">按批次</button></div>`) +
    `<div class="grid g-12">
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

/* ---------------- 9. 分类规则 ---------------- */
function pageRules() {
  const rows = RULES.map((r, i) => `<tr>
    <td><span class="rule-kw">${r.kw}</span></td>
    <td class="td-muted">${r.field}</td>
    <td class="td-strong">${r.l1} · ${r.l2}</td>
    <td class="td-num">${r.p}</td>
    <td class="td-num td-muted">${r.hit}</td>
    <td><span class="switch" role="switch" aria-checked="${r.on}" data-act="rule-toggle" data-i="${i}" aria-label="启用规则"></span></td>
    <td class="right"><button class="icon-btn" data-act="toast" data-msg="规则编辑（示例）" aria-label="编辑">${icon('edit', 15)}</button>
      <button class="icon-btn" data-act="toast" data-msg="规则已删除（示例）" aria-label="删除">${icon('trash', 15)}</button></td>
  </tr>`).join('');

  const table = card({
    cls: 'card--flush',
    title: '自动分类规则',
    sub: '关键词 + 匹配字段 + 目标分类 + 优先级，命中多条取优先级高者',
    actions: `<div class="input-group" style="width:200px"><span class="input-group__icon">${icon('search', 14)}</span>
        <input class="input" placeholder="搜索关键词" style="height:30px;font-size:12px"></div>
      <button class="btn btn--primary btn--sm" data-act="add-rule">${icon('plus', 13)}新增规则</button>`,
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
    `<button class="btn btn--outline" data-act="recalc">${icon('refresh', 15)}重算历史</button>`) +
    table + `<div style="margin-top:16px">${hint}</div>`;
}

/* ---------------- 10. 分类体系 ---------------- */
function pageCategories() {
  const sel = state.catL1 || '支出';
  const cur = CATS.find((c) => c.l1 === sel) || CATS[1];
  const l1 = `<section class="card card--flush">
    <div class="card__head"><div><div class="card__title">一级分类</div><div class="card__sub">共 3 个 · 停用后不可再被选择</div></div>
      <div class="spacer"></div><button class="icon-btn" data-act="toast" data-msg="新增一级分类（示例）" aria-label="新增">${icon('plus', 16)}</button></div>
    <div class="cat-tree">
      ${CATS.map((c) => `<div class="cat-tree__l1 ${c.l1 === sel ? 'is-active' : ''}" data-cat-l1="${c.l1}">
        ${icon('tag', 15)}<b>${c.l1}</b><span class="cat-tree__count">${c.l2.length} 个二级 · ${c.l2.reduce((a, b) => a + b[1], 0)} 笔</span>
        <div class="spacer"></div>
        <span class="switch" role="switch" aria-checked="${c.on}" data-act="toggle"></span>
      </div>`).join('')}
    </div>
    <div class="card__foot"><span>${icon('info', 12)} 分类归属不影响收支统计</span><span class="tiny">统计以 direction 为准</span></div>
  </section>`;

  const l2 = `<section class="card card--flush">
    <div class="card__head"><div><div class="card__title">${cur.l1} · 二级分类</div>
      <div class="card__sub">${cur.l2.length} 个分类 · 共 ${cur.l2.reduce((a, b) => a + b[1], 0)} 笔引用</div></div>
      <div class="spacer"></div>
      <button class="btn btn--soft btn--sm" data-act="toast" data-msg="新增二级分类（示例）">${icon('plus', 13)}新增</button></div>
    <div class="table-wrap"><table class="table">
      <thead><tr><th>二级分类</th><th class="right">引用笔数</th><th>启用</th><th class="right">操作</th></tr></thead>
      <tbody>${cur.l2.map(([n, c]) => `<tr>
        <td class="td-strong">${n}</td>
        <td class="td-num td-muted">${c}</td>
        <td><span class="switch" role="switch" aria-checked="true" data-act="toggle"></span></td>
        <td class="right"><button class="btn btn--ghost btn--sm" data-act="disable-cat" data-name="${n}" data-count="${c}">停用</button></td>
      </tr>`).join('')}</tbody></table></div>
    <div class="card__foot"><span>${icon('lock', 12)} 被引用的分类不会被无声删除，停用需选择迁移方式</span></div>
  </section>`;

  return pageHead('分类体系', '维护一级 / 二级分类 · 停用引用中的分类必须先迁移',
    `<button class="btn btn--outline" data-act="toast" data-msg="已导出分类体系（CSV）">${icon('download', 15)}导出</button>`) +
    `<div class="grid g-12"><div class="c-5">${l1}</div><div class="c-7">${l2}</div>
      <div class="c-12"><div class="notice notice--warn"><span class="notice__icon">${icon('alert', 15)}</span>
        <div><b>停用「餐饮美食 · 咖啡茶饮」会怎样？</b> 该分类有 68 笔引用。系统会要求你选择「保留历史记录」或「迁移到其他分类」，迁移不改变收支总额。</div></div></div>
    </div>`;
}

/* ---------------- 11. 备份与恢复 ---------------- */
function pageBackup() {
  const status = card({
    title: '备份状态',
    sub: '备份文件仅存本机，请自行妥善保管',
    body: `<div class="row" style="gap:16px;align-items:flex-start;margin-bottom:16px">
        <div style="flex:1">
          <div class="small muted">上次备份</div>
          <div class="num" style="font-size:var(--t-2xl);color:var(--text-1);margin-top:2px">10-13 21:04</div>
          <div class="row" style="margin-top:6px"><span class="badge badge--warn">已 9 天未备份</span>
            <span class="tiny muted">提醒间隔 7 天</span></div>
        </div>
        <div style="text-align:right">
          <div class="small muted">数据库大小</div>
          <div class="num" style="font-size:var(--t-xl);color:var(--text-1);margin-top:4px">4.2 MB</div>
          <div class="tiny muted">含 10 个月 · 1,086 笔</div>
        </div>
      </div>
      <div class="notice notice--warn" style="margin-bottom:16px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div><b>建议每周备份一次。</b>备份文件不要上传到公开平台，也不要放在会被自动清理的目录。</div>
      </div>
      <div class="row">
        <button class="btn btn--primary" data-act="backup">${icon('shield', 15)}立即备份数据库</button>
        <button class="btn btn--outline" data-act="toast" data-msg="正在导出 JSON 全量数据…">${icon('download', 15)}导出 JSON</button>
        <button class="btn btn--ghost" data-act="toast" data-msg="正在导出 CSV（明细 + 分类）…">导出 CSV</button>
      </div>
      <p class="tiny muted" style="margin-top:12px">备份路径：D:\\finance-data\\backups\\ · 恢复前会自动备份当前库，失败可一键回退</p>`,
  });

  const files = card({
    cls: 'card--flush',
    title: '本机备份文件',
    sub: `共 ${BACKUPS.length} 个`,
    raw: `<div style="padding:4px 20px 12px">
      ${BACKUPS.map((b) => `<div class="backup-file">
        <span class="file-icon" style="background:var(--primary-soft);color:var(--primary-ink)">${icon('db', 16)}</span>
        <div style="flex:1;min-width:0"><b class="small strong" style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${b.name}</b>
          <span class="tiny muted">${b.size} · ${b.at} · ${b.kind}</span></div>
        <button class="btn btn--outline btn--sm" ${b.kind === '数据库备份' ? 'data-act="restore"' : 'data-act="toast" data-msg="已开始下载（示例）"'}>${b.kind === '数据库备份' ? '恢复' : '下载'}</button>
      </div>`).join('')}
    </div>`,
    foot: `<span>${icon('lock', 12)} 不引导拷贝到外部介质</span><span class="tiny">最近 30 天</span>`,
  });

  const danger = card({
    cls: 'card--quiet',
    title: '恢复与回退',
    sub: '恢复是破坏性操作，务必先备份',
    body: `<div class="step" style="margin-bottom:10px"><span class="step__dot">1</span>
        <span class="small">选择备份文件 → 预览将入库的记录数并校验完整性</span></div>
      <div class="step" style="margin-bottom:10px"><span class="step__dot">2</span>
        <span class="small">系统<b>自动备份当前库</b>，作为回退点</span></div>
      <div class="step" style="margin-bottom:14px"><span class="step__dot">3</span>
        <span class="small">二次确认后执行恢复；失败或中断可一键回退</span></div>
      <button class="btn btn--danger btn--block" data-act="restore">${icon('alert', 15)}从备份恢复…</button>
      <p class="tiny muted" style="margin-top:10px;text-align:center">恢复期间服务不可用，请勿关闭页面</p>`,
  });

  return pageHead('备份与恢复', '防止数据丢失 · 双通道：数据库整体备份 + 全量导出',
    `<button class="btn btn--ghost" data-go="help">${icon('help', 15)}备份指引</button>`) +
    `<div class="grid g-12">
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

/* ---------------- 12. 设置 ---------------- */
function pageSettings() {
  const row = (title, desc, ctl, flag) => `<div class="setting-row">
    <div><div class="setting-row__title">${title}${flag || ''}</div><div class="setting-row__desc">${desc}</div></div>
    <div class="setting-row__ctl">${ctl}</div>
  </div>`;

  const form = card({
    title: '记账与提醒',
    sub: '保存后立即生效，无需重启',
    body:
      row('单日支出阈值', '超过阈值的日期在趋势图上高亮，并写入月度摘要。', 
        `<input class="input input--num" value="200" style="text-align:right;width:108px"><span class="small muted">元</span>`) +
      row('备份提醒间隔', '距上次备份超过该天数时，仪表盘与报表页顶部提醒。', 
        `<input class="input input--num" value="7" style="text-align:right;width:108px"><span class="small muted">天</span>`) +
      row('每周起始日', '仅影响季度报表的按周聚合边界。',
        `<div class="select"><select class="select__native"><option>周一</option><option>周日</option></select></div>`) +
      row('本地事件日志', '记录导入成功率、待确认率、删除与补删次数。仅存本机，不上传。',
        `<span class="switch" role="switch" aria-checked="false" data-act="toggle"></span>`) +
      row('界面主题', '两套主题共用同一套语义变量，切换不会改变任何布局与数据。',
        `<div class="theme-switch">
          <button class="theme-switch__item" data-theme-set="pink" aria-pressed="${state.theme === 'pink'}"><i></i>玫瑰粉</button>
          <button class="theme-switch__item" data-theme-set="sky" aria-pressed="${state.theme === 'sky'}"><i></i>天青蓝</button>
        </div>`),
  });

  const dir = `<section class="card">
    <div class="card__head"><div><div class="card__title">数据目录</div><div class="card__sub">数据库 + 缓冲区 + 备份的统一根目录</div></div></div>
    <div class="card__body">
      <div class="field is-invalid">
        <label class="field__label">当前路径</label>
        <input class="input mono" value="\\\\NAS\\share\\finance" style="font-size:12px">
        <span class="field__error">${icon('alert', 11)} 不能指向网络位置，请选择本机磁盘路径</span>
      </div>
      <div class="field" style="margin-top:14px">
        <label class="field__label">备选路径（示例）</label>
        <input class="input mono" value="D:\\finance-data" style="font-size:12px">
        <span class="field__hint">路径合法化校验：必须为本地绝对路径；禁止系统敏感目录（C:\\Windows 等）与网络位置。</span>
      </div>
      <div class="notice notice--warn" style="margin-top:14px">
        <span class="notice__icon">${icon('alert', 14)}</span>
        <div>更换目录会搬移数据库与缓冲区文件，执行前请先备份，搬移期间不要操作。</div>
      </div>
      <button class="btn btn--outline btn--block" style="margin-top:14px" data-act="migrate">${icon('folder', 15)}打开数据迁移向导</button>
    </div>
  </section>`;

  const save = card({
    cls: 'card--quiet',
    body: `<div class="section-label" style="margin-bottom:10px">保存</div>
      <p class="small muted" style="margin-bottom:14px">有 1 项设置未通过校验，保存会被拒绝并给出原因（入口校验，不进入业务层）。</p>
      <button class="btn btn--primary btn--block" data-act="save-settings">${icon('check', 15)}保存全部设置</button>
      <p class="tiny muted" style="margin-top:10px;text-align:center">上次保存 10-13 21:04</p>`,
  });

  return pageHead('基础设置', '阈值、提醒、周期与数据目录 · 键值均做类型校验',
    `<button class="btn btn--ghost" data-act="toast" data-msg="设置已恢复默认值（示例）">恢复默认</button>`) +
    `<div class="grid g-12"><div class="c-8">${form}</div>
      <div class="c-4 stack">${dir}${save}</div></div>`;
}

/* ---------------- 13. 帮助 ---------------- */
function pageHelp() {
  const toc = `<section class="card"><div class="card__body" style="padding:12px">
    <div class="help-toc">
      <a href="#h-1" class="is-active">收支口径说明</a>
      <a href="#h-2">导入流程引导</a>
      <a href="#h-3">备份指引</a>
      <a href="#h-4">异常自助处理</a>
      <a href="#h-5">隐私与部署</a>
    </div></div></section>`;

  const caliber = card({
    title: '收支口径说明',
    sub: '全部统计以 direction 为唯一准绳',
    body: `<div class="help-prose">
      <p>「钱花在哪」这件事，先要统一口径：<b>一笔流水是否计入收入/支出，只看它的方向（direction）</b>，与它被归到哪个分类无关。零钱通/余额宝的申赎、信用卡还款、银行卡互转、提现都属于资产形态转移，方向记为 <b>neutral</b>，一律不计入收支。</p>
      <div class="table-wrap" style="border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden;margin:14px 0">
        <table class="table table--compact">
          <thead><tr><th>常见场景</th><th>direction</th><th>计入收支</th><th>默认分类</th></tr></thead>
          <tbody>
            <tr><td>父母转账、奖助学金</td><td><span class="badge badge--ok">income</span></td><td>计入收入</td><td class="td-muted">收入 · 家人资助 / 奖学金</td></tr>
            <tr><td>点外卖、坐地铁</td><td><span class="badge badge--plain" style="background:var(--surface-3)">expense</span></td><td>计入支出</td><td class="td-muted">支出 · 餐饮 / 交通</td></tr>
            <tr><td>零钱通转入 / 转出</td><td><span class="badge badge--neutral">neutral</span></td><td><b>不计入</b></td><td class="td-muted">资金流转 · 申购赎回</td></tr>
            <tr><td>信用卡还款</td><td><span class="badge badge--neutral">neutral</span></td><td><b>不计入</b></td><td class="td-muted">资金流转 · 信用卡还款</td></tr>
            <tr><td>银行卡互转 / 提现</td><td><span class="badge badge--neutral">neutral</span></td><td><b>不计入</b></td><td class="td-muted">资金流转</td></tr>
            <tr><td>转账给个人</td><td><span class="badge badge--neutral">neutral</span></td><td><b>不计入</b>（可改分类，仍不计）</td><td class="td-muted">资金流转 · 个人转账</td></tr>
          </tbody>
        </table>
      </div>
      <div class="notice notice--info"><span class="notice__icon">${icon('info', 15)}</span>
        <div><b>把一笔 neutral 记录改分类到「餐饮美食」，它也不会进总支出。</b>分类只决定「归到哪里」，方向才决定「算不算」。</div></div>
    </div>`,
  });

  const steps = card({
    title: '导入流程引导',
    sub: '从导出账单到看见报表，十分钟内完成',
    body: `<div class="help-prose"><ol>
      <li><b>导出账单</b>：在支付 App 里导出 CSV 或 Excel（微信：我 → 服务 → 钱包 → 账单 → 常见问题 → 下载账单）。</li>
      <li><b>上传缓冲区</b>：把文件拖进导入页。文件只落在本机缓冲区，此时还没有写库。</li>
      <li><b>映射与预检</b>：五个核心字段通常会自动命中；预检会逐条标注新增/重复，误判可「强制新增」。</li>
      <li><b>确认入库</b>：事务写入按月分表 + 主数据层，成功后自动删除缓冲区原文件。</li>
    </ol></div>`,
  });

  const backup = card({
    title: '备份指引',
    sub: '本周备份了吗',
    body: `<div class="help-prose">
      <p>备份会在 <code class="mono">backups/</code> 生成一个完整的数据库文件，恢复时整体覆盖。也可以在备份页导出 JSON/CSV 作为第二通道。</p>
      <p><b>请自行妥善保管备份文件，不要上传到公开平台或聊天工具。</b>本产品不引导你把数据拷贝到外部介质或网盘。</p>
    </div>`,
  });

  const trouble = card({
    title: '异常自助处理',
    sub: '最常见的 4 个问题',
    body: `<div class="help-prose"><ol>
      <li><b>中文乱码 / 解析失败</b>：用 Excel 另存为「CSV UTF-8」，再重新上传。</li>
      <li><b>流水进了待确认</b>：说明没命中规则，去待确认队列批量归类，勾选「同时生成规则」。</li>
      <li><b>提示文件待清理</b>：文件被其他程序占用，关闭后到缓冲区点「重试删除」，数据不受影响。</li>
      <li><b>重复导入被跳过</b>：确认是真实消费时，在预检里点「强制新增」并填写原因，会留痕可查。</li>
    </ol></div>`,
  });

  const privacy = card({
    title: '隐私与部署',
    body: `<div class="help-prose"><p>后端仅监听 <code class="mono">127.0.0.1</code>，不提供对外绑定选项；不会自动抓取任何平台数据；不集成第三方统计或云 SDK。所有数据（数据库、缓冲区、备份）都保存在你选择的数据目录里。</p></div>
    <div class="row" style="margin-top:12px"><span class="badge badge--ok">${icon('lock', 11)}仅本机</span>
      <span class="badge badge--neutral">无账号体系</span><span class="badge badge--neutral">无外部请求</span></div>`,
  });

  return pageHead('帮助与说明', '口径、引导与自助处理 · 与产品实际行为保持一致',
    `<button class="btn btn--outline" data-act="toast" data-msg="已复制本页链接（本机）">${icon('file', 15)}复制链接</button>`) +
    `<div class="grid g-12"><div class="c-3">${toc}</div>
      <div class="c-9 stack"><div id="h-1">${caliber}</div><div id="h-2">${steps}</div>
      <div id="h-3">${backup}</div><div id="h-4">${trouble}</div><div id="h-5">${privacy}</div></div></div>`;
}

/* ---------------- 14. 设计系统 ---------------- */
const TOKENS = [
  ['--primary', '#D03F6B', '#2D7AB2', '品牌主色：主按钮、选中态、关键数据'],
  ['--primary-hover', '#BC355F', '#256BA1', '悬停态'],
  ['--primary-active', '#A52C52', '#1D5C8C', '按下态'],
  ['--primary-ink', '#A62F55', '#1D5F92', '浅底上的品牌色文字（正文级）'],
  ['--primary-soft', '#FCE8EE', '#E2EFF9', '标签底、选中底'],
  ['--primary-softer', '#FEF3F6', '#F0F8FD', '页面高亮、行选中底'],
  ['--primary-line', '#F5C8D5', '#BFDCF0', '品牌描边、进度轨道'],
  ['--accent', '#E0913F', '#3FAE97', '辅助色：第二数据序列、渐变端点'],
  ['--violet', '#8D7AD4', '#7A8FD6', '第三强调色：强调徽标'],
  ['--text-1', '#3A2930', '#1C2C38', '标题与关键数字'],
  ['--text-2', '#6B5159', '#4A6272', '正文、表格内容'],
  ['--text-3', '#806670', '#607684', '说明文字、表头'],
  ['--text-4', '#B09AA3', '#9DB3C1', '占位符、禁用'],
  ['--bg', '#FDF5F7', '#F4FAFD', '页面背景'],
  ['--surface', '#FFFFFF', '#FFFFFF', '卡片、弹窗表面'],
  ['--surface-2', '#FFFAFB', '#F9FCFE', '次级表面：表头、底栏'],
  ['--surface-3', '#FDF1F5', '#EEF6FB', '凹陷表面：输入底、轨道'],
  ['--border', '#F3E1E6', '#DFEAF2', '分隔线、卡片描边'],
  ['--border-2', '#E8CDD6', '#C8DBE8', '控件描边'],
  ['--ok', '#17795A', '#17795B', '成功 / 已入库 / 有利变化'],
  ['--warn', '#8A600C', '#8A600C', '警示 / 待确认 / 待清理'],
  ['--danger', '#BC3A2E', '#BC3A2E', '危险 / 失败 / 删除'],
  ['--fin-up', '#C63C33', '#C63C33', '财务不利（支出上升、结余下降）'],
  ['--fin-down', '#17795B', '#17795B', '财务有利（支出下降、结余上升）'],
];

function lum(hex) {
  const c = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => parseInt(c.substr(i, 2), 16) / 255)
    .map((x) => (x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
function cr(a, b) {
  const l1 = Math.max(lum(a), lum(b)), l2 = Math.min(lum(a), lum(b));
  return (l1 + 0.05) / (l2 + 0.05);
}
const crBadge = (r) => `<span class="cr ${r >= 4.5 ? 'cr--ok' : r >= 3 ? 'cr--warn' : ''}">${r.toFixed(1)}:1</span>`;

function pageDS() {
  const t = TOKENS;

  const previews = `<div class="ds-grid-2">
    ${[['pink', '玫瑰粉 · 少女感', '温柔、轻盈，灰玫瑰压住甜度'],
      ['sky', '天青蓝 · 自然清新', '透气、克制，冷青中性色']].map(([k, name, desc]) => `
      <div class="tp" data-theme="${k}">
        <div class="tp__bar"><i class="tp__sw"></i><b>${name}</b>
          <span class="tiny" style="color:var(--text-3);margin-left:6px">${desc}</span>
          <span class="badge badge--info badge--plain">${k === state.theme ? '当前' : '预览'}</span></div>
        <div class="tp__body">
          <div class="tp__kpi">
            <span>本期结余</span>
            <b>¥513.50</b><span class="delta delta--red" style="display:inline-flex">▼5.2%</span>
          </div>
          <div class="tp__chips">
            <span class="badge badge--ok">已入库</span>
            <span class="badge badge--warn">待确认</span>
            <span class="badge badge--info">已修正</span>
            <span class="badge badge--neutral">中性</span>
          </div>
          <div class="tp__bars">
            ${[42, 68, 55, 88, 62, 76, 48, 92].map((h) => `<i style="height:${h}%"></i>`).join('')}
          </div>
          <div class="row">
            <button class="btn btn--primary btn--sm">主按钮</button>
            <button class="btn btn--outline btn--sm">次按钮</button>
            <button class="btn btn--ghost btn--sm">文字</button>
          </div>
        </div>
      </div>`).join('')}
  </div>`;

  const swatches = `<div class="swatch-grid">
    ${[['brand', '--primary', '品牌主色'], ['brand-soft', '--primary-soft', '品牌浅底'],
      ['accent', '--accent', '辅助色'], ['violet', '--violet', '第三强调'],
      ['text', '--text-1', '主文字'], ['text-2', '--text-2', '次文字'],
      ['bg', '--bg', '页面背景'], ['surface', '--surface', '表面'],
      ['surface-3', '--surface-3', '凹陷表面'], ['border', '--border', '分隔线'],
      ['ok', '--ok', '成功'], ['warn', '--warn', '警示'],
      ['danger', '--danger', '危险'], ['fin-up', '--fin-up', '财务不利'],
      ['fin-down', '--fin-down', '财务有利']].map(([n, v, use]) => `
      <div class="swatch">
        <div class="swatch__chip" style="background:var(${v})"></div>
        <div class="swatch__meta"><b>${use}</b><code>${v}</code></div>
      </div>`).join('')}
  </div>`;

  const tokenTable = `<div class="table-wrap"><table class="token-table">
    <thead><tr><th>语义变量</th><th>玫瑰粉</th><th>天青蓝</th><th>色值（粉 / 蓝）</th><th>用途</th></tr></thead>
    <tbody>${t.map(([name, pink, sky, use]) => `<tr>
      <td><code>${name}</code></td>
      <td class="cell-sw"><i style="background:${pink}"></i></td>
      <td class="cell-sw"><i style="background:${sky}"></i></td>
      <td class="hex">${pink} / ${sky}</td>
      <td>${use}</td>
    </tr>`).join('')}</tbody>
  </table></div>`;

  const contrast = `<div class="table-wrap"><table class="token-table">
    <thead><tr><th>对比组合</th><th>玫瑰粉</th><th>天青蓝</th><th>结论</th></tr></thead>
    <tbody>
      ${[['正文 --text-1 / 页面 --bg', '#3A2930', '#1C2C38', '#FDF5F7', '#F4FAFD'],
        ['次文字 --text-2 / 表面 --surface', '#6B5159', '#4A6272', '#FFFFFF', '#FFFFFF'],
        ['--text-3 / --surface（辅助文字 12px）', '#806670', '#607684', '#FFFFFF', '#FFFFFF'],
        ['品牌文字 --primary-ink / --primary-softer', '#AB3557', '#1D6398', '#FEF3F6', '#F0F8FD'],
        ['白字 --on-primary / --primary', '#FFFFFF', '#FFFFFF', '#D03F6B', '#2D7AB2'],
        ['--danger / --danger-soft', '#BC3A2E', '#BC3A2E', '#FCEBE9', '#FBEAE7']].map(([label, p1, p2, b1, b2]) => {
          const r1 = cr(p1, b1), r2 = cr(p2, b2);
          const ok = r1 >= 4.5 && r2 >= 4.5;
          return `<tr><td>${label}</td><td>${crBadge(r1)}</td><td>${crBadge(r2)}</td>
            <td class="tiny ${ok ? '' : 'muted'}">${ok ? 'AA 正文达标' : '仅用于 ≥18px 大字/图形（AA Large 3:1）'}</td></tr>`;
        }).join('')}
    </tbody>
  </table></div>`;

  const typeScale = [
    ['--t-5xl', '42px', '结余主数字', 'var(--font-num)', '500'],
    ['--t-3xl', '28px', '页面主标题', 'var(--font-ui)', '600'],
    ['--t-2xl', '23px', '卡片群标题', 'var(--font-ui)', '600'],
    ['--t-xl', '19px', '弹窗标题', 'var(--font-ui)', '600'],
    ['--t-lg', '16px', '分区标题', 'var(--font-ui)', '600'],
    ['--t-md', '14px', '正文 / 表格', 'var(--font-ui)', '400'],
    ['--t-sm', '13px', '表格次要列', 'var(--font-ui)', '400'],
    ['--t-xs', '12px', '说明 / 标签', 'var(--font-ui)', '400'],
    ['--t-2xs', '11px', '表头 / 徽标', 'var(--font-ui)', '500'],
  ];

  const buttons = `<div class="demo-block">
    <div class="demo-block__label">按钮 · 变体</div>
    <div class="gallery">
      <button class="btn btn--primary">主操作</button>
      <button class="btn btn--outline">次操作</button>
      <button class="btn btn--soft">柔和</button>
      <button class="btn btn--ghost">文字按钮</button>
      <button class="btn btn--danger">危险操作</button>
      <button class="btn btn--primary btn--sm">小号</button>
      <button class="btn btn--primary btn--lg">大号</button>
    </div>
    <div class="demo-block__label" style="margin-top:16px">按钮 · 状态</div>
    <div class="gallery">
      <button class="btn btn--primary">默认</button>
      <button class="btn btn--primary" style="background:var(--primary-hover);box-shadow:var(--shadow-2);transform:translateY(-1px)">悬停</button>
      <button class="btn btn--primary" style="background:var(--primary-active)">按下</button>
      <button class="btn btn--primary" style="box-shadow:var(--ring)">聚焦</button>
      <button class="btn btn--primary" disabled>禁用</button>
      <button class="btn btn--primary btn--loading" style="min-width:96px">加载中</button>
    </div>
  </div>`;

  const forms = `<div class="demo-block">
    <div class="demo-block__label">输入 · 默认 / 聚焦 / 错误 / 只读</div>
    <div class="grid" style="grid-template-columns:repeat(4,1fr);gap:12px">
      <div class="field"><label class="field__label">搜索</label>
        <div class="input-group"><span class="input-group__icon">${icon('search', 14)}</span>
          <input class="input" placeholder="对方 / 商品"></div></div>
      <div class="field"><label class="field__label">金额阈值</label>
        <input class="input input--num" value="200" style="box-shadow:var(--ring);border-color:var(--primary)"></div>
      <div class="field is-invalid"><label class="field__label">数据目录</label>
        <input class="input mono" value="\\\\NAS\\share" style="font-size:12px">
        <span class="field__error">${icon('alert', 11)} 不能指向网络位置</span></div>
      <div class="field"><label class="field__label">来源批次</label>
        <input class="input mono" value="B-20261021-1" readonly style="font-size:12px"></div>
    </div>
    <div class="demo-block__label" style="margin-top:16px">选择 · 开关 · 复选</div>
    <div class="gallery">
      <div class="select" style="width:160px"><select class="select__native"><option>支出 · 餐饮美食</option></select></div>
      <span class="switch" role="switch" aria-checked="true" data-act="toggle"></span>
      <span class="switch" role="switch" aria-checked="false" data-act="toggle"></span>
      <span class="switch" role="switch" aria-checked="true" style="opacity:.45"></span>
      <label class="checkbox"><input type="checkbox" checked><span class="checkbox__box"></span>已勾选</label>
      <label class="checkbox"><input type="checkbox"><span class="checkbox__box"></span>未勾选</label>
      <label class="radio"><input type="radio" name="r" checked><span class="radio__box"></span>保留历史</label>
      <label class="radio"><input type="radio" name="r"><span class="radio__box"></span>迁移</label>
    </div>
  </div>`;

  const badges = `<div class="demo-block">
    <div class="demo-block__label">徽标 · 业务状态映射</div>
    <div class="gallery">
      <span class="badge badge--ok">已入库 / 已分类</span>
      <span class="badge badge--info">待映射 / 已修正</span>
      <span class="badge badge--warn">待确认 / 待清理</span>
      <span class="badge badge--danger">失败</span>
      <span class="badge badge--neutral">已丢弃 / 中性</span>
      <span class="badge badge--plain badge--outline">中性描边</span>
    </div>
    <div class="demo-block__label" style="margin-top:16px">筛选 chip · 涨跌标记</div>
    <div class="gallery">
      <button class="chip" aria-pressed="true">餐饮美食 <span class="chip__x">×</span></button>
      <button class="chip">全部状态</button>
      <span class="delta delta--red">▲8.3%</span>
      <span class="delta delta--green">▼2.4%</span>
      <span class="delta delta--flat">—</span>
    </div>
  </div>`;

  const states = `<div class="table-wrap"><table class="spec-table">
    <thead><tr><th>交互状态</th><th>视觉规则</th><th>变量</th><th>约束</th></tr></thead>
    <tbody>
      <tr><td>默认</td><td>品牌实底 + 内高光 1px</td><td><code>--primary</code></td><td>每屏主按钮 ≤ 1 个</td></tr>
      <tr><td>悬停</td><td>加深 6%，上浮 1px，阴影升一级</td><td><code>--primary-hover</code> + <code>--shadow-2</code></td><td>仅指针设备</td></tr>
      <tr><td>按下</td><td>再加深 8%，位移归零，阴影去除</td><td><code>--primary-active</code></td><td>即时反馈 ≤ 110ms</td></tr>
      <tr><td>聚焦</td><td>外发光环 3px，偏移 2px</td><td><code>--ring</code></td><td>键盘可见，鼠标点击不触发</td></tr>
      <tr><td>禁用</td><td>整体 46% 不透明，禁用指针</td><td>opacity .46</td><td>保留尺寸，不位移</td></tr>
      <tr><td>加载</td><td>文字透明，中心 14px 旋转环</td><td>—</td><td>按钮宽度锁定，避免抖动</td></tr>
      <tr><td>选中</td><td>浅色底 + 品牌描边 + 品牌字</td><td><code>--primary-soft/line/ink</code></td><td>与聚焦态可叠加</td></tr>
      <tr><td>只读</td><td>凹陷底 + 次文字，去掉描边强调</td><td><code>--surface-3</code></td><td>不显示 hover</td></tr>
    </tbody>
  </table></div>`;

  const bizMap = `<div class="table-wrap"><table class="spec-table">
    <thead><tr><th>业务状态</th><th>语义色</th><th>组件</th><th>出现位置</th></tr></thead>
    <tbody>
      <tr><td>已上传 / 已丢弃</td><td><code>--text-3</code>（中性灰）</td><td>badge--neutral</td><td>缓冲区列表</td></tr>
      <tr><td>待映射 / 入库中</td><td><code>--primary</code>（品牌）</td><td>badge--info</td><td>导入向导、缓冲区</td></tr>
      <tr><td>待确认（批次）</td><td><code>--warn</code></td><td>badge--warn</td><td>缓冲区、预检表</td></tr>
      <tr><td>已入库</td><td><code>--ok</code></td><td>badge--ok</td><td>报告、原始库</td></tr>
      <tr><td>失败（仅解析失败）</td><td><code>--danger</code></td><td>badge--danger</td><td>缓冲区</td></tr>
      <tr><td>文件待清理</td><td><code>--warn</code> + 重试按钮</td><td>notice--warn</td><td>缓冲区待清理区</td></tr>
      <tr><td>已修正（corrected）</td><td><code>--primary-ink</code></td><td>badge--info</td><td>明细、待确认队列</td></tr>
      <tr><td>已排除（excluded）</td><td><code>--text-3</code> + 删除线金额</td><td>badge--neutral</td><td>明细（仅状态筛选可见）</td></tr>
      <tr><td>支出上升 / 结余下降</td><td><code>--fin-up</code> 红</td><td>delta--red</td><td>KPI、报表、分类分析</td></tr>
      <tr><td>支出下降 / 结余上升</td><td><code>--fin-down</code> 绿</td><td>delta--green</td><td>同上</td></tr>
    </tbody>
  </table></div>`;

  const chartColors = `<div class="gallery">
    ${[1, 2, 3, 4, 5, 6, 7, 8].map((i) => `<div style="text-align:center">
      <div style="width:56px;height:56px;border-radius:14px;background:var(--chart-${i});box-shadow:var(--shadow-1)"></div>
      <div class="tiny muted" style="margin-top:6px">chart-${i}</div></div>`).join('')}
  </div>
  <p class="small muted" style="margin-top:12px">色序固定：chart-1 = 最大支出分类（餐饮），chart-8 保留给「未分类」；两套主题色序语义一一对应，切换主题不改变「哪个分类是什么颜色」的认知。</p>`;

  const a11y = `<ul class="stack" style="gap:8px">
    ${[['正文对比度', '--text-1/--text-2 在页面与卡片底上均 ≥ 4.5:1；--text-3 用于 12px 辅助信息，必要时改用 --text-2'],
      ['大字对比度', '--primary 用于 ≥18px 粗体或图形元素，满足 3:1；正文级品牌文字一律使用 --primary-ink'],
      ['焦点可见', '所有可交互元素 :focus-visible 显示 2px 品牌描边 + 2px 偏移；不使用 outline: none'],
      ['触控尺寸', '按钮最小 30px 高，主要操作 36–42px；图标按钮 34×34；移动端行高不小于 44px'],
      ['语义结构', '表头使用 th、状态使用文字而非仅颜色、图表提供 aria-label 与数值 tooltip'],
      ['动态偏好', 'prefers-reduced-motion 下动画降到 0.01ms，保留最终态'],
      ['文案可读', '错误信息说明「哪里错、怎么改」，不用「操作失败」这类无信息文案']]
      .map(([k, v]) => `<li class="row" style="align-items:flex-start;gap:10px">
        <span style="color:var(--ok);margin-top:2px">${icon('checkCircle', 14)}</span>
        <span class="small"><b>${k}</b>：<span class="muted">${v}</span></span></li>`).join('')}
  </ul>`;

  const sections = `
    <section class="ds-section">
      <div class="ds-head"><h2>两套主题</h2><p>同一套语义变量，仅替换取值；布局、间距、组件结构完全一致</p></div>
      ${previews}
      <div class="notice notice--info" style="margin-top:16px">
        <span class="notice__icon">${icon('palette', 15)}</span>
        <div><b>主题映射规则</b>：主题只覆盖「语义层」的 24 个变量，组件层不允许出现硬编码色值。切换主题时仅背景色与文字色做 480ms 过渡，其余元素即时切换，避免大面积重绘造成的闪烁。</div>
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>色彩系统</h2><p>当前主题实时取值 · 中性色均带品牌色温，不使用纯黑纯白做背景</p></div>
      ${swatches}
      <div style="margin-top:20px">
        <div class="section-label" style="margin-bottom:10px">语义变量对照表</div>
        ${tokenTable}
      </div>
      <div style="margin-top:20px">
        <div class="section-label" style="margin-bottom:10px">对比度实测</div>
        ${contrast}
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>字体与排版</h2><p>正文用系统中文黑体，数字用 Bahnschrift/DIN 等宽字形，避免金额跳动</p></div>
      <div class="ds-grid-2">
        <div class="card"><div class="card__body" style="padding:8px 20px 16px">
          ${typeScale.map(([v, size, use, fam, w]) => `<div class="type-row">
            <span class="type-row__sample" style="font-family:${fam};font-weight:${w};font-size:${size};letter-spacing:${size.includes('4') ? '-.03em' : '-.01em'}">餐饮美食 1,486.50</span>
            <span class="type-row__meta">${size} · ${w} · ${v.replace('--', '')}</span></div>`).join('')}
        </div></div>
        <div class="stack">
          <div class="card"><div class="card__body">
            <div class="section-label" style="margin-bottom:12px">间距刻度（4px 基准）</div>
            <div class="spacing-demo">
              ${[4, 6, 8, 12, 16, 20, 24, 32, 40, 48].map((n) => `<div style="flex:1"><i style="height:${n * 1.4}px"></i>${n}</div>`).join('')}
            </div>
            <p class="tiny muted" style="margin-top:10px">卡片内边距 20/24，区块间距 16/24，页面左右留白 28；不使用 10 以下的奇数间距。</p>
          </div></div>
          <div class="card"><div class="card__body">
            <div class="section-label" style="margin-bottom:12px">圆角与阴影</div>
            <div class="radius-demo">
              ${[['6', '--r-xs'], ['9', '--r-sm'], ['12', '--r-md'], ['16', '--r-lg'], ['20', '--r-xl'], ['26', '--r-2xl'], ['∞', '--r-pill']].map(([n, v]) => `
                <div><i style="border-radius:${v === '--r-pill' ? '999px' : n + 'px'};height:${v === '--r-pill' ? 26 : 56}px"></i><span>${n}</span></div>`).join('')}
            </div>
            <div class="gallery" style="margin-top:16px">
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-1)"></div>
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-2)"></div>
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-3)"></div>
            </div>
            <p class="tiny muted" style="margin-top:10px">阴影带品牌色温（粉：暖褐 / 蓝：冷青），不用纯黑投影。</p>
          </div></div>
        </div>
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>组件与状态</h2><p>按钮、表单、徽标全部状态可交互查看</p></div>
      <div class="ds-grid-2">${buttons}${forms}</div>
      <div style="margin-top:16px">${badges}</div>
      <div style="margin-top:20px">
        <div class="section-label" style="margin-bottom:10px">交互状态规则</div>
        ${states}
      </div>
      <div style="margin-top:20px">
        <div class="section-label" style="margin-bottom:10px">业务状态 → 语义映射</div>
        ${bizMap}
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>图表色序</h2><p>两套主题共用语义顺序，保证切换后分类识别不漂移</p></div>
      ${chartColors}
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>空态 / 骨架 / 提示</h2><p>数据未就绪、无结果、异常三种态都有明确出口</p></div>
      <div class="ds-grid-2">
        <div class="card"><div class="empty">
          <div class="empty__art">${icon('db', 30)}</div>
          <div class="empty__title">还没有导入任何账单</div>
          <div class="empty__desc">导出微信 / 支付宝的账单文件，拖进导入页就能看到第一份月报。数据只留在本机。</div>
          <div class="empty__actions"><button class="btn btn--primary" data-go="import">导入第一份账单</button>
            <button class="btn btn--ghost" data-go="help">看看怎么导出</button></div>
        </div></div>
        <div class="card"><div class="card__body">
          <div class="section-label" style="margin-bottom:12px">骨架屏</div>
          <div class="stack" style="gap:10px">
            <div class="skeleton" style="height:14px;width:38%"></div>
            <div class="skeleton" style="height:34px;width:62%"></div>
            <div class="skeleton" style="height:10px;width:100%"></div>
            <div class="skeleton" style="height:10px;width:86%"></div>
            <div class="skeleton" style="height:120px;width:100%;border-radius:12px"></div>
          </div>
          <div class="section-label" style="margin:18px 0 10px">提示条</div>
          <div class="stack" style="gap:8px">
            <div class="notice notice--info"><span class="notice__icon">${icon('info', 14)}</span><div>预检只读，不会写库。</div></div>
            <div class="notice notice--warn"><span class="notice__icon">${icon('alert', 14)}</span><div>有 4 笔待确认计入总支出。</div></div>
            <div class="notice notice--danger"><span class="notice__icon">${icon('alert', 14)}</span><div>事务失败已整体回滚，批次回到待确认。</div></div>
          </div>
          <div class="row" style="margin-top:16px">
            <button class="btn btn--outline btn--sm" data-act="modal-demo">打开弹窗</button>
            <button class="btn btn--outline btn--sm" data-act="toast" data-msg="这是一条操作反馈">触发轻提示</button>
            <button class="btn btn--outline btn--sm" data-act="drawer-demo">打开抽屉</button>
          </div>
        </div></div>
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>无障碍清单</h2><p>WCAG AA 基线，交付前逐条自检</p></div>
      <div class="card"><div class="card__body">${a11y}</div></div>
    </section>`;

  return pageHead('设计规范', '语义变量 · 双主题映射 · 组件状态矩阵 · 无障碍基线',
    `<div class="theme-switch">
      <button class="theme-switch__item" data-theme-set="pink" aria-pressed="${state.theme === 'pink'}"><i></i>玫瑰粉</button>
      <button class="theme-switch__item" data-theme-set="sky" aria-pressed="${state.theme === 'sky'}"><i></i>天青蓝</button>
    </div>`) + sections;
}
