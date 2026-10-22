/* 设计规范：语义变量、双主题、组件状态矩阵、业务状态映射、无障碍清单。
   本页是开发与验收的唯一视觉参照。 */

import { pageHead } from '../core/ui.js';
import { icon } from '../core/icons.js';
import { state } from '../core/store.js';

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

export async function render() {
  const previews = `<div class="ds-grid-2">
    ${[['pink', '玫瑰粉 · 少女感', '温柔、轻盈，灰玫瑰压住甜度'],
      ['sky', '天青蓝 · 自然清新', '透气、克制，冷青中性色']].map(([k, name, desc]) => `
      <div class="tp" data-theme="${k}">
        <div class="tp__bar"><i class="tp__sw"></i><b>${name}</b>
          <span class="tiny" style="color:var(--text-3);margin-left:6px">${desc}</span>
          <span class="badge badge--info badge--plain">${k === state.theme ? '当前' : '预览'}</span></div>
        <div class="tp__body">
          <div class="tp__kpi"><span>本期结余</span><b>¥513.50</b><span class="delta delta--red" style="display:inline-flex">▼5.2%</span></div>
          <div class="tp__chips">
            <span class="badge badge--ok">已入库</span><span class="badge badge--warn">待确认</span>
            <span class="badge badge--info">已修正</span><span class="badge badge--neutral">中性</span>
          </div>
          <div class="tp__bars">${[42, 68, 55, 88, 62, 76, 48, 92].map((h) => `<i style="height:${h}%"></i>`).join('')}</div>
          <div class="row"><button class="btn btn--primary btn--sm">主按钮</button><button class="btn btn--outline btn--sm">次按钮</button><button class="btn btn--ghost btn--sm">文字</button></div>
        </div>
      </div>`).join('')}
  </div>`;

  const swatches = `<div class="swatch-grid">
    ${[['--primary', '品牌主色'], ['--primary-soft', '品牌浅底'], ['--accent', '辅助色'], ['--violet', '第三强调'],
      ['--text-1', '主文字'], ['--text-2', '次文字'], ['--bg', '页面背景'], ['--surface', '表面'],
      ['--surface-3', '凹陷表面'], ['--border', '分隔线'], ['--ok', '成功'], ['--warn', '警示'],
      ['--danger', '危险'], ['--fin-up', '财务不利'], ['--fin-down', '财务有利']].map(([v, use]) => `
      <div class="swatch"><div class="swatch__chip" style="background:var(${v})"></div>
        <div class="swatch__meta"><b>${use}</b><code>${v}</code></div></div>`).join('')}
  </div>`;

  const tokenTable = `<div class="table-wrap"><table class="token-table">
    <thead><tr><th>语义变量</th><th>玫瑰粉</th><th>天青蓝</th><th>色值（粉 / 蓝）</th><th>用途</th></tr></thead>
    <tbody>${TOKENS.map(([name, pink, sky, use]) => `<tr>
      <td><code>${name}</code></td>
      <td class="cell-sw"><i style="background:${pink}"></i></td>
      <td class="cell-sw"><i style="background:${sky}"></i></td>
      <td class="hex">${pink} / ${sky}</td><td>${use}</td></tr>`).join('')}</tbody>
  </table></div>`;

  const contrast = `<div class="table-wrap"><table class="token-table">
    <thead><tr><th>对比组合</th><th>玫瑰粉</th><th>天青蓝</th><th>结论</th></tr></thead>
    <tbody>${[
      ['正文 --text-1 / 页面 --bg', '#3A2930', '#1C2C38', '#FDF5F7', '#F4FAFD'],
      ['次文字 --text-2 / 表面 --surface', '#6B5159', '#4A6272', '#FFFFFF', '#FFFFFF'],
      ['--text-3 / --surface（12px 辅助）', '#806670', '#607684', '#FFFFFF', '#FFFFFF'],
      ['品牌文字 --primary-ink / --primary-softer', '#A62F55', '#1D5F92', '#FEF3F6', '#F0F8FD'],
      ['白字 --on-primary / --primary', '#FFFFFF', '#FFFFFF', '#D03F6B', '#2D7AB2'],
      ['--danger / --danger-soft', '#BC3A2E', '#BC3A2E', '#FCEBE9', '#FCEBE9'],
    ].map(([label, p1, p2, b1, b2]) => {
      const r1 = cr(p1, b1), r2 = cr(p2, b2);
      const ok = r1 >= 4.5 && r2 >= 4.5;
      return `<tr><td>${label}</td><td>${crBadge(r1)}</td><td>${crBadge(r2)}</td>
        <td class="tiny ${ok ? '' : 'muted'}">${ok ? 'AA 正文达标' : '仅用于 ≥18px 大字/图形（AA Large 3:1）'}</td></tr>`;
    }).join('')}</tbody>
  </table></div>`;

  const typeScale = [
    ['42px', '结余主数字', 'var(--font-num)', '500'],
    ['28px', '页面主标题', 'var(--font-ui)', '600'],
    ['23px', '卡片群标题', 'var(--font-ui)', '600'],
    ['19px', '弹窗标题', 'var(--font-ui)', '600'],
    ['16px', '分区标题', 'var(--font-ui)', '600'],
    ['14px', '正文 / 表格', 'var(--font-ui)', '400'],
    ['13px', '表格次要列', 'var(--font-ui)', '400'],
    ['12px', '说明 / 标签', 'var(--font-ui)', '400'],
    ['11px', '表头 / 徽标', 'var(--font-ui)', '500'],
  ];

  const states = `<div class="table-wrap"><table class="spec-table">
    <thead><tr><th>交互状态</th><th>视觉规则</th><th>变量</th><th>约束</th></tr></thead>
    <tbody>
      <tr><td>默认</td><td>品牌实底 + 内高光 1px</td><td><code>--primary</code></td><td>每屏主按钮 ≤ 1 个</td></tr>
      <tr><td>悬停</td><td>加深 8%，上浮 1px，阴影升一级</td><td><code>--primary-hover</code></td><td>仅指针设备</td></tr>
      <tr><td>按下</td><td>再加深 8%，位移归零，阴影去除</td><td><code>--primary-active</code></td><td>反馈 ≤ 110ms</td></tr>
      <tr><td>聚焦</td><td>外发光环 3px，偏移 2px</td><td><code>--ring</code></td><td>键盘可见，鼠标不触发</td></tr>
      <tr><td>禁用</td><td>整体 46% 不透明，禁用指针</td><td>opacity .46</td><td>保留尺寸，不位移</td></tr>
      <tr><td>加载</td><td>文字透明，中心 14px 旋转环</td><td>—</td><td>按钮宽度锁定，避免抖动</td></tr>
      <tr><td>选中</td><td>浅色底 + 品牌描边 + 品牌字</td><td><code>--primary-soft</code></td><td>可与聚焦态叠加</td></tr>
      <tr><td>只读</td><td>凹陷底 + 次文字，去掉描边强调</td><td><code>--surface-3</code></td><td>不显示 hover</td></tr>
    </tbody>
  </table></div>`;

  const bizMap = `<div class="table-wrap"><table class="spec-table">
    <thead><tr><th>业务状态</th><th>语义色</th><th>组件</th><th>出现位置</th></tr></thead>
    <tbody>
      <tr><td>已上传 / 已丢弃</td><td><code>--text-3</code>（中性灰）</td><td>badge--neutral</td><td>缓冲区列表</td></tr>
      <tr><td>待映射 / 入库中</td><td><code>--primary</code>（品牌）</td><td>badge--info</td><td>导入向导、缓冲区</td></tr>
      <tr><td>待确认（批次 / 流水）</td><td><code>--warn</code></td><td>badge--warn</td><td>缓冲区、预检、明细</td></tr>
      <tr><td>已入库</td><td><code>--ok</code></td><td>badge--ok</td><td>报告、原始库</td></tr>
      <tr><td>解析失败</td><td><code>--danger</code></td><td>badge--danger</td><td>缓冲区</td></tr>
      <tr><td>文件待清理</td><td><code>--warn</code> + 重试按钮</td><td>notice--warn</td><td>缓冲区待清理区</td></tr>
      <tr><td>已修正（corrected）</td><td><code>--primary-ink</code></td><td>badge--info</td><td>明细、待确认队列</td></tr>
      <tr><td>已排除（excluded）</td><td><code>--text-3</code> + 金额降权</td><td>badge--neutral</td><td>明细（状态筛选可见）</td></tr>
      <tr><td>支出上升 / 结余下降</td><td><code>--fin-up</code> 红</td><td>delta--red</td><td>KPI、报表、分类分析</td></tr>
      <tr><td>支出下降 / 结余上升</td><td><code>--fin-down</code> 绿</td><td>delta--green</td><td>同上</td></tr>
    </tbody>
  </table></div>`;

  const a11y = `<ul class="stack" style="gap:8px">
    ${[['正文对比度', '--text-1 / --text-2 在页面与卡片底上均 ≥ 4.5:1；--text-3 仅用于 12px 辅助信息'],
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
        <div><b>主题映射规则</b>：主题只覆盖「语义层」的 24 个变量，组件层不允许出现硬编码色值。切换主题时仅背景与文字做 480ms 过渡，其余元素即时切换。</div>
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>色彩系统</h2><p>当前主题实时取值 · 中性色均带品牌色温</p></div>
      ${swatches}
      <div style="margin-top:20px"><div class="section-label" style="margin-bottom:10px">语义变量对照表</div>${tokenTable}</div>
      <div style="margin-top:20px"><div class="section-label" style="margin-bottom:10px">对比度实测</div>${contrast}</div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>字体与排版</h2><p>正文用系统中文黑体，数字用 Bahnschrift/DIN 等宽字形，避免金额跳动</p></div>
      <div class="ds-grid-2">
        <div class="card"><div class="card__body" style="padding:8px 20px 16px">
          ${typeScale.map(([size, use, fam, w]) => `<div class="type-row">
            <span class="type-row__sample" style="font-family:${fam};font-weight:${w};font-size:${size};letter-spacing:-.02em">餐饮美食 1,486.50</span>
            <span class="type-row__meta">${size} · ${w} · ${use}</span></div>`).join('')}
        </div></div>
        <div class="stack">
          <div class="card"><div class="card__body">
            <div class="section-label" style="margin-bottom:12px">间距刻度（4px 基准）</div>
            <div class="spacing-demo">${[4, 6, 8, 12, 16, 20, 24, 32, 40, 48].map((n) => `<div style="flex:1"><i style="height:${n * 1.4}px"></i>${n}</div>`).join('')}</div>
            <p class="tiny muted" style="margin-top:10px">卡片内边距 20/24，区块间距 16/24，页面左右留白 28。</p>
          </div></div>
          <div class="card"><div class="card__body">
            <div class="section-label" style="margin-bottom:12px">圆角与阴影</div>
            <div class="radius-demo">${[['6', 6], ['9', 9], ['12', 12], ['16', 16], ['20', 20], ['26', 26], ['∞', 999]].map(([n, v]) => `<div><i style="border-radius:${v}px;height:${v === 999 ? 26 : 56}px"></i><span>${n}</span></div>`).join('')}</div>
            <div class="gallery" style="margin-top:16px">
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-1)"></div>
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-2)"></div>
              <div style="width:64px;height:44px;border-radius:12px;background:var(--surface);box-shadow:var(--shadow-3)"></div>
            </div>
          </div></div>
        </div>
      </div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>组件与状态</h2><p>按钮、表单、徽标全部状态可交互查看</p></div>
      <div class="ds-grid-2">
        <div class="demo-block"><div class="demo-block__label">按钮 · 变体</div>
          <div class="gallery"><button class="btn btn--primary">主操作</button><button class="btn btn--outline">次操作</button>
            <button class="btn btn--soft">柔和</button><button class="btn btn--ghost">文字按钮</button>
            <button class="btn btn--danger">危险操作</button><button class="btn btn--primary btn--sm">小号</button>
            <button class="btn btn--primary btn--lg">大号</button></div>
          <div class="demo-block__label" style="margin-top:16px">按钮 · 状态</div>
          <div class="gallery"><button class="btn btn--primary">默认</button>
            <button class="btn btn--primary" style="background:var(--primary-hover);box-shadow:var(--shadow-2);transform:translateY(-1px)">悬停</button>
            <button class="btn btn--primary" style="background:var(--primary-active)">按下</button>
            <button class="btn btn--primary" style="box-shadow:var(--ring)">聚焦</button>
            <button class="btn btn--primary" disabled>禁用</button>
            <button class="btn btn--primary btn--loading" style="min-width:96px">加载中</button></div>
        </div>
        <div class="demo-block"><div class="demo-block__label">输入 · 默认 / 聚焦 / 错误 / 只读</div>
          <div class="grid" style="grid-template-columns:repeat(2,1fr);gap:12px">
            <div class="field"><label class="field__label">搜索</label><div class="input-group"><span class="input-group__icon">${icon('search', 14)}</span><input class="input" placeholder="对方 / 商品"></div></div>
            <div class="field"><label class="field__label">金额阈值</label><input class="input input--num" value="200" style="box-shadow:var(--ring);border-color:var(--primary)"></div>
            <div class="field is-invalid"><label class="field__label">数据目录</label><input class="input mono" value="\\\\NAS\\share" style="font-size:12px"><span class="field__error">${icon('alert', 11)} 不能指向网络位置</span></div>
            <div class="field"><label class="field__label">来源批次</label><input class="input mono" value="B-20261021-1" readonly style="font-size:12px"></div>
          </div>
          <div class="demo-block__label" style="margin-top:16px">选择 · 开关 · 复选</div>
          <div class="gallery">
            <div class="select" style="width:150px"><select class="select__native"><option>支出 · 餐饮美食</option></select></div>
            <span class="switch" role="switch" aria-checked="true" data-act="toggle"></span>
            <span class="switch" role="switch" aria-checked="false" data-act="toggle"></span>
            <label class="checkbox"><input type="checkbox" checked><span class="checkbox__box"></span>已勾选</label>
            <label class="radio"><input type="radio" name="r" checked><span class="radio__box"></span>保留历史</label>
          </div>
        </div>
      </div>
      <div class="demo-block" style="margin-top:16px"><div class="demo-block__label">徽标 · 业务状态映射</div>
        <div class="gallery"><span class="badge badge--ok">已入库 / 已分类</span><span class="badge badge--info">待映射 / 已修正</span>
          <span class="badge badge--warn">待确认 / 待清理</span><span class="badge badge--danger">失败</span>
          <span class="badge badge--neutral">已丢弃 / 中性</span><span class="badge badge--plain badge--outline">中性描边</span></div>
        <div class="demo-block__label" style="margin-top:16px">涨跌标记 · 颜色由「是否有利」决定</div>
        <div class="gallery"><span class="delta delta--red">▲8.3%</span><span class="delta delta--green">▼2.4%</span><span class="delta delta--flat">—</span></div>
      </div>
      <div style="margin-top:20px"><div class="section-label" style="margin-bottom:10px">交互状态规则</div>${states}</div>
      <div style="margin-top:20px"><div class="section-label" style="margin-bottom:10px">业务状态 → 语义映射</div>${bizMap}</div>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>图表色序</h2><p>两套主题共用语义顺序，切换后分类识别不漂移</p></div>
      <div class="gallery">${[1, 2, 3, 4, 5, 6, 7, 8].map((i) => `<div style="text-align:center">
        <div style="width:56px;height:56px;border-radius:14px;background:var(--chart-${i});box-shadow:var(--shadow-1)"></div>
        <div class="tiny muted" style="margin-top:6px">chart-${i}</div></div>`).join('')}</div>
      <p class="small muted" style="margin-top:12px">色序固定：chart-1 = 最大支出分类，chart-8 保留给「未分类 / 其他」；两套主题语义一一对应。</p>
    </section>

    <section class="ds-section">
      <div class="ds-head"><h2>空态 / 骨架 / 提示</h2><p>数据未就绪、无结果、异常三种态都有明确出口</p></div>
      <div class="ds-grid-2">
        <div class="card"><div class="empty">
          <div class="empty__art">${icon('db', 30)}</div>
          <div class="empty__title">还没有导入任何账单</div>
          <div class="empty__desc">导出微信 / 支付宝的账单文件，拖进导入页就能看到第一份月报。数据只留在本机。</div>
          <div class="empty__actions"><button class="btn btn--primary" data-go="import">导入第一份账单</button><button class="btn btn--ghost" data-go="help">看看怎么导出</button></div>
        </div></div>
        <div class="card"><div class="card__body">
          <div class="section-label" style="margin-bottom:12px">骨架屏</div>
          <div class="stack" style="gap:10px">
            <div class="skeleton" style="height:14px;width:38%"></div><div class="skeleton" style="height:34px;width:62%"></div>
            <div class="skeleton" style="height:10px;width:100%"></div><div class="skeleton" style="height:10px;width:86%"></div>
            <div class="skeleton" style="height:120px;width:100%;border-radius:12px"></div>
          </div>
          <div class="section-label" style="margin:18px 0 10px">提示条</div>
          <div class="stack" style="gap:8px">
            <div class="notice notice--info"><span class="notice__icon">${icon('info', 14)}</span><div>预检只读，不会写库。</div></div>
            <div class="notice notice--warn"><span class="notice__icon">${icon('alert', 14)}</span><div>有 4 笔待确认计入总支出。</div></div>
            <div class="notice notice--danger"><span class="notice__icon">${icon('alert', 14)}</span><div>事务失败已整体回滚，批次回到待确认。</div></div>
          </div>
          <div class="row" style="margin-top:16px">
            <button class="btn btn--outline btn--sm" data-act="demo-modal">打开弹窗</button>
            <button class="btn btn--outline btn--sm" data-act="demo-toast">触发轻提示</button>
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

export const actions = {
  'demo-modal': async () => {
    const { modal, closeLayer } = await import('../core/ui.js');
    modal({
      title: '标准弹窗',
      sub: '用于二次确认与轻表单，最大宽度 560px',
      body: '<p class="small muted" style="line-height:1.9">弹窗出现时背景模糊 3px，按 Esc 或点击遮罩关闭。破坏性操作会把主按钮换成 danger 变体。</p>',
      foot: '<button class="btn btn--ghost" data-act="close-layer">取消</button><button class="btn btn--primary" data-act="close-layer">知道了</button>',
    });
    document.querySelectorAll('#layer [data-act="close-layer"]').forEach((b) => b.addEventListener('click', () => closeLayer()));
  },
  'demo-toast': async () => {
    const { toast } = await import('../core/ui.js');
    toast('这是一条操作反馈', 'ok');
  },
};
