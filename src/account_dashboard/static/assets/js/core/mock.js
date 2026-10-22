/* 本地契约同构数据源（仅在前端演示/联调前使用）。
 *
 * 目标不是「假数据糊页面」，而是**按 SDD §6.2 的端点、DTO、错误码与金额/时间约定**
 * 提供一个可跑通全链路的后端替身：上传 → 映射 → 预检 → 入库 → 报表 → 重算 → 备份。
 * 后端 C2~C4 交付后，把数据源切到 live 即可，页面代码不需要改。
 *
 * 已知契约缺口（不擅自扩展契约，只做前端侧兜底）：
 *  - KpiDTO 未定义储蓄率/日均支出的环比字段 → 这里提供可选字段 savings_mom / daily_avg_*
 *    并在 UI 上缺失时显示「—」；
 *  - PreviewDTO / PendingGroupDTO / SettingsDTO 等 SDD 未展开 → 按 §6.2 的响应名与
 *    PRD 附录 B 推定字段，集中记录在 docs/frontend/前端实现说明.md。
 */

import { ApiError } from './api.js';

const STORAGE_KEY = 'fd-mock-v3';
const NOW = new Date();

let db = null;

/* ============================================================
   工具
   ============================================================ */
const pad = (n) => String(n).padStart(2, '0');
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
const dateIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const ymd = (d) => dateIso(d);
const monthKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;
const startOfMonth = (y, m) => new Date(y, m - 1, 1);
const daysInMonth = (y, m) => new Date(y, m, 0).getDate();
const addMonths = (d, n) => new Date(d.getFullYear(), d.getMonth() + n, 1);
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const clone = (v) => JSON.parse(JSON.stringify(v));
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const sleep = () => delay(90 + Math.random() * 130);

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (r, arr) => arr[Math.floor(r() * arr.length)];
const between = (r, min, max) => min + Math.floor(r() * (max - min + 1));
const wpick = (r, list) => {
  const total = list.reduce((s, x) => s + x.w, 0);
  let v = r() * total;
  for (const item of list) { v -= item.w; if (v <= 0) return item; }
  return list[list.length - 1];
};

function fpOf(time, cents, dir, cp, item) {
  const s = `${time}|${cents}|${dir}|${cp || ''}|${item || ''}`;
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0).toString(16).padStart(8, '0') + s.length.toString(16);
}

/* ============================================================
   种子：分类 / 规则 / 商户
   ============================================================ */
const CATEGORY_SEED = [
  ['收入', '家人资助'], ['收入', '奖学金助学金'], ['收入', '兼职收入'], ['收入', '红包收入'], ['收入', '其他收入'],
  ['支出', '餐饮美食'], ['支出', '交通出行'], ['支出', '购物消费'], ['支出', '学习资料'], ['支出', '居住缴费'],
  ['支出', '通讯娱乐'], ['支出', '医疗健康'], ['支出', '人情往来'], ['支出', '其他支出'],
  ['资金流转', '零钱通申购赎回'], ['资金流转', '信用卡还款'], ['资金流转', '银行卡互转'], ['资金流转', '提现'], ['资金流转', '个人转账'],
];

const RULE_SEED = [
  ['美团|饿了么', 'counterparty', '支出', '餐饮美食', 100, true],
  ['食堂', 'counterparty', '支出', '餐饮美食', 100, true],
  ['瑞幸|星巴克|Manner|蜜雪', 'counterparty', '支出', '餐饮美食', 90, true],
  ['便利店|超市', 'counterparty', '支出', '购物消费', 60, true],
  ['淘宝|天猫', 'counterparty', '支出', '购物消费', 70, true],
  ['京东', 'counterparty', '支出', '购物消费', 70, true],
  ['屈臣氏|优衣库', 'counterparty', '支出', '购物消费', 60, true],
  ['滴滴|高德打车', 'counterparty', '支出', '交通出行', 80, true],
  ['地铁|公交', 'counterparty', '支出', '交通出行', 80, true],
  ['哈啰|单车', 'counterparty', '支出', '交通出行', 70, true],
  ['当当|教材', 'counterparty', '支出', '学习资料', 70, true],
  ['打印|文具', 'counterparty', '支出', '学习资料', 60, true],
  ['学校后勤|住宿费', 'counterparty', '支出', '居住缴费', 90, true],
  ['水电', 'item', '支出', '居住缴费', 80, true],
  ['中国移动|话费', 'counterparty', '支出', '通讯娱乐', 80, true],
  ['万达|影城|电影', 'counterparty', '支出', '通讯娱乐', 70, true],
  ['会员|大会员', 'item', '支出', '通讯娱乐', 60, true],
  ['校医院|药店', 'counterparty', '支出', '医疗健康', 70, true],
  ['红包', 'item', '支出', '人情往来', 50, true],
  ['零钱通|余额宝', 'counterparty', '资金流转', '零钱通申购赎回', 120, true],
  ['信用卡还款', 'item', '资金流转', '信用卡还款', 120, true],
  ['父亲|母亲|生活费', 'counterparty', '收入', '家人资助', 110, true],
  ['助学金|奖学金|财务处', 'counterparty', '收入', '奖学金助学金', 110, true],
  ['兼职|家教', 'counterparty', '收入', '兼职收入', 90, true],
];

const MERCHANTS = [
  // 支出 · 餐饮美食
  { cp: '美团外卖', items: ['午餐·黄焖鸡米饭', '晚餐·麻辣香锅', '夜宵·烧烤'], l2: '餐饮美食', min: 1500, max: 3500, ch: 'wechat', w: 11 },
  { cp: '饿了么', items: ['午餐·麻辣烫', '晚餐·盖浇饭'], l2: '餐饮美食', min: 1500, max: 3500, ch: 'alipay', w: 7 },
  { cp: '学校食堂', items: ['早餐', '午餐', '晚餐'], l2: '餐饮美食', min: 600, max: 1800, ch: 'wechat', w: 24 },
  { cp: '瑞幸咖啡', items: ['生椰拿铁', '美式'], l2: '餐饮美食', min: 990, max: 1900, ch: 'wechat', w: 5 },
  { cp: '蜜雪冰城', items: ['柠檬水', '冰淇淋'], l2: '餐饮美食', min: 400, max: 1200, ch: 'wechat', w: 3 },
  { cp: '校园便利店', items: ['日用品', '零食', '饮料'], l2: '购物消费', min: 500, max: 2500, ch: 'wechat', w: 7 },
  // 支出 · 交通出行
  { cp: '滴滴出行', items: ['快车·返校', '快车·去市区'], l2: '交通出行', min: 1000, max: 4000, ch: 'alipay', w: 5 },
  { cp: '地铁 2 号线', items: ['通勤'], l2: '交通出行', min: 200, max: 600, ch: 'alipay', w: 14 },
  { cp: '哈啰单车', items: ['骑行'], l2: '交通出行', min: 150, max: 300, ch: 'wechat', w: 5 },
  // 支出 · 购物消费
  { cp: '淘宝', items: ['Type-C 数据线', '收纳盒', '手机壳'], l2: '购物消费', min: 1000, max: 12000, ch: 'alipay', w: 4 },
  { cp: '京东', items: ['移动电源', '键盘', '日用品'], l2: '购物消费', min: 5000, max: 20000, ch: 'alipay', w: 1 },
  { cp: '屈臣氏', items: ['洗护用品'], l2: '购物消费', min: 3000, max: 9000, ch: 'alipay', w: 1 },
  { cp: '优衣库', items: ['T 恤', '外套'], l2: '购物消费', min: 9900, max: 29900, ch: 'wechat', w: 0.4 },
  // 支出 · 学习资料
  { cp: '当当网', items: ['教材《数据结构》', '考研资料'], l2: '学习资料', min: 3000, max: 8000, ch: 'alipay', w: 1.5 },
  { cp: '学校打印店', items: ['打印复印'], l2: '学习资料', min: 200, max: 1200, ch: 'wechat', w: 4 },
  { cp: '文具店', items: ['笔芯', '笔记本'], l2: '学习资料', min: 500, max: 3000, ch: 'wechat', w: 2 },
  // 支出 · 居住缴费
  { cp: '学校后勤', items: ['住宿费'], l2: '居住缴费', min: 13500, max: 13500, ch: 'bank', w: 1, monthly: true },
  { cp: '水电缴费', items: ['水电费'], l2: '居住缴费', min: 3000, max: 8000, ch: 'alipay', w: 1, monthly: true },
  // 支出 · 通讯娱乐
  { cp: '中国移动', items: ['话费充值 50 元'], l2: '通讯娱乐', min: 5000, max: 5000, ch: 'wechat', w: 1, monthly: true },
  { cp: '万达影城', items: ['电影票 ×2'], l2: '通讯娱乐', min: 3800, max: 7600, ch: 'wechat', w: 1.2 },
  { cp: '哔哩哔哩', items: ['大会员'], l2: '通讯娱乐', min: 1500, max: 1500, ch: 'alipay', w: 1, monthly: true },
  // 支出 · 医疗健康
  { cp: '校医院', items: ['门诊'], l2: '医疗健康', min: 1000, max: 5000, ch: 'wechat', w: 0.8 },
  { cp: '药店', items: ['感冒药', '创可贴'], l2: '医疗健康', min: 1500, max: 4000, ch: 'alipay', w: 0.8 },
  // 支出 · 人情往来
  { cp: '室友-张', items: ['AA 聚餐'], l2: '人情往来', min: 2000, max: 6000, ch: 'wechat', w: 1.5 },
  { cp: '红包', items: ['生日红包', '群红包'], l2: '人情往来', min: 5000, max: 10000, ch: 'wechat', w: 0.5 },
  // 支出 · 其他
  { cp: '未知商户 8871', items: ['二维码收款'], l2: '其他支出', min: 1000, max: 4000, ch: 'wechat', w: 1.2, noRule: true },
  { cp: '校园洗衣房', items: ['自助洗衣'], l2: '其他支出', min: 400, max: 1000, ch: 'wechat', w: 1.5 },
  // 收入
  { cp: '父亲', items: ['生活费转账'], l2: '家人资助', dir: 'income', min: 150000, max: 200000, ch: 'bank', w: 1, monthly: true },
  { cp: '学校财务处', items: ['秋季助学金'], l2: '奖学金助学金', dir: 'income', min: 50000, max: 50000, ch: 'bank', w: 1, months: [3, 9, 10] },
  { cp: '兼职-家教', items: ['家教课时费'], l2: '兼职收入', dir: 'income', min: 20000, max: 60000, ch: 'wechat', w: 1 },
  { cp: '微信红包', items: ['红包收入'], l2: '红包收入', dir: 'income', min: 5000, max: 20000, ch: 'wechat', w: 1, months: [1, 2] },
  // 资金流转
  { cp: '零钱通', items: ['转入零钱通', '转出至银行卡'], l2: '零钱通申购赎回', dir: 'neutral', min: 50000, max: 150000, ch: 'wechat', w: 2 },
  { cp: '信用卡还款', items: ['信用卡还款'], l2: '信用卡还款', dir: 'neutral', min: 30000, max: 100000, ch: 'bank', w: 1 },
  { cp: '银行卡互转', items: ['本人账户互转'], l2: '银行卡互转', dir: 'neutral', min: 20000, max: 80000, ch: 'bank', w: 1 },
  { cp: '提现', items: ['零钱提现'], l2: '提现', dir: 'neutral', min: 10000, max: 50000, ch: 'wechat', w: 1 },
  { cp: '室友-李', items: ['AA 转账'], l2: '个人转账', dir: 'neutral', min: 2000, max: 10000, ch: 'wechat', w: 2 },
];

/* 日常随机消费池：固定项（收入/居住/通讯/资金流转）不参与随机 */
const DAILY = MERCHANTS.filter((m) => !m.dir && !m.monthly && !m.months);

/* ============================================================
   种子：生成 10 个月流水
   ============================================================ */
function seedCategories() {
  return CATEGORY_SEED.map(([l1, l2], i) => ({
    id: `CAT-${String(i + 1).padStart(3, '0')}`,
    l1, l2,
    sort: i,
    enabled: true,
    is_builtin: true,
    created_at: '2026-01-01T00:00:00',
  }));
}

function seedRules() {
  return RULE_SEED.map(([keyword, field, l1, l2, priority, enabled], i) => ({
    id: `RULE-${String(i + 1).padStart(3, '0')}`,
    keyword,
    match_field: field,
    category_l1: l1,
    category_l2: l2,
    priority,
    enabled,
    is_builtin: true,
    created_at: `2026-01-01T00:${pad(i)}:00`,
    updated_at: `2026-01-01T00:${pad(i)}:00`,
  }));
}

function seedTransactions() {
  const r = rng(20261022);
  const out = [];
  const raw = {};
  const months = [];
  for (let back = 9; back >= 0; back--) months.push(new Date(NOW.getFullYear(), NOW.getMonth() - back, 1));

  const byName = (n) => MERCHANTS.find((m) => m.cp === n);
  let seq = 0;

  for (const first of months) {
    const y = first.getFullYear(), m = first.getMonth() + 1;
    const isCurrent = y === NOW.getFullYear() && m === NOW.getMonth() + 1;
    const lastDay = isCurrent ? NOW.getDate() : daysInMonth(y, m);
    const batchId = `B-${y}${pad(m)}15-1`;
    const mk = monthKey(first);
    let rowNo = 0;
    raw[mk] = [];

    const add = (mt, day, cents, item, hourHint) => {
      if (day < 1 || day > lastDay) return;
      const dir = mt.dir || 'expense';
      const hour = hourHint ?? between(r, 8, 21);
      const t = `${y}-${pad(m)}-${pad(day)}T${pad(hour)}:${pad(between(r, 0, 59))}:${pad(between(r, 0, 59))}`;
      const cp = mt.cp;
      const it = item || pick(r, mt.items);
      const fp = fpOf(t, cents, dir, cp, it);

      let status = 'confirmed';
      let catL1 = dir === 'income' ? '收入' : dir === 'neutral' ? '资金流转' : '支出';
      let catL2 = mt.l2;
      let hintL1 = null, hintL2 = null;
      if (dir === 'expense' && mt.noRule) {
        if (isCurrent) {
          // 当期未命中：留在待确认队列
          status = 'pending'; catL1 = null; catL2 = null; hintL1 = '支出'; hintL2 = '其他支出';
        } else {
          // 历史月份视为已处理，避免导航角标被历史积压长期占满
          status = 'confirmed'; catL1 = '支出'; catL2 = '其他支出';
        }
      } else if (dir === 'expense' && r() < 0.004) {
        status = 'excluded';
      } else if (dir === 'expense' && r() < 0.015) {
        status = 'corrected';
      }

      out.push({
        id: `T-${y}${pad(m)}-${String(++seq).padStart(4, '0')}`,
        occurred_at: t,
        amount_cents: cents,
        direction: dir,
        category_l1: catL1,
        category_l2: catL2,
        counterparty: cp,
        item: it,
        txn_type: dir === 'neutral' ? '转账' : dir === 'income' ? '转账' : '商户消费',
        payment_method: mt.ch === 'wechat' ? '零钱' : mt.ch === 'alipay' ? '余额宝' : '银行卡',
        channel: mt.ch,
        status,
        note: status === 'corrected' ? '原判为「其他支出」，手动改为当前分类' : '',
        hint_l1: hintL1,
        hint_l2: hintL2,
        batch_id: batchId,
        row_no: ++rowNo,
        fp,
        override_reason: null,
        override_at: null,
        created_at: t,
        updated_at: t,
      });

      raw[mk].push({
        id: raw[mk].length + 1,
        batch_id: batchId,
        row_no: rowNo,
        occurred_at: t,
        amount_cents: cents,
        direction: dir,
        counterparty: cp,
        item: it,
        txn_type: dir === 'neutral' ? '转账' : '商户消费',
        payment_method: mt.ch === 'wechat' ? '零钱' : mt.ch === 'alipay' ? '余额宝' : '银行卡',
        platform_category: hintL2 || catL2 || '',
        platform_status: '交易成功',
        channel: mt.ch,
        fp,
        raw_payload: JSON.stringify({ 交易时间: t, 交易对方: cp, 商品: it, 金额: (cents / 100).toFixed(2) }),
        imported_at: t,
      });
    };

    /* 固定项：生活费、助学金、住宿、话费、会员、零钱通、室友转账 */
    add(byName('父亲'), 3, 200000, '生活费转账', 9);
    if ([3, 9, 10].includes(m)) add(byName('学校财务处'), 10, 50000, '助学金', 16);
    if ([1, 2].includes(m)) add(byName('微信红包'), 8, between(r, 5000, 20000), '红包收入', 12);
    add(byName('兼职-家教'), between(r, 6, 24), between(r, 20000, 50000), '家教课时费', 20);
    add(byName('学校后勤'), 5, 13500, '住宿费', 10);
    add(byName('水电缴费'), 8, between(r, 3500, 6500), '水电费', 11);
    add(byName('中国移动'), 12, 5000, '话费充值 50 元', 19);
    add(byName('哔哩哔哩'), 15, 1500, '大会员', 21);
    add(byName('零钱通'), 18, between(r, 50000, 120000), '转入零钱通', 22);
    add(byName('未知商户 8871'), Math.min(19, lastDay), between(r, 1000, 4000), '二维码收款', 20);
    add(byName('室友-李'), 20, between(r, 2000, 8000), 'AA 转账', 23);

    /* 日常消费：工作日 2~4 笔，周末 3~5 笔 */
    for (let d = 1; d <= lastDay; d++) {
      const wd = new Date(y, m - 1, d).getDay();
      const n = wd === 0 || wd === 6 ? between(r, 3, 5) : between(r, 2, 4);
      for (let k = 0; k < n; k++) {
        const mt = wpick(r, DAILY);
        add(mt, d, between(r, mt.min, mt.max));
      }
    }
  }
  return { transactions: out, raw };
}

/* ============================================================
   种子：批次 / 备份 / 设置 / 待清理
   ============================================================ */
function seedBatches() {
  const now = iso(NOW);
  const mk = monthKey(NOW);
  return [
    {
      id: `B-${mk.replace('-', '')}21-1`, file_name: '微信支付账单(20261001-20261021).csv', stored_name: 'a1f3-wechat.csv',
      file_size: 88064, channel: 'wechat', status: 'prechecked', total_rows: 42, new_count: 38, dup_count: 3, pending_count: 1,
      encoding: 'UTF-8', adapter: 'wechat', header_row_no: 17, file_exists: true,
      created_at: now, updated_at: now, fail_reason: null, pending_delete_flag: 0, deleted_at: null,
    },
    {
      id: 'B-20261020-1', file_name: '支付宝交易明细(20261001-20261020).csv', stored_name: 'b7c2-alipay.csv',
      file_size: 219136, channel: 'alipay', status: 'mapped_pending', total_rows: 128, new_count: 0, dup_count: 0, pending_count: 0,
      encoding: 'UTF-8', adapter: 'alipay', header_row_no: 23, file_exists: true,
      created_at: '2026-10-20T21:10:00', updated_at: '2026-10-20T21:10:00', fail_reason: null, pending_delete_flag: 0, deleted_at: null,
    },
    {
      id: 'B-20261019-1', file_name: '招商银行流水(202609).xlsx', stored_name: 'c9d1-bank.xlsx',
      file_size: 65536, channel: 'bank', status: 'failed', total_rows: 0, new_count: 0, dup_count: 0, pending_count: 0,
      encoding: null, adapter: null, header_row_no: null, file_exists: true,
      created_at: '2026-10-19T10:22:00', updated_at: '2026-10-19T10:22:00',
      fail_reason: '编码探测失败：疑似 GB18030 变体，请另存为「CSV UTF-8」后重试', pending_delete_flag: 0, deleted_at: null,
    },
    {
      id: 'B-20261018-1', file_name: '微信支付账单(202609).csv', stored_name: 'd3e4-wechat-09.csv',
      file_size: 172032, channel: 'wechat', status: 'ingested', total_rows: 96, new_count: 92, dup_count: 4, pending_count: 0,
      encoding: 'UTF-8', adapter: 'wechat', header_row_no: 17, file_exists: false,
      created_at: '2026-10-18T09:30:00', updated_at: '2026-10-18T09:31:12', fail_reason: null, pending_delete_flag: 0,
      deleted_at: '2026-10-18T09:31:12',
    },
    {
      id: 'B-20261015-2', file_name: '零钱通收益明细.csv', stored_name: 'e5f6-change.csv',
      file_size: 12288, channel: 'wechat', status: 'discarded', total_rows: 31, new_count: 0, dup_count: 0, pending_count: 0,
      encoding: 'UTF-8', adapter: 'wechat', header_row_no: 0, file_exists: false,
      created_at: '2026-10-15T16:40:00', updated_at: '2026-10-15T16:41:00', fail_reason: null, pending_delete_flag: 0,
      deleted_at: '2026-10-15T16:41:00',
    },
    {
      id: 'B-20261014-1', file_name: '微信支付账单(202608).csv', stored_name: 'f7a8-wechat-08.csv',
      file_size: 151552, channel: 'wechat', status: 'ingested', total_rows: 88, new_count: 88, dup_count: 0, pending_count: 0,
      encoding: 'UTF-8', adapter: 'wechat', header_row_no: 17, file_exists: true,
      created_at: '2026-10-14T20:05:00', updated_at: '2026-10-14T20:06:00', fail_reason: null, pending_delete_flag: 1,
      deleted_at: null,
    },
  ];
}

function seedBackups() {
  return [
    { id: 'BK-001', kind: 'db', file_name: 'finance-2026-10-13.sqlite', file_path: 'backups/finance-2026-10-13.sqlite', size_bytes: 4404019, checksum: 'sha256:9a1c…', row_counts: { transaction: 1086, raw: 1086 }, created_at: '2026-10-13T21:04:00', restored_at: null },
    { id: 'BK-002', kind: 'db', file_name: 'finance-2026-10-06.sqlite', file_path: 'backups/finance-2026-10-06.sqlite', size_bytes: 4299161, checksum: 'sha256:7f2b…', row_counts: { transaction: 1002, raw: 1002 }, created_at: '2026-10-06T20:11:00', restored_at: null },
    { id: 'BK-003', kind: 'export_csv', file_name: 'export-2026-09-30.csv', file_path: 'backups/export-2026-09-30.csv', size_bytes: 1887436, checksum: 'sha256:1c9d…', row_counts: { transaction: 982 }, created_at: '2026-09-30T18:22:00', restored_at: null },
    { id: 'BK-004', kind: 'db', file_name: 'finance-2026-09-29.sqlite', file_path: 'backups/finance-2026-09-29.sqlite', size_bytes: 4089446, checksum: 'sha256:4e6a…', row_counts: { transaction: 968, raw: 968 }, created_at: '2026-09-29T19:40:00', restored_at: null },
  ];
}

function seedSettings() {
  return {
    single_day_threshold_cents: 20000,
    backup_interval_days: 7,
    week_start: 1,
    event_log_enabled: false,
    buffer_threshold_bytes: 524288000,
    data_dir: 'D:\\finance-data',
    theme: 'pink',
    updated_at: '2026-10-13T21:04:00',
  };
}

/* ============================================================
   构建与持久化
   ============================================================ */
function build() {
  const { transactions, raw } = seedTransactions();
  const batches = seedBatches();
  const db = {
    version: 3,
    transactions,
    raw,
    batches,
    rules: seedRules(),
    categories: seedCategories(),
    settings: seedSettings(),
    backups: seedBackups(),
    cleanup: [{
      id: 'CL-001', batch_id: 'B-20261014-1', file_path: 'buffer/f7a8-wechat-08.csv',
      file_name: '微信支付账单(202608).csv', reason: '文件被其他程序占用（E4003）', attempts: 1,
      last_error: 'EBUSY: resource busy or locked', status: 'pending',
      created_at: '2026-10-14T20:06:02', updated_at: '2026-10-14T20:06:02',
    }],
    orphans: [{ name: 'tmp_upload_9f2a.part', size: 2516582, modified_at: '2026-10-20T18:02:00' }],
    overrides: {},
    previews: {},
    prechecks: {},
    reports: {},
    templates: [{
      id: 'TPL-001', channel: 'wechat', name: '微信支付', is_default: true,
      spec: { occurred_at: 0, amount: 5, direction: 4, counterparty: 2, item: 3, amount_scale: 1 },
      created_at: '2026-09-01T09:00:00', updated_at: '2026-09-01T09:00:00',
    }],
    events: [],
    last_restore: null,
    seq: transactions.length,
  };
  return db;
}

function ensureDb() {
  if (db) return;
  try {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
      const parsed = JSON.parse(cached);
      if (parsed.version === 3) { db = parsed; return; }
    }
  } catch { /* 隐私模式忽略 */ }
  db = build();
  persist();
}

function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(db)); } catch { /* 容量/隐私模式忽略 */ }
}

export function resetLocalData() {
  db = build();
  persist();
}

function fail(code, message, detail = null) {
  throw new ApiError(code, message, 200, detail);
}

/* ============================================================
   期间与口径（与 SDD §9.2 / §10.3 对齐）
   ============================================================ */
function rangeOf(period, anchor) {
  const now = new Date(NOW.getFullYear(), NOW.getMonth(), NOW.getDate());
  if (period === 'month') {
    const [y, m] = anchor.split('-').map(Number);
    const start = new Date(y, m - 1, 1);
    const next = addMonths(start, 1);
    const end = next <= addDays(now, 1) ? next : addDays(now, 1);
    const days = Math.max(1, Math.round((end - start) / 86400000));
    return { kind: 'month', label: `${y} 年 ${m} 月`, start: dateIso(start), end: dateIso(end), days, startDate: start, endDate: end };
  }
  if (period === 'quarter') {
    const [y, q] = anchor.split('Q').map(Number);
    const start = new Date(y, (q - 1) * 3, 1);
    const next = new Date(y, q * 3, 1);
    const end = next <= addDays(now, 1) ? next : addDays(now, 1);
    const days = Math.max(1, Math.round((end - start) / 86400000));
    return { kind: 'quarter', label: `${y} 年 Q${q}`, start: dateIso(start), end: dateIso(end), days, startDate: start, endDate: end };
  }
  const y = Number(anchor);
  const start = new Date(y, 0, 1);
  const next = new Date(y + 1, 0, 1);
  const end = next <= addDays(now, 1) ? next : addDays(now, 1);
  const days = Math.max(1, Math.round((end - start) / 86400000));
  return { kind: 'year', label: `${y} 年度`, start: dateIso(start), end: dateIso(end), days, startDate: start, endDate: end };
}

function prevRangeOf(period, anchor) {
  if (period === 'month') {
    const [y, m] = anchor.split('-').map(Number);
    const d = addMonths(new Date(y, m - 1, 1), -1);
    return rangeOf('month', monthKey(d));
  }
  if (period === 'quarter') {
    const [y, q] = anchor.split('Q').map(Number);
    const py = q === 1 ? y - 1 : y, pq = q === 1 ? 4 : q - 1;
    const start = new Date(py, (pq - 1) * 3, 1);
    const end = new Date(py, pq * 3, 1);
    return { kind: 'quarter', label: `${py} 年 Q${pq}`, start: dateIso(start), end: dateIso(end), days: Math.round((end - start) / 86400000), startDate: start, endDate: end };
  }
  const y = Number(anchor) - 1;
  const start = new Date(y, 0, 1), end = new Date(y + 1, 0, 1);
  return { kind: 'year', label: `${y} 年度`, start: dateIso(start), end: dateIso(end), days: Math.round((end - start) / 86400000), startDate: start, endDate: end };
}

const inRange = (t, range) => t.occurred_at >= range.start && t.occurred_at < range.end;
const countBase = (rows) => rows.filter((t) => (t.direction === 'income' || t.direction === 'expense') && t.status !== 'excluded');

function sumBy(rows, dir) {
  return rows.filter((t) => t.direction === dir).reduce((s, t) => s + t.amount_cents, 0);
}

function kpiOf(range, prevRange) {
  const rows = countBase(db.transactions.filter((t) => inRange(t, range)));
  const prev = countBase(db.transactions.filter((t) => inRange(t, prevRange)));
  const income = sumBy(rows, 'income');
  const expense = sumBy(rows, 'expense');
  const pIncome = sumBy(prev, 'income');
  const pExpense = sumBy(prev, 'expense');
  const balance = income - expense;
  const pBalance = pIncome - pExpense;
  const saving = income > 0 ? (balance / income) * 100 : null;
  const pSaving = pIncome > 0 ? (pBalance / pIncome) * 100 : null;
  const dailyAvg = Math.round(expense / range.days);
  const pDailyAvg = Math.round(pExpense / prevRange.days);
  const mom = (cur, before) => {
    if (!prev.length) return { v: null, flag: 'na' };
    if (before === 0) return { v: null, flag: 'new' };
    return { v: ((cur - before) / before) * 100, flag: 'ok' };
  };
  const incomeMom = mom(income, pIncome);
  const expenseMom = mom(expense, pExpense);
  const pendingRows = rows.filter((t) => t.status === 'pending');
  return {
    total_income_cents: income,
    total_expense_cents: expense,
    balance_cents: balance,
    savings_rate: saving,
    income_mom: incomeMom.v,
    expense_mom: expenseMom.v,
    mom_flag: incomeMom.flag === 'na' ? 'na' : incomeMom.flag,
    pending_count: pendingRows.length,
    uncategorized_cents: pendingRows.filter((t) => t.direction === 'expense').reduce((s, t) => s + t.amount_cents, 0),
    // 可选字段：SDD §6.3 未定义，前端缺失时显示「—」
    savings_mom: saving != null && pSaving != null ? saving - pSaving : null,
    daily_avg_cents: dailyAvg,
    daily_avg_mom: prev.length && pDailyAvg ? ((dailyAvg - pDailyAvg) / pDailyAvg) * 100 : null,
  };
}

function categoriesOf(range, prevRange, level = 1) {
  const rows = db.transactions.filter((t) => inRange(t, range) && t.direction === 'expense' && t.status !== 'excluded');
  const prevRows = db.transactions.filter((t) => inRange(t, prevRange) && t.direction === 'expense' && t.status !== 'excluded');
  const total = rows.reduce((s, t) => s + t.amount_cents, 0);
  const prevTotal = prevRows.reduce((s, t) => s + t.amount_cents, 0);

  const keyOf = (t) => {
    if (t.status === 'pending') return ['未分类', null];
    return level === 1 ? [t.category_l1 || '其他', null] : [t.category_l1 || '其他', t.category_l2 || '其他'];
  };
  const buckets = new Map();
  for (const t of rows) {
    const [l1, l2] = keyOf(t);
    const k = `${l1}||${l2 || ''}`;
    const b = buckets.get(k) || { l1, l2, amount: 0, count: 0 };
    b.amount += t.amount_cents; b.count += 1;
    buckets.set(k, b);
  }
  const prevBuckets = new Map();
  for (const t of prevRows) {
    const [l1, l2] = keyOf(t);
    const k = `${l1}||${l2 || ''}`;
    prevBuckets.set(k, (prevBuckets.get(k) || 0) + t.amount_cents);
  }
  const list = [...buckets.values()].map((b) => {
    const before = prevBuckets.get(`${b.l1}||${b.l2 || ''}`) || 0;
    return {
      l1: b.l1,
      l2: b.l2,
      amount_cents: b.amount,
      ratio: total > 0 ? Math.round((b.amount / total) * 10000) / 100 : 0,
      txn_count: b.count,
      mom: prevRows.length ? (before === 0 ? null : ((b.amount - before) / before) * 100) : null,
      mom_flag: !prevRows.length ? 'na' : before === 0 ? 'new' : 'ok',
    };
  });
  list.sort((a, b) => (a.l1 === '未分类' ? 1 : b.l1 === '未分类' ? -1 : b.amount_cents - a.amount_cents));
  return { list, total, prevTotal };
}

function trendOf(range, granularity) {
  const rows = db.transactions.filter((t) => inRange(t, range) && (t.direction === 'income' || t.direction === 'expense') && t.status !== 'excluded');
  const threshold = db.settings.single_day_threshold_cents;
  const buckets = new Map();
  const bucketKey = (t) => {
    const d = t.occurred_at.slice(0, 10);
    if (granularity === 'month') return d.slice(0, 7);
    if (granularity === 'week') {
      const dt = new Date(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
      const weekStart = db.settings.week_start === 1 ? 1 : 0;
      const diff = (dt.getDay() - weekStart + 7) % 7;
      return dateIso(addDays(dt, -diff));
    }
    return d;
  };
  for (const t of rows) {
    const k = bucketKey(t);
    const b = buckets.get(k) || { bucket: k, income_cents: 0, expense_cents: 0 };
    if (t.direction === 'income') b.income_cents += t.amount_cents;
    else b.expense_cents += t.amount_cents;
    buckets.set(k, b);
  }
  const s = range.startDate, e = addDays(range.endDate, -1);
  const points = [];
  if (granularity === 'day') {
    for (let d = new Date(s); d <= e; d = addDays(d, 1)) {
      const k = dateIso(d);
      const b = buckets.get(k) || { income_cents: 0, expense_cents: 0 };
      points.push({ bucket: k, ...b, over_threshold: b.expense_cents > threshold });
    }
  } else if (granularity === 'month') {
    for (let d = new Date(s.getFullYear(), s.getMonth(), 1); d < e || monthKey(d) === monthKey(e); d = addMonths(d, 1)) {
      const k = monthKey(d);
      const b = buckets.get(k) || { income_cents: 0, expense_cents: 0 };
      points.push({ bucket: k, ...b, over_threshold: false });
      if (d.getFullYear() === e.getFullYear() && d.getMonth() === e.getMonth()) break;
    }
  } else {
    const weekStart = db.settings.week_start === 1 ? 1 : 0;
    let w = new Date(s);
    while (((w.getDay() - weekStart + 7) % 7) !== 0) w = addDays(w, -1);
    for (; w <= e; w = addDays(w, 7)) {
      const k = dateIso(w);
      const b = buckets.get(k) || { income_cents: 0, expense_cents: 0 };
      points.push({ bucket: k, ...b, over_threshold: false });
    }
  }
  const dedup = [];
  const seen = new Set();
  for (const p of points) { if (!seen.has(p.bucket)) { seen.add(p.bucket); dedup.push(p); } }
  return { granularity, points: dedup };
}

function topCounterparties(range, limit = 5) {
  const rows = db.transactions.filter((t) => inRange(t, range) && t.direction === 'expense' && t.status !== 'excluded' && t.counterparty);
  const map = new Map();
  for (const t of rows) {
    const b = map.get(t.counterparty) || { counterparty: t.counterparty, amount_cents: 0, txn_count: 0 };
    b.amount_cents += t.amount_cents; b.txn_count += 1;
    map.set(t.counterparty, b);
  }
  return [...map.values()].sort((a, b) => b.amount_cents - a.amount_cents || b.txn_count - a.txn_count).slice(0, limit);
}

function pendingBrief(range) {
  const rows = countBase(db.transactions.filter((t) => inRange(t, range))).filter((t) => t.status === 'pending');
  return {
    count: rows.length,
    amount_cents: rows.filter((t) => t.direction === 'expense').reduce((s, t) => s + t.amount_cents, 0),
  };
}

function toTxnDTO(t) { return clone(t); }

function toBatchDTO(b) {
  const { stored_name, pending_delete_flag, deleted_at, mapping_snapshot, ...rest } = b;
  return clone(rest);
}

function batchDetail(b) {
  const mapping = db.previews[b.id]?.mapping || b.mapped_fields || null;
  return {
    ...toBatchDTO(b),
    header_row_no: b.header_row_no,
    mapped_fields: mapping,
    mapping_snapshot: b.mapping_snapshot || null,
    parse_meta: {
      sheet: b.channel === 'bank' ? 'Sheet1' : null,
      delimiter: b.channel === 'bank' ? null : ',',
      preamble_rows: b.header_row_no || 0,
      header_row_no: b.header_row_no || 0,
      empty_rows_skipped: 0,
      issues: b.fail_reason ? { ENCODING: 1 } : {},
    },
    report: db.reports[b.id] || null,
    file_exists: !!b.file_exists,
  };
}

/* ============================================================
   分类引擎（规则优先级：数值大者优先，同级取最新创建）
   ============================================================ */
function classify(tx) {
  const hay = { counterparty: tx.counterparty || '', item: tx.item || '', txn_type: tx.txn_type || '' };
  const rules = db.rules
    .filter((r) => r.enabled)
    .slice()
    .sort((a, b) => b.priority - a.priority || String(b.created_at).localeCompare(String(a.created_at)));
  for (const r of rules) {
    const fields = r.match_field === 'any' ? Object.values(hay) : [hay[r.match_field] || ''];
    const hit = fields.some((f) => r.keyword.split('|').some((kw) => kw && f.toLowerCase().includes(kw.toLowerCase())));
    if (hit) return { category_l1: r.category_l1, category_l2: r.category_l2, status: 'confirmed' };
  }
  return { category_l1: null, category_l2: null, status: 'pending' };
}

/* ============================================================
   预览 / 预检
   ============================================================ */
function buildPreview(batch) {
  if (db.previews[batch.id]) return db.previews[batch.id];
  const r = rng(1234 + batch.total_rows);
  const total = Math.max(4, batch.total_rows);
  const newCount = total - 4;
  const mk = monthKey(NOW);
  const [yy, mm] = mk.split('-').map(Number);
  const maxDay = yy === NOW.getFullYear() && mm === NOW.getMonth() + 1 ? NOW.getDate() : daysInMonth(yy, mm);
  const headers = ['交易时间', '交易类型', '交易对方', '商品', '收/支', '金额(元)', '支付方式'];

  const row = (cells, parsed, issues = []) => ({
    row_no: 0,
    occurred_at: parsed.occurred_at ?? null,
    amount_cents: parsed.amount_cents ?? null,
    direction: parsed.direction ?? null,
    counterparty: parsed.counterparty ?? null,
    item: parsed.item ?? null,
    cells,
    issues,
    valid: !!(parsed.occurred_at && parsed.amount_cents != null),
  });

  const fresh = [];
  for (let i = 0; i < newCount; i++) {
    const mt = pick(r, DAILY);
    const day = between(r, 1, maxDay);
    const time = `${yy}-${pad(mm)}-${pad(day)}T${pad(between(r, 8, 21))}:${pad(between(r, 0, 59))}:${pad(between(r, 0, 59))}`;
    const cents = between(r, mt.min, mt.max);
    const item = pick(r, mt.items);
    fresh.push(row(
      [time.replace('T', ' '), '商户消费', mt.cp, item, '支出', (cents / 100).toFixed(2), '零钱'],
      { occurred_at: time, amount_cents: cents, direction: 'expense', counterparty: mt.cp, item },
    ));
  }

  // 前 8 条新流水 → 3 条真实重复 → 其余新流水 → 1 条金额异常
  const rows = fresh.slice(0, 8);

  const dupes = db.transactions
    .filter((t) => t.direction === 'expense' && t.occurred_at.startsWith(mk))
    .slice(0, 3);
  for (const t of dupes) {
    rows.push(row(
      [t.occurred_at.replace('T', ' '), t.txn_type, t.counterparty, t.item, '支出', (t.amount_cents / 100).toFixed(2), t.payment_method],
      { occurred_at: t.occurred_at, amount_cents: t.amount_cents, direction: t.direction, counterparty: t.counterparty, item: t.item },
    ));
  }
  rows.push(...fresh.slice(8));

  const badTime = `${yy}-${pad(mm)}-${pad(Math.min(2, maxDay))}T20:20:00`;
  rows.push(row(
    [badTime.replace('T', ' '), '商户消费', '万达影城', '电影票 ×2', '支出', '—', '零钱'],
    { occurred_at: badTime, amount_cents: null, direction: 'expense', counterparty: '万达影城', item: '电影票 ×2' },
    [{ code: 'AMOUNT_PARSE', row_no: 0, field: 'amount', raw: '—' }],
  ));

  rows.forEach((x, i) => {
    x.row_no = i + 1;
    x.issues.forEach((issue) => { issue.row_no = i + 1; });
  });

  const preview = {
    batch_id: batch.id,
    total_rows: total,
    columns: headers.length,
    header_row_no: batch.header_row_no || 0,
    headers,
    suggested_mapping: {
      occurred_at: 0, amount: 5, direction: 4, counterparty: 2, item: 3,
      txn_type: 1, payment_method: 6, platform_category: -1, platform_status: -1,
      direction_map: { 支出: 'expense', 收入: 'income', '/': 'neutral' },
      amount_scale: 1,
    },
    rows,
    limit: 20,
    truncated: rows.length > 20,
  };
  db.previews[batch.id] = preview;
  persist();
  return preview;
}

function mappingIsValid(m) {
  return Number.isInteger(m?.occurred_at) && m.occurred_at >= 0
    && Number.isInteger(m?.amount) && m.amount >= 0
    && Number.isInteger(m?.direction) && m.direction >= 0;
}

function precheckOf(batch) {
  const pv = buildPreview(batch);
  const known = new Set(db.transactions.map((t) => t.fp).filter(Boolean));
  const overrides = db.overrides[batch.id] || {};
  const rows = pv.rows.map((row) => {
    const invalid = row.occurred_at == null || row.amount_cents == null || row.direction == null;
    const fp = invalid ? null : fpOf(row.occurred_at, row.amount_cents, row.direction, row.counterparty, row.item);
    const dup = !invalid && known.has(fp);
    const overridden = !!overrides[row.row_no];
    return {
      row_no: row.row_no,
      label: invalid ? 'pending_manual' : dup && !overridden ? 'dup' : 'new',
      occurred_at: row.occurred_at || null,
      amount_cents: row.amount_cents ?? null,
      direction: row.direction || null,
      counterparty: row.counterparty || null,
      item: row.item || null,
      issues: row.issues || [],
      override: overridden,
    };
  });
  const summary = {
    total: rows.length,
    new: rows.filter((r) => r.label === 'new').length,
    dup: rows.filter((r) => r.label === 'dup').length,
    pending_manual: rows.filter((r) => r.label === 'pending_manual').length,
  };
  const result = { summary, rows, snapshot_at: iso(new Date()) };
  db.prechecks[batch.id] = result;
  return result;
}

/* ============================================================
   报表
   ============================================================ */
function reportSummary(kpi, cats, top, pending) {
  const out = [];
  const expense = kpi.total_expense_cents / 100;
  const mom = kpi.expense_mom;
  out.push(mom == null
    ? `本期总支出 ${expense.toFixed(2)} 元，上期无可比数据。`
    : `本期总支出 ${expense.toFixed(2)} 元，较上期${mom >= 0 ? '增加' : '减少'} ${Math.abs(mom).toFixed(1)}%。`);
  const main = cats.find((c) => c.l1 !== '未分类');
  if (main) {
    out.push(`支出最多的是「${main.l2 || main.l1}」，共 ${(main.amount_cents / 100).toFixed(2)} 元，占 ${main.ratio.toFixed(1)}%。`);
  }
  if (top[0]) out.push(`Top 商户为「${top[0].counterparty}」，共 ${(top[0].amount_cents / 100).toFixed(2)} 元（${top[0].txn_count} 笔）。`);
  if (pending.count > 0) out.push(`有 ${pending.count} 笔待确认（${(pending.amount_cents / 100).toFixed(2)} 元）未分类，已计入总支出。`);
  out.push(kpi.savings_rate == null ? '本期无收入记录，储蓄率无法计算。' : `储蓄率 ${kpi.savings_rate.toFixed(1)}%。`);
  return out.slice(0, 5);
}

function monthlyReport(y, m) {
  const period = rangeOf('month', `${y}-${pad(m)}`);
  const prev = prevRangeOf('month', `${y}-${pad(m)}`);
  const kpi = kpiOf(period, prev);
  const { list } = categoriesOf(period, prev, 2);
  const top = topCounterparties(period, 5);
  const pending = pendingBrief(period);
  return {
    period: { kind: 'month', label: period.label, start: period.start, end: period.end, days: period.days },
    kpi, categories: list, top_counterparties: top,
    daily_avg_cents: kpi.daily_avg_cents,
    pending,
    summary_text: reportSummary(kpi, list, top, pending),
    generated_at: iso(new Date()),
  };
}

function quarterlyReport(y, q) {
  const period = rangeOf('quarter', `${y}Q${q}`);
  const prev = prevRangeOf('quarter', `${y}Q${q}`);
  const kpi = kpiOf(period, prev);
  const { list } = categoriesOf(period, prev, 2);
  const top = topCounterparties(period, 5);
  const pending = pendingBrief(period);
  return {
    period: { kind: 'quarter', label: period.label, start: period.start, end: period.end, days: period.days },
    kpi, categories: list, top_counterparties: top,
    daily_avg_cents: kpi.daily_avg_cents, pending,
    summary_text: reportSummary(kpi, list, top, pending),
    generated_at: iso(new Date()),
  };
}

function yearlyReport(y) {
  const period = rangeOf('year', String(y));
  const prev = prevRangeOf('year', String(y));
  const kpi = kpiOf(period, prev);
  const { list } = categoriesOf(period, prev, 2);
  const top = topCounterparties(period, 5);
  const pending = pendingBrief(period);
  return {
    period: { kind: 'year', label: period.label, start: period.start, end: period.end, days: period.days },
    kpi, categories: list, top_counterparties: top,
    daily_avg_cents: kpi.daily_avg_cents, pending,
    summary_text: reportSummary(kpi, list, top, pending),
    generated_at: iso(new Date()),
  };
}

/* ============================================================
   路由
   ============================================================ */
export async function handle(method, path, opts = {}) {
  ensureDb();
  await sleep();
  const { query = {}, body = {}, form } = opts;
  const qv = (k, d = null) => (query[k] === undefined || query[k] === '' ? d : query[k]);
  const page = Math.max(1, Number(qv('page', 1)));
  const pageSize = Math.min(200, Math.max(10, Number(qv('page_size', 50))));
  const paged = (items) => ({
    items: items.slice((page - 1) * pageSize, page * pageSize),
    meta: { page, page_size: pageSize, total: items.length, total_pages: Math.ceil(items.length / pageSize) },
  });

  /* ---- 健康 ---- */
  if (method === 'GET' && path === '/health') {
    return {
      status: 'ok', version: '0.1.0 (local-contract)', data_dir: db.settings.data_dir, db_ok: true,
      backlog: { cleanup: db.cleanup.filter((c) => c.status === 'pending').length, orphans: db.orphans.length },
    };
  }

  /* ---- 统计 ---- */
  if (method === 'GET' && path === '/stats/overview') {
    const period = rangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    const prev = prevRangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    const kpi = kpiOf(period, prev);
    const { list } = categoriesOf(period, prev, 2);
    const head = list.filter((c) => c.l1 !== '未分类').slice(0, 7);
    const rest = list.filter((c) => c.l1 !== '未分类').slice(7);
    const uncat = list.filter((c) => c.l1 === '未分类');
    const merged = [...head];
    if (rest.length) {
      merged.push({
        l1: '其他', l2: null,
        amount_cents: rest.reduce((s, x) => s + x.amount_cents, 0),
        ratio: Math.round(rest.reduce((s, x) => s + x.ratio, 0) * 100) / 100,
        txn_count: rest.reduce((s, x) => s + x.txn_count, 0), mom: null, mom_flag: 'na',
      });
    }
    merged.push(...uncat);
    const gran = period.kind === 'month' ? 'day' : period.kind === 'quarter' ? 'week' : 'month';
    return {
      period: { kind: period.kind, label: period.label, start: period.start, end: period.end, days: period.days },
      kpi,
      category_top: merged,
      trend: { ...trendOf(period, gran), granularity: gran },
      top_counterparties: topCounterparties(period, 5),
      pending: pendingBrief(period),
      generated_at: iso(new Date()),
    };
  }

  if (method === 'GET' && path === '/stats/categories') {
    const period = rangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    const prev = prevRangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    return categoriesOf(period, prev, Number(qv('level', 1))).list;
  }

  if (method === 'GET' && path === '/stats/trend') {
    const period = rangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    const g = qv('granularity', period.kind === 'month' ? 'day' : period.kind === 'quarter' ? 'week' : 'month');
    return trendOf(period, g);
  }

  if (method === 'GET' && path === '/stats/top-counterparties') {
    const period = rangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    return topCounterparties(period, Number(qv('limit', 5)));
  }

  if (method === 'GET' && path === '/stats/daily-threshold') {
    const period = rangeOf(qv('period', 'month'), qv('anchor', monthKey(NOW)));
    const threshold = db.settings.single_day_threshold_cents;
    const t = trendOf(period, 'day');
    return {
      threshold_cents: threshold,
      days: t.points.filter((p) => p.expense_cents > threshold).map((p) => ({
        date: p.bucket, amount_cents: p.expense_cents, over: p.expense_cents - threshold,
      })),
    };
  }

  /* ---- 报表 ---- */
  if (method === 'GET' && path === '/reports/monthly') {
    return monthlyReport(Number(qv('year', NOW.getFullYear())), Number(qv('month', NOW.getMonth() + 1)));
  }
  if (method === 'GET' && path === '/reports/quarterly') {
    return quarterlyReport(Number(qv('year', NOW.getFullYear())), Number(qv('quarter', Math.ceil((NOW.getMonth() + 1) / 3))));
  }
  if (method === 'GET' && path === '/reports/yearly') {
    return yearlyReport(Number(qv('year', NOW.getFullYear())));
  }

  /* ---- 明细 ---- */
  if (method === 'GET' && path === '/transactions') {
    const now = new Date();
    const period = qv('period', null);
    const anchor = qv('anchor', null);
    let rows = db.transactions.slice();
    if (period && anchor) {
      const r = rangeOf(period, anchor);
      rows = rows.filter((t) => inRange(t, r));
    }
    const dirs = (qv('direction', '') || '').split(',').filter(Boolean);
    if (dirs.length) rows = rows.filter((t) => dirs.includes(t.direction));
    const sts = (qv('status', '') || '').split(',').filter(Boolean);
    if (sts.length) rows = rows.filter((t) => sts.includes(t.status));
    const c1 = qv('category_l1', '');
    const c2 = qv('category_l2', '');
    if (c1 === '未分类' || c2 === '未分类') rows = rows.filter((t) => t.status === 'pending');
    else {
      if (c1) rows = rows.filter((t) => t.category_l1 === c1);
      if (c2) rows = rows.filter((t) => t.category_l2 === c2);
    }
    const kw = (qv('keyword', '') || '').trim();
    if (kw) rows = rows.filter((t) => `${t.counterparty || ''}${t.item || ''}`.toLowerCase().includes(kw.toLowerCase()));
    const pm = qv('payment_method', '');
    if (pm) rows = rows.filter((t) => t.payment_method === pm);
    const ch = qv('channel', '');
    if (ch) rows = rows.filter((t) => t.channel === ch);

    const sortRaw = qv('sort', '-occurred_at');
    const desc = sortRaw.startsWith('-');
    const key = sortRaw.replace(/^-/, '');
    if (!['occurred_at', 'amount_cents'].includes(key)) fail('E1010', '排序字段不支持，请使用时间或金额排序');
    rows.sort((a, b) => (key === 'amount_cents' ? a.amount_cents - b.amount_cents : a.occurred_at.localeCompare(b.occurred_at)) * (desc ? -1 : 1));
    const pageOut = paged(rows);
    return { items: pageOut.items.map(toTxnDTO), meta: pageOut.meta };
  }

  if (method === 'GET' && path === '/transactions/summary') {
    const now = new Date();
    let rows = db.transactions.filter((t) => (t.direction === 'income' || t.direction === 'expense') && t.status !== 'excluded');
    if (qv('period') && qv('anchor')) {
      const r = rangeOf(qv('period'), qv('anchor'));
      rows = rows.filter((t) => inRange(t, r));
    }
    const dirs = (qv('direction', '') || '').split(',').filter(Boolean);
    if (dirs.length) rows = rows.filter((t) => dirs.includes(t.direction));
    const sts = (qv('status', '') || '').split(',').filter(Boolean);
    if (sts.length) rows = rows.filter((t) => sts.includes(t.status));
    const c1 = qv('category_l1', ''), c2 = qv('category_l2', '');
    if (c1 === '未分类' || c2 === '未分类') rows = rows.filter((t) => t.status === 'pending');
    else {
      if (c1) rows = rows.filter((t) => t.category_l1 === c1);
      if (c2) rows = rows.filter((t) => t.category_l2 === c2);
    }
    const kw = (qv('keyword', '') || '').trim();
    if (kw) rows = rows.filter((t) => `${t.counterparty || ''}${t.item || ''}`.toLowerCase().includes(kw.toLowerCase()));
    const pm = qv('payment_method', '');
    if (pm) rows = rows.filter((t) => t.payment_method === pm);
    const ch = qv('channel', '');
    if (ch) rows = rows.filter((t) => t.channel === ch);
    const income = sumBy(rows, 'income'), expense = sumBy(rows, 'expense');
    return { total: rows.length, income_cents: income, expense_cents: expense, net_cents: income - expense };
  }

  if (method === 'PATCH' && /^\/transactions\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const t = db.transactions.find((x) => x.id === id);
    if (!t) fail('E2010', '这条流水不存在，可能已被删除，请刷新列表');
    const allowed = ['category_l1', 'category_l2', 'note'];
    const bad = Object.keys(body).filter((k) => !allowed.includes(k));
    if (bad.length) fail('E2009', '原始事实字段不可修改，只能改分类与备注', { fields: bad });
    if (body.category_l1 !== undefined) {
      const found = db.categories.find((c) => c.l1 === body.category_l1 && c.l2 === body.category_l2 && c.enabled);
      if (!found) fail('E2006', '目标分类不存在或已停用，请重新选择');
      t.category_l1 = body.category_l1;
      t.category_l2 = body.category_l2;
      t.status = 'corrected';
    }
    if (body.note !== undefined) t.note = String(body.note).slice(0, 200);
    t.updated_at = iso(new Date());
    persist();
    return toTxnDTO(t);
  }

  if (method === 'POST' && path === '/transactions/batch-category') {
    const ids = body.ids || [];
    const cp = body.counterparty;
    if (!ids.length && !cp) fail('E2008', '请先勾选要处理的流水');
    if (!body.l1 || !body.l2) fail('E2006', '请选择目标分类');
    const target = db.categories.find((c) => c.enabled && c.l1 === body.l1 && c.l2 === body.l2);
    if (!target) fail('E2006', '目标分类不存在或已停用');
    const rows = db.transactions.filter((t) => (ids.length ? ids.includes(t.id) : t.counterparty === cp) && t.status === 'pending');
    if (!rows.length) fail('E2008', '所选流水已被处理，请刷新后重试');
    for (const t of rows) {
      t.category_l1 = body.l1; t.category_l2 = body.l2; t.status = 'corrected'; t.updated_at = iso(new Date());
    }
    let rule_id = null;
    if (body.create_rule) {
      const id = `RULE-${String(db.rules.length + 1).padStart(3, '0')}`;
      const cpName = cp || rows[0].counterparty || '';
      db.rules.push({
        id, keyword: cpName, match_field: 'counterparty', category_l1: body.l1, category_l2: body.l2,
        priority: 100, enabled: true, is_builtin: false, created_at: iso(new Date()), updated_at: iso(new Date()),
      });
      rule_id = id;
    }
    persist();
    return { updated: rows.length, rule_id };
  }

  if (method === 'POST' && /^\/transactions\/[^/]+\/(exclude|restore)$/.test(path)) {
    const [, , id, action] = path.split('/');
    const t = db.transactions.find((x) => x.id === decodeURIComponent(id));
    if (!t) fail('E2010', '这条流水不存在，请刷新列表');
    if (action === 'exclude') {
      if (t.status === 'excluded') fail('E2008', '该流水已是「已排除」状态，无需重复操作');
      t.status = 'excluded';
      t.note = body.reason || t.note || '手动排除，不计入收支';
    } else {
      if (t.status !== 'excluded') fail('E2008', '只有「已排除」的流水可以恢复');
      t.status = t.category_l1 ? 'confirmed' : 'pending';
      t.note = '';
    }
    t.updated_at = iso(new Date());
    persist();
    return toTxnDTO(t);
  }

  if (method === 'GET' && path === '/pending') {
    const rows = countBase(db.transactions).filter((t) => t.status === 'pending');
    const map = new Map();
    for (const t of rows) {
      const k = t.counterparty || '未知对方';
      const g = map.get(k) || { counterparty: k, txn_count: 0, amount_cents: 0, first_at: t.occurred_at, last_at: t.occurred_at, hint_l1: t.hint_l1, hint_l2: t.hint_l2, items: [] };
      g.txn_count += 1; g.amount_cents += t.amount_cents;
      g.first_at = g.first_at < t.occurred_at ? g.first_at : t.occurred_at;
      g.last_at = g.last_at > t.occurred_at ? g.last_at : t.occurred_at;
      g.items.push(toTxnDTO(t));
      map.set(k, g);
    }
    const groups = [...map.values()];
    groups.forEach((g) => g.items.sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)));
    return paged(groups);
  }

  if (method === 'GET' && path === '/pending/count') {
    const rows = countBase(db.transactions).filter((t) => t.status === 'pending');
    return { count: rows.length, amount_cents: rows.filter((t) => t.direction === 'expense').reduce((s, t) => s + t.amount_cents, 0) };
  }

  if (method === 'GET' && /^\/transactions\/[^/]+\/trace$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const t = db.transactions.find((x) => x.id === id);
    if (!t) fail('E2010', '这条流水不存在，无法追溯');
    const b = db.batches.find((x) => x.id === t.batch_id) || null;
    const rawRow = (db.raw[t.occurred_at.slice(0, 7)] || []).find((r) => r.batch_id === t.batch_id && r.row_no === t.row_no) || null;
    return { transaction: toTxnDTO(t), batch: b ? toBatchDTO(b) : null, raw_record: rawRow, mapping_snapshot: b?.mapping_snapshot || null };
  }

  /* ---- 缓冲区 ---- */
  if (method === 'POST' && path === '/staging/batches') {
    if (!form) fail('E1001', '请选择要上传的文件');
    const file = form.get('file');
    if (!file || !file.name) fail('E1001', '请选择要上传的文件');
    const name = file.name;
    if (!/\.(csv|xlsx)$/i.test(name)) fail('E1001', '只支持 CSV 或 Excel(.xlsx) 文件，请重新导出');
    if (file.size > 5 * 1024 * 1024) fail('E1005', '文件超过 5MB，请按月分导出后重试');
    const channel = form.get('channel') || (/支付宝|alipay/i.test(name) ? 'alipay' : /银行|bank/i.test(name) ? 'bank' : /微信|wechat/i.test(name) ? 'wechat' : 'other');
    const id = `B-${new Date().getFullYear()}${pad(new Date().getMonth() + 1)}${pad(new Date().getDate())}-${db.batches.length + 1}`;
    const batch = {
      id, file_name: name, stored_name: `${Math.random().toString(16).slice(2, 6)}-${name.replace(/[^\w.]/g, '_')}`,
      file_size: file.size, channel, status: 'uploaded', total_rows: 42 + Math.floor(Math.random() * 30),
      new_count: 0, dup_count: 0, pending_count: 0, encoding: 'UTF-8', adapter: channel,
      header_row_no: channel === 'alipay' ? 23 : 17, file_exists: true,
      created_at: iso(new Date()), updated_at: iso(new Date()), fail_reason: null, pending_delete_flag: 0, deleted_at: null,
    };
    db.batches.unshift(batch);
    await delay(260);
    batch.status = 'mapped_pending';
    batch.updated_at = iso(new Date());
    buildPreview(batch);
    persist();
    return toBatchDTO(batch);
  }

  if (method === 'GET' && path === '/staging/batches') {
    let rows = db.batches.slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
    const st = qv('status');
    if (st) rows = rows.filter((b) => b.status === st);
    const out = paged(rows);
    return { items: out.items.map(toBatchDTO), meta: out.meta };
  }

  if (method === 'GET' && /^\/staging\/batches\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在，可能已被清理');
    return batchDetail(b);
  }

  if (method === 'POST' && /^\/staging\/batches\/[^/]+\/parse$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (!['uploaded', 'failed', 'mapped_pending', 'prechecked'].includes(b.status)) fail('E2002', '当前状态不允许重新解析');
    if (b.channel === 'bank' && b.file_name.includes('招商银行')) {
      b.status = 'failed';
      b.fail_reason = '编码探测失败：疑似 GB18030 变体，请另存为「CSV UTF-8」后重试';
      persist();
      fail('E1002', '无法识别文件编码，请用 Excel 另存为「CSV UTF-8」后重试');
    }
    b.status = 'mapped_pending';
    b.fail_reason = null;
    b.updated_at = iso(new Date());
    buildPreview(b);
    persist();
    return {
      batch: toBatchDTO(b),
      parse_meta: {
        sheet: null, delimiter: ',', preamble_rows: b.header_row_no || 0, header_row_no: b.header_row_no || 0,
        empty_rows_skipped: 0, issues: {}, columns: 7,
      },
      warnings: [],
    };
  }

  if (method === 'GET' && /^\/staging\/batches\/[^/]+\/preview$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (b.status === 'failed') fail('E2003', b.fail_reason || '该批次解析失败，请先重新解析', { can_retry: true });
    const pv = buildPreview(b);
    const limit = Math.max(1, Math.min(50, Number(qv('limit', 20))));
    return { ...clone(pv), rows: pv.rows.slice(0, limit), limit, truncated: pv.rows.length > limit };
  }

  if (method === 'PUT' && /^\/staging\/batches\/[^/]+\/mapping$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (b.status === 'ingested' || b.status === 'discarded') fail('E2002', '该批次已结束，不能再修改映射');
    if (!mappingIsValid(body)) {
      fail('E1007', '交易时间、金额、收支方向三列必须映射后才能进入预检');
    }
    const cols = buildPreview(b).columns.length;
    for (const k of ['occurred_at', 'amount', 'direction', 'counterparty', 'item']) {
      const v = body[k];
      if (v != null && (v < -1 || v >= cols)) fail('E1008', '列索引超出文件实际列数，请刷新预览后重新选择');
    }
    for (const v of Object.values(body.direction_map || {})) {
      if (!['income', 'expense', 'neutral'].includes(v)) fail('E1008', '收支方向的取值不合法');
    }
    let template_id = null;
    if (body.save_template) {
      const existing = db.templates.find((t) => t.channel === b.channel && t.is_default);
      if (existing && !body.template_policy) {
        fail('E2003', '该渠道已有默认模板，是否覆盖？也可另存为新模板', { existing_id: existing.id, can_overwrite: true });
      }
      if (existing && body.template_policy === 'overwrite') {
        existing.name = body.template_name || existing.name;
        existing.updated_at = iso(new Date());
        template_id = existing.id;
      } else if (!existing || body.template_policy === 'save_as') {
        const t = {
          id: `TPL-${String(db.templates.length + 1).padStart(3, '0')}`,
          channel: b.channel, name: body.template_name || `${b.channel} 模板`, is_default: !existing,
          spec_json: { mapping: body }, created_at: iso(new Date()), updated_at: iso(new Date()),
        };
        db.templates.push(t);
        template_id = t.id;
      }
    }
    const warnings = [];
    if (body.counterparty == null || body.counterparty === -1) warnings.push('未映射「交易对方」，按对方聚合的报表会缺少主体');
    if (body.item == null || body.item === -1) warnings.push('未映射「商品说明」，关键词规则只能匹配对方');

    // 硬三（时间/金额/方向）通过、模板无冲突后才提交映射状态（D-1/D-2）
    b.mapped_fields = clone(body);
    b.status = 'prechecked';
    b.updated_at = iso(new Date());
    persist();
    return { batch: toBatchDTO(b), warnings, template: template_id ? clone(db.templates.find((x) => x.id === template_id)) : null };
  }

  if (method === 'GET' && path === '/staging/templates') {
    const ch = qv('channel');
    return clone(db.templates.filter((t) => !ch || t.channel === ch));
  }

  if (method === 'POST' && path === '/staging/templates') {
    const { channel, name, spec, policy = 'abort' } = body;
    if (!channel || !name) fail('E2007', '渠道与模板名称不能为空');
    const defaults = db.templates.filter((t) => t.channel === channel && t.is_default);
    if (policy === 'abort' && defaults.length) {
      fail('E2003', `该渠道已有默认模板「${defaults[0].name}」，请选择覆盖或另存`, { channel, existing: defaults[0].name });
    }
    if (policy === 'overwrite') {
      for (const t of defaults) t.is_default = false;
      const t = {
        id: `TPL-${String(db.templates.length + 1).padStart(3, '0')}`,
        channel, name, spec: clone(spec), is_default: true,
        created_at: iso(new Date()), updated_at: iso(new Date()),
      };
      db.templates.push(t); persist();
      return clone(t);
    }
    const t = {
      id: `TPL-${String(db.templates.length + 1).padStart(3, '0')}`,
      channel, name, spec: clone(spec), is_default: false,
      created_at: iso(new Date()), updated_at: iso(new Date()),
    };
    db.templates.push(t); persist();
    return clone(t);
  }

  if (method === 'POST' && /^\/staging\/batches\/[^/]+\/precheck$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (b.status === 'mapped_pending') fail('E2002', '请先确认字段映射，再执行去重预检');
    if (b.status !== 'prechecked') fail('E2002', '该批次当前状态不允许预检');
    const res = precheckOf(b);
    b.new_count = res.summary.new;
    b.dup_count = res.summary.dup;
    b.pending_count = res.summary.pending_manual;
    b.updated_at = iso(new Date());
    persist();
    return res;
  }

  if (method === 'POST' && /^\/staging\/batches\/[^/]+\/overrides$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (!body.row_no || !String(body.reason || '').trim()) fail('E2008', '请填写强制新增的原因，便于日后追溯');
    db.overrides[id] = db.overrides[id] || {};
    db.overrides[id][body.row_no] = String(body.reason).trim();
    persist();
    return { batch_id: id, row_no: body.row_no, reason: db.overrides[id][body.row_no], created_at: iso(new Date()) };
  }

  if (method === 'DELETE' && /^\/staging\/batches\/[^/]+\/overrides\/\d+$/.test(path)) {
    const seg = path.split('/');
    const id = decodeURIComponent(seg[3]);
    const rowNo = Number(seg[seg.length - 1]);
    if (db.overrides[id]) delete db.overrides[id][rowNo];
    persist();
    return { removed: true };
  }

  if (method === 'POST' && /^\/staging\/batches\/[^/]+\/confirm$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (b.status !== 'prechecked') fail('E2002', '该批次当前状态为「已入库」或「入库中」，无需重复提交');
    const res = db.prechecks[b.id] || precheckOf(b);
    const accepted = res.rows.filter((r) => r.label === 'new');
    const monthly = {};
    let inserted = 0, pending = 0, skippedInvalid = 0;
    for (const row of accepted) {
      if (!row.occurred_at || row.amount_cents == null) { skippedInvalid += 1; continue; }
      const mk = row.occurred_at.slice(0, 7);
      const ch = b.channel;
      const draft = {
        id: `T-${mk.replace('-', '')}-${String(++db.seq).padStart(4, '0')}`,
        occurred_at: row.occurred_at,
        amount_cents: row.amount_cents,
        direction: row.direction || 'expense',
        counterparty: row.counterparty,
        item: row.item,
        txn_type: '商户消费',
        payment_method: ch === 'wechat' ? '零钱' : ch === 'alipay' ? '余额宝' : '银行卡',
        channel: ch,
        batch_id: b.id,
        row_no: row.row_no,
        fp: fpOf(row.occurred_at, row.amount_cents, row.direction, row.counterparty, row.item),
        note: '',
        hint_l1: null,
        hint_l2: null,
        override_reason: row.override ? (db.overrides[b.id]?.[row.row_no] || '强制新增') : null,
        override_at: row.override ? iso(new Date()) : null,
        created_at: iso(new Date()),
        updated_at: iso(new Date()),
      };
      const cls = classify(draft);
      Object.assign(draft, cls);
      if (draft.status === 'pending') pending += 1;
      db.transactions.push(draft);

      db.raw[mk] = db.raw[mk] || [];
      db.raw[mk].push({
        id: db.raw[mk].length + 1, batch_id: b.id, row_no: row.row_no, occurred_at: draft.occurred_at,
        amount_cents: draft.amount_cents, direction: draft.direction, counterparty: draft.counterparty,
        item: draft.item, txn_type: draft.txn_type, payment_method: draft.payment_method,
        platform_category: '', platform_status: '交易成功', channel: ch, fp: draft.fp,
        raw_payload: JSON.stringify({ 交易时间: draft.occurred_at, 交易对方: draft.counterparty, 商品: draft.item }),
        imported_at: iso(new Date()),
      });
      monthly[`raw_${mk.replace('-', '_')}`] = (monthly[`raw_${mk.replace('-', '_')}`] || 0) + 1;
      inserted += 1;
    }
    b.status = 'ingested';
    b.new_count = inserted;
    b.pending_count = pending;
    b.committed_at = iso(new Date());
    b.updated_at = iso(new Date());
    b.file_exists = false;
    b.deleted_at = iso(new Date());
    b.mapping_snapshot = { ...(b.mapped_fields || {}), created_at: iso(new Date()), adapter: b.adapter };
    const report = {
      batch_id: b.id, total: res.summary.total, inserted, skipped_dup: res.summary.dup,
      skipped_invalid: skippedInvalid, pending, monthly,
      overrides: Object.keys(db.overrides[b.id] || {}).length,
      files_deleted: true, cleanup_enqueued: false, finished_at: iso(new Date()),
    };
    b.report_json = report;
    db.reports[b.id] = report;
    db.events.unshift({ id: db.events.length + 1, ts: iso(new Date()), kind: 'INGEST_OK', batch_id: b.id, payload: `inserted=${inserted}` });
    persist();
    return report;
  }

  if (method === 'GET' && /^\/staging\/batches\/[^/]+\/report$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const r = db.reports[id];
    if (!r) fail('E2001', '该批次还没有导入报告');
    return clone(r);
  }

  if (method === 'POST' && /^\/staging\/batches\/[^/]+\/discard$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const b = db.batches.find((x) => x.id === id);
    if (!b) fail('E2001', '批次不存在');
    if (body.confirm !== true) fail('E2008', '丢弃需要二次确认');
    if (b.status === 'ingested') fail('E2002', '已入库的批次不能丢弃');
    b.status = 'discarded';
    b.file_exists = false;
    b.deleted_at = iso(new Date());
    b.updated_at = iso(new Date());
    persist();
    return toBatchDTO(b);
  }

  if (method === 'GET' && path === '/staging/orphans') return clone(db.orphans);

  if (method === 'POST' && path === '/staging/orphans/cleanup') {
    const names = body.names || [];
    const allowed = new Set(db.orphans.map((o) => o.name));
    const bad = names.filter((n) => !allowed.has(n));
    if (bad.length) fail('E1008', '存在未在清单中的文件名，已拒绝清理', { names: bad });
    db.orphans = db.orphans.filter((o) => !names.includes(o.name));
    persist();
    return { deleted: names.length, failed: [] };
  }

  if (method === 'GET' && path === '/staging/usage') {
    const files = db.batches.filter((b) => b.file_exists);
    const total = files.reduce((s, b) => s + b.file_size, 0);
    const threshold = db.settings.buffer_threshold_bytes;
    return { file_count: files.length, total_bytes: total, threshold, exceeded: total > threshold };
  }

  if (method === 'POST' && path === '/staging/ensure-dir') {
    return { path: 'D:\\finance-data\\buffer', created: false };
  }

  /* ---- 原始库 ---- */
  if (method === 'GET' && path === '/raw/months') {
    const out = Object.keys(db.raw).sort().reverse().map((m) => ({
      month: m.replace('-', '_'),
      count: db.raw[m].length,
      bytes: db.raw[m].reduce((s, r) => s + (r.raw_payload?.length || 0), 0),
    }));
    return out;
  }

  if (method === 'GET' && /^\/raw\/\d{4}_\d{2}\/records$/.test(path)) {
    const ym = path.split('/')[2];
    if (!/^\d{4}_\d{2}$/.test(ym)) fail('E1009', '月份格式应为 YYYY_MM');
    const key = ym.replace('_', '-');
    const rows = (db.raw[key] || []).slice().sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
    return paged(rows);
  }

  if (method === 'GET' && /^\/raw\/records\/\d+$/.test(path)) {
    const id = Number(path.split('/')[3]);
    for (const m of Object.keys(db.raw)) {
      const row = db.raw[m].find((r) => r.id === id);
      if (row) return { ...clone(row), month: m, batch: toBatchDTO(db.batches.find((b) => b.id === row.batch_id) || {}) };
    }
    fail('E2001', '原始记录不存在');
  }

  /* ---- 规则 ---- */
  if (method === 'GET' && path === '/rules') {
    const enabled = qv('enabled');
    let rows = db.rules.slice();
    if (enabled !== null) rows = rows.filter((r) => String(r.enabled) === String(enabled));
    return rows
      .slice()
      .sort((a, b) => b.priority - a.priority || String(b.created_at).localeCompare(String(a.created_at)))
      .map((r) => ({ ...clone(r), hit_count: db.transactions.filter((t) => matchRule(t, r)).length }));
  }

  if (method === 'POST' && path === '/rules') {
    if (!String(body.keyword || '').trim()) fail('E2007', '关键词不能为空');
    if (!Number.isInteger(body.priority)) fail('E2007', '优先级必须是整数');
    const cat = db.categories.find((c) => c.enabled && c.l1 === body.l1 && c.l2 === body.l2);
    if (!cat) fail('E2006', '目标分类不存在或已停用');
    if (db.rules.some((r) => r.keyword === body.keyword && r.match_field === body.match_field && r.category_l1 === body.l1 && r.category_l2 === body.l2)) {
      fail('E2007', '同样的规则已存在，请修改关键词或目标分类');
    }
    const r = {
      id: `RULE-${String(db.rules.length + 1).padStart(3, '0')}`,
      keyword: String(body.keyword).trim(), match_field: body.match_field || 'counterparty',
      category_l1: body.l1, category_l2: body.l2, priority: body.priority, enabled: true, is_builtin: false,
      created_at: iso(new Date()), updated_at: iso(new Date()),
    };
    db.rules.push(r);
    persist();
    return { ...clone(r), hit_count: 0 };
  }

  if (method === 'PATCH' && /^\/rules\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const r = db.rules.find((x) => x.id === id);
    if (!r) fail('E2007', '规则不存在');
    if (r.is_builtin) fail('E2007', '内置规则不可修改，可先停用后新增自定义规则');
    Object.assign(r, body, { updated_at: iso(new Date()) });
    persist();
    return { ...clone(r), hit_count: db.transactions.filter((t) => matchRule(t, r)).length };
  }

  if (method === 'POST' && /^\/rules\/[^/]+\/toggle$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const r = db.rules.find((x) => x.id === id);
    if (!r) fail('E2007', '规则不存在');
    r.enabled = !!body.enabled; r.updated_at = iso(new Date());
    persist();
    return { ...clone(r), hit_count: db.transactions.filter((t) => matchRule(t, r)).length };
  }

  if (method === 'DELETE' && /^\/rules\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const r = db.rules.find((x) => x.id === id);
    if (!r) fail('E2007', '规则不存在');
    if (r.is_builtin) fail('E2007', '内置规则不可删除，可停用');
    db.rules = db.rules.filter((x) => x.id !== id);
    persist();
    return { deleted: true };
  }

  /* ---- 分类 ---- */
  if (method === 'GET' && path === '/categories') {
    const enabled = qv('enabled');
    const groups = new Map();
    for (const c of db.categories) {
      if (enabled !== null && String(c.enabled) !== String(enabled)) continue;
      const g = groups.get(c.l1) || { l1: c.l1, enabled: true, children: [] };
      g.children.push({ ...clone(c), ref_count: db.transactions.filter((t) => t.category_l1 === c.l1 && t.category_l2 === c.l2).length });
      groups.set(c.l1, g);
    }
    return [...groups.values()];
  }

  if (method === 'POST' && path === '/categories') {
    if (!body.l1 || !body.l2) fail('E2008', '一级与二级分类都不能为空');
    if (db.categories.some((c) => c.l1 === body.l1 && c.l2 === body.l2)) fail('E2005', '该分类已存在，请换一个名称');
    const c = { id: `CAT-${String(db.categories.length + 1).padStart(3, '0')}`, l1: body.l1, l2: body.l2, sort: body.sort ?? 999, enabled: true, is_builtin: false, created_at: iso(new Date()) };
    db.categories.push(c);
    persist();
    return clone(c);
  }

  if (method === 'PATCH' && /^\/categories\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const c = db.categories.find((x) => x.id === id);
    if (!c) fail('E2006', '分类不存在');
    if (body.l2 && db.categories.some((x) => x.l1 === c.l1 && x.l2 === body.l2 && x.id !== id)) fail('E2005', '同一级下已有同名分类');
    if (body.l2) c.l2 = body.l2;
    if (body.sort !== undefined) c.sort = body.sort;
    if (body.enabled !== undefined) c.enabled = !!body.enabled;
    persist();
    return clone(c);
  }

  if (method === 'POST' && /^\/categories\/[^/]+\/disable$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2]);
    const c = db.categories.find((x) => x.id === id);
    if (!c) fail('E2006', '分类不存在');
    if (c.l1 === body.migrate_to_l1 && c.l2 === body.migrate_to_l2) fail('E2006', '不能迁移到自身');
    const target = db.categories.find((x) => x.enabled && x.l1 === body.migrate_to_l1 && x.l2 === body.migrate_to_l2);
    if (!target) fail('E2006', '迁移目标不存在或已停用');
    let migrated = 0;
    for (const t of db.transactions) {
      if (t.category_l1 === c.l1 && t.category_l2 === c.l2) {
        t.category_l1 = target.l1; t.category_l2 = target.l2; migrated += 1;
      }
    }
    c.enabled = false;
    persist();
    return { migrated };
  }

  /* ---- 重算 ---- */
  if (method === 'POST' && (path === '/recalc/preview' || path === '/recalc')) {
    const scope = body.scope || 'all';
    if (scope === 'batch' && !body.batch_id) fail('E2011', '按批次重算必须指定批次');
    if (scope === 'rules' && !(body.rule_ids || []).length) fail('E2011', '按规则重算必须指定规则');
    let rows = db.transactions.filter((t) => ['pending', 'confirmed', 'corrected', 'excluded'].includes(t.status));
    if (scope === 'batch') rows = rows.filter((t) => t.batch_id === body.batch_id);
    if (scope === 'rules') {
      const ids = body.rule_ids;
      const keywords = db.rules.filter((r) => ids.includes(r.id)).flatMap((r) => r.keyword.split('|'));
      rows = rows.filter((t) => keywords.some((k) => k && `${t.counterparty || ''}${t.item || ''}`.toLowerCase().includes(k.toLowerCase())));
    }
    const manualKept = rows.filter((t) => (t.status === 'corrected' || t.status === 'excluded') && !body.overwrite_manual).length;
    const toRecalc = rows.length - manualKept;
    if (path === '/recalc/preview') return { to_recalc: toRecalc, manual_kept: manualKept, scope };
    if (body.confirm !== true) fail('E2008', '重算需要二次确认');
    let updated = 0, kept = 0, unchanged = 0;
    for (const t of rows) {
      if ((t.status === 'corrected' || t.status === 'excluded') && !body.overwrite_manual) { kept += 1; continue; }
      const cls = classify(t);
      const nextStatus = cls.status === 'confirmed' ? 'confirmed' : 'pending';
      if (t.category_l1 === cls.category_l1 && t.category_l2 === cls.category_l2 && t.status === nextStatus) { unchanged += 1; continue; }
      t.category_l1 = cls.category_l1; t.category_l2 = cls.category_l2; t.status = nextStatus;
      t.updated_at = iso(new Date());
      updated += 1;
    }
    persist();
    return { updated, manual_kept: kept, unchanged, scope, finished_at: iso(new Date()) };
  }

  /* ---- 设置 ---- */
  if (method === 'GET' && path === '/settings') return clone(db.settings);

  if (method === 'PUT' && path === '/settings') {
    const allowed = ['single_day_threshold_cents', 'backup_interval_days', 'week_start', 'event_log_enabled', 'buffer_threshold_bytes', 'theme'];
    for (const [k, v] of Object.entries(body)) {
      if (!allowed.includes(k)) fail('E2008', `不支持的设置项：${k}`);
      if (k === 'single_day_threshold_cents' && (!Number.isInteger(v) || v <= 0)) fail('E2008', '单日阈值必须是大于 0 的整数（分）');
      if (k === 'backup_interval_days' && (!Number.isInteger(v) || v < 1)) fail('E2008', '备份提醒间隔必须 ≥ 1 天');
      if (k === 'week_start' && ![0, 1].includes(v)) fail('E2008', '每周起始日只能是周一或周日');
      if (k === 'buffer_threshold_bytes' && (!Number.isInteger(v) || v <= 0)) fail('E2008', '缓冲区阈值必须大于 0');
    }
    Object.assign(db.settings, body, { updated_at: iso(new Date()) });
    persist();
    return clone(db.settings);
  }

  if (method === 'POST' && path === '/settings/data-dir/validate') {
    const raw = String(body.path || '').trim();
    if (!raw) return { valid: false, resolved: '', reason: '请填写数据目录路径' };
    if (/^(\\\\|\/\/)/.test(raw) || /^[a-zA-Z]:\\\\/.test(raw)) return { valid: false, resolved: raw, reason: '不能指向网络位置，请选择本机磁盘路径' };
    if (!/^[a-zA-Z]:[\\/]/.test(raw) && !raw.startsWith('/')) return { valid: false, resolved: raw, reason: '必须是绝对路径，例如 D:\\finance-data' };
    if (/^[a-zA-Z]:[\\/](Windows|Program Files|ProgramData)/i.test(raw)) return { valid: false, resolved: raw, reason: '不能使用系统目录，请选择普通数据目录' };
    if (raw.length < 4) return { valid: false, resolved: raw, reason: '路径过短，请选择具体目录' };
    return { valid: true, resolved: raw.replace(/[\\/]+$/, ''), reason: null };
  }

  if (method === 'POST' && path === '/settings/data-dir/migrate') {
    if (!body.to) fail('E1011', '目标目录不能为空');
    if (body.to === db.settings.data_dir) fail('E1011', '目标目录与当前目录相同，无需迁移');
    if (body.confirm !== true) fail('E2008', '迁移需要二次确认');
    const from = db.settings.data_dir;
    db.settings.data_dir = body.to;
    db.settings.updated_at = iso(new Date());
    persist();
    return { from, to: body.to, migrated_bytes: db.batches.reduce((s, b) => s + b.file_size, 0) + 4404019, restarted_required: !body.copy_only };
  }

  /* ---- 备份 ---- */
  if (method === 'POST' && path === '/backup/db') {
    const id = `BK-${String(db.backups.length + 1).padStart(3, '0')}`;
    const name = `finance-${dateIso(new Date())}.sqlite`;
    const b = {
      id, kind: 'db', file_name: name, file_path: `backups/${name}`,
      size_bytes: 4500000, checksum: 'sha256:' + Math.random().toString(16).slice(2, 6) + '…',
      row_counts: { transaction: db.transactions.length, raw: Object.values(db.raw).reduce((s, r) => s + r.length, 0) },
      created_at: iso(new Date()), restored_at: null,
    };
    db.backups.unshift(b);
    persist();
    return clone(b);
  }

  if (method === 'GET' && path === '/backup') {
    const items = db.backups.slice().sort((a, b) => b.created_at.localeCompare(a.created_at));
    const dbs = items.filter((b) => b.kind === 'db' || b.kind === 'pre_restore');
    const last = dbs[0]?.created_at || null;
    const days = last ? Math.floor((Date.now() - new Date(last).getTime()) / 86400000) : null;
    return { items, last_at: last, overdue: days == null ? true : days > db.settings.backup_interval_days, interval_days: db.settings.backup_interval_days };
  }

  if (method === 'POST' && path === '/backup/restore/validate') {
    const b = db.backups.find((x) => x.file_name === body.file_name);
    if (!b) return { valid: false, reason: '找不到该备份文件，可能已被移动或删除' };
    if (b.kind === 'export_csv' || b.kind === 'export_json') return { valid: false, reason: '全量导出文件不能用于数据库恢复，请选择 .sqlite 备份' };
    return {
      valid: true, schema_version: 1,
      counts: { transactions: b.row_counts?.transaction || 0, raw_records: b.row_counts?.raw || 0, rules: db.rules.length, categories: db.categories.length },
      reason: null,
    };
  }

  if (method === 'POST' && path === '/backup/restore') {
    const b = db.backups.find((x) => x.file_name === body.file_name);
    if (!b) fail('E4005', '备份文件无效或不存在');
    if (body.confirm !== true) fail('E2008', '恢复需要二次确认');
    const pre = {
      id: `BK-${String(db.backups.length + 1).padStart(3, '0')}`,
      kind: 'pre_restore', file_name: `rollback-${dateIso(new Date()).replace(/-/g, '')}.sqlite`,
      file_path: 'backups/rollback.sqlite', size_bytes: 4500000, checksum: 'sha256:pre…',
      row_counts: { transaction: db.transactions.length }, created_at: iso(new Date()), restored_at: null,
    };
    db.backups.unshift(pre);
    db.last_restore = { pre_backup_id: pre.id, from: b.file_name, at: iso(new Date()) };
    b.restored_at = iso(new Date());
    persist();
    return { restored: true, pre_backup_id: pre.id, restored_from: b.file_name, counts: pre.row_counts, finished_at: iso(new Date()) };
  }

  if (method === 'POST' && path === '/backup/restore/rollback') {
    if (!db.last_restore || db.last_restore.pre_backup_id !== body.pre_backup_id) fail('E4007', '回退点不存在或已被清理');
    const pre = db.backups.find((x) => x.id === body.pre_backup_id);
    if (!pre) fail('E4007', '回退点不存在');
    return { restored: true, restored_from: pre.file_name, counts: pre.row_counts || {}, finished_at: iso(new Date()) };
  }

  if (method === 'POST' && path === '/backup/export') {
    const fmt = body.format === 'csv' ? 'csv' : 'json';
    const name = `export-${dateIso(new Date())}.${fmt}`;
    return { file_name: name, path: `backups/${name}`, rows: db.transactions.length };
  }

  /* ---- 维护 ---- */
  if (method === 'GET' && path === '/maintenance/cleanup') {
    const st = qv('status', 'pending');
    return clone(db.cleanup.filter((c) => c.status === st));
  }

  if (method === 'POST' && /^\/maintenance\/cleanup\/[^/]+\/retry$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[3]);
    const c = db.cleanup.find((x) => x.id === id);
    if (!c) fail('E4003', '待清理项不存在');
    c.attempts += 1;
    c.updated_at = iso(new Date());
    if (c.attempts >= 3) { c.status = 'abandoned'; c.last_error = '文件持续被占用，请手动删除'; }
    else { c.status = 'pending'; }
    persist();
    return clone(c);
  }

  if (method === 'GET' && path === '/maintenance/events') {
    if (!db.settings.event_log_enabled) return [];
    return clone(db.events.slice(0, Number(qv('limit', 100))));
  }

  fail('E5001', `本地数据源未实现该接口：${method} ${path}`);
}

/* 规则命中判断（与 classify 保持一致，用于命中数展示） */
function matchRule(tx, r) {
  if (!r.enabled) return false;
  const fields = r.match_field === 'any'
    ? [tx.counterparty || '', tx.item || '', tx.txn_type || '']
    : [tx[r.match_field] || ''];
  return fields.some((f) => r.keyword.split('|').some((kw) => kw && f.toLowerCase().includes(kw.toLowerCase())));
}
