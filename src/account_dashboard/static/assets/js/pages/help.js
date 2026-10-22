/* 帮助与说明：纯静态页（FR-23 明确不设 API）。
   内容与产品实际行为一致：口径、导入、备份、异常自助、隐私。 */

import { card, pageHead } from '../core/ui.js';
import { icon } from '../core/icons.js';

export async function render() {
  const toc = `<section class="card"><div class="card__body" style="padding:12px">
    <div class="help-toc">
      <button class="help-toc__item is-active" data-act="anchor" data-id="h-1">收支口径说明</button>
      <button class="help-toc__item" data-act="anchor" data-id="h-2">导入流程引导</button>
      <button class="help-toc__item" data-act="anchor" data-id="h-3">备份指引</button>
      <button class="help-toc__item" data-act="anchor" data-id="h-4">异常自助处理</button>
      <button class="help-toc__item" data-act="anchor" data-id="h-5">隐私与部署</button>
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
      <li><b>映射与预检</b>：时间 / 金额 / 方向三个核心字段通常会自动命中；预检会逐条标注新增/重复，误判可「强制新增」。</li>
      <li><b>确认入库</b>：事务写入按月分表 + 主数据层，成功后自动删除缓冲区原文件。</li>
    </ol></div>`,
  });

  const backup = card({
    title: '备份指引',
    sub: '本周备份了吗',
    body: `<div class="help-prose">
      <p>备份会在 <code class="mono">backups/</code> 生成一个完整的数据库文件，恢复时整体覆盖。也可以在备份页导出 JSON / CSV 作为第二通道。</p>
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
    `<button class="btn btn--outline" data-act="copy">${icon('file', 15)}复制本页地址</button>`)
    + `<div class="grid g-12"><div class="c-3">${toc}</div>
      <div class="c-9 stack"><div id="h-1">${caliber}</div><div id="h-2">${steps}</div>
      <div id="h-3">${backup}</div><div id="h-4">${trouble}</div><div id="h-5">${privacy}</div></div></div>`;
}

export const actions = {
  anchor: (data) => {
    document.getElementById(data.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.querySelectorAll('.help-toc__item').forEach((b) => b.classList.toggle('is-active', b.dataset.id === data.id));
  },
  copy: async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      const { toast } = await import('../core/ui.js');
      toast('已复制本页地址（仅本机可访问）', 'ok');
    } catch {
      const { toast } = await import('../core/ui.js');
      toast('浏览器拒绝了剪贴板写入，可手动复制地址栏', 'warn');
    }
  },
};
