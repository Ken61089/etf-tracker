# -*- coding: utf-8 -*-
"""產生自包含的網頁儀表板（資料直接內嵌，點兩下即可開啟，免伺服器）。"""

import json


def _fmt(n):
    return f"{n:,}"


def _delta(n):
    sign = "+" if n > 0 else ""
    return f"{sign}{n:,}"


def render(payload):
    data_json = json.dumps(payload, ensure_ascii=False)
    return PAGE.replace("/*__DATA__*/", data_json)


PAGE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>主動型 ETF 每日持股追蹤</title>
<style>
  :root{
    --bg:#0f1115; --card:#181b22; --line:#262b36; --txt:#e6e9ef; --sub:#9aa4b2;
    --buy:#ef4444; --buy-bg:#3a1d1f; --sell:#22c55e; --sell-bg:#16301f;
    --accent:#5b8cff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--txt);
    font-family:-apple-system,"PingFang TC","Microsoft JhengHei",Helvetica,Arial,sans-serif;
    line-height:1.5;padding:24px 16px 64px}
  .wrap{max-width:1100px;margin:0 auto}
  header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-bottom:8px}
  h1{font-size:22px;margin:0}
  .meta{color:var(--sub);font-size:13px}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}
  .tab{padding:8px 14px;border:1px solid var(--line);border-radius:999px;
    background:var(--card);color:var(--sub);cursor:pointer;font-size:14px}
  .tab.active{color:#fff;border-color:var(--accent);background:#1d2740}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:18px 18px 6px;margin-bottom:22px}
  .card h2{font-size:18px;margin:0 0 2px}
  .card .sub{color:var(--sub);font-size:13px;margin-bottom:14px}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:720px){.grid{grid-template-columns:1fr}}
  .box{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:#13161c}
  .box h3{font-size:14px;margin:0 0 10px;display:flex;align-items:center;gap:6px}
  .pill{font-size:11px;color:var(--sub);font-weight:400}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--sub);font-weight:500;font-size:12px}
  td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
  .buy{color:var(--buy)} .sell{color:var(--sell)}
  .tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:5px;margin-left:6px}
  .tag.new{background:var(--buy-bg);color:var(--buy)}
  .tag.rm{background:var(--sell-bg);color:var(--sell)}
  .chip{display:inline-block;font-size:11px;padding:2px 7px;border-radius:6px;
    margin:2px 3px 2px 0;border:1px solid var(--line);white-space:nowrap}
  .chip.buy{background:var(--buy-bg);color:#ffb4b4;border-color:#5a2a2c}
  .chip.sell{background:var(--sell-bg);color:#a7e8bf;border-color:#1f5236}
  .chip.trust{background:#2a2410;color:#e8d27a;border-color:#5a4d18}
  td.wrap{white-space:normal}
  .empty{color:var(--sub);font-size:13px;padding:8px 2px}
  .baseline{background:#2a2410;border:1px solid #5a4d18;color:#e8d27a;
    padding:10px 14px;border-radius:10px;font-size:13px;margin-bottom:14px}
  details{margin:6px 0 14px}
  summary{cursor:pointer;color:var(--accent);font-size:13px;padding:6px 0}
  .full td:first-child{white-space:normal}
  .page{display:none} .page.active{display:block}
  .unit-sw{display:inline-flex;margin-left:10px;border:1px solid var(--line);
    border-radius:8px;overflow:hidden;vertical-align:middle}
  .unit-sw button{background:transparent;color:var(--sub);border:0;cursor:pointer;
    font-size:12px;padding:4px 12px;font-family:inherit}
  .unit-sw button.on{background:var(--accent);color:#0b0d10;font-weight:600}
  /* 小宇式動作清單 */
  .fbar{display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 12px}
  .fchip{padding:6px 12px;border:1px solid var(--line);border-radius:10px;background:#13161c;
    color:var(--txt);cursor:pointer;font-size:14px;font-family:inherit}
  .fchip b{color:var(--sub);font-weight:400;margin-left:4px;font-variant-numeric:tabular-nums}
  .fchip.on{background:#0f766e;border-color:#14b8a6;color:#fff}
  .fchip.on b{color:#d5fff9}
  .alist{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:14px}
  .ahead,.arow{display:grid;grid-template-columns:28px minmax(0,1fr) 78px 64px 72px;
    gap:8px;align-items:start;padding:10px 12px}
  .ahead{color:var(--sub);font-size:12px;border-bottom:1px solid var(--line)}
  .ahead span{cursor:pointer;user-select:none;text-align:right}
  .ahead span.on{color:#2dd4bf;font-weight:600}
  .ahead span:nth-child(-n+2){text-align:left;cursor:default}
  .arow{border-top:1px solid var(--line);font-variant-numeric:tabular-nums}
  .arow:first-of-type{border-top:0}
  .arow .rk{color:var(--sub);font-size:13px;padding-top:2px}
  .arow .nm{border-left:3px solid transparent;padding-left:8px;min-width:0}
  .arow.add .nm,.arow.new .nm{border-left-color:var(--buy)}
  .arow.reduce .nm,.arow.clear .nm{border-left-color:var(--sell)}
  .arow .nm b{font-size:15px}
  .arow .cd{color:var(--sub);font-size:12px;margin:0 4px}
  .arow .nb{font-size:11px;font-weight:600;margin-right:3px}
  .arow .r{text-align:right;font-size:14px;padding-top:2px}
  .arow .ln2{grid-column:2/-1;font-size:12px;color:var(--sub);margin:-4px 0 0 11px;white-space:normal}
  .act{display:inline-block;font-size:11px;padding:1px 6px;border-radius:5px;margin-right:6px;font-weight:600}
  .act.add,.act.new{background:var(--buy-bg);color:var(--buy)}
  .act.reduce,.act.clear{background:var(--sell-bg);color:var(--sell)}
  @media(max-width:560px){.ahead,.arow{grid-template-columns:22px minmax(0,1fr) 60px 52px 56px;gap:6px;padding:9px 8px}
    .arow .r{font-size:13px}}
  footer{color:var(--sub);font-size:12px;text-align:center;margin-top:30px}
  a{color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📊 主動型 ETF 每日持股追蹤</h1>
    <span class="meta" id="genAt"></span>
    <span class="unit-sw" id="unitSw">
      <button data-u="shares">股</button><button data-u="lots">張</button>
    </span>
  </header>
  <div class="tabs" id="tabs"></div>
  <div id="pages"></div>
  <footer>
    資料來源：ETF 持股＝籌碼小宇（備援 MoneyDJ 理財網）、投信買賣超＝富邦 DJ ｜ 紅=買入/新增，綠=賣出/剔除（依台股慣例）<br>
    比對基準為「資料日期」變化，非日曆日。
  </footer>
</div>

<script id="payload" type="application/json">/*__DATA__*/</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
// 單位切換:股(原始資料) / 張(=股/1000,零股會有小數)。選擇記在 localStorage。
let UNIT = (localStorage.getItem('etfUnit') === 'lots') ? 'lots' : 'shares';
const unitName = () => (UNIT === 'lots' ? '張' : '股');
function numStr(n){
  if(n==null) return '';
  const v = Number(n);
  if(UNIT === 'lots') return (v/1000).toLocaleString(undefined,{maximumFractionDigits:2});
  return v.toLocaleString();
}
const fmt = n => (n==null?'':numStr(n));
const delta = n => (n>0?'+':'') + numStr(n);

document.getElementById('genAt').textContent = '更新時間：' + DATA.generated_at;

// ===== 各 ETF:小宇式「全部/新增/加碼/減碼/出清」清單 =====
const ACTS = [['all','全部'],['new','新增'],['add','加碼'],['reduce','減碼'],['clear','出清']];
const ACT_LABEL = {new:'新增', add:'加碼', reduce:'減碼', clear:'出清'};
const VIEW = {};   // etfid -> {f:篩選, k:排序欄, d:方向}
const sgn = (v,dig=2) => (v>0?'+':'') + v.toFixed(dig);

function actList(e){
  const v = VIEW[e.etfid] || (VIEW[e.etfid] = {f:'all', k:'mv', d:-1});
  let rows = e.rows.filter(r => v.f==='all' || r.act===v.f);
  const key = r => (v.k==='mv' ? (r.mv ?? -1) : v.k==='pct' ? r.pct : r.shares);
  rows = rows.slice().sort((a,b)=> (key(a)-key(b))*v.d || Math.abs(b.delta)-Math.abs(a.delta));
  const arrow = k => v.k===k ? (v.d<0?' ▾':' ▴') : ' ⇅';
  const head = `<div class="ahead"><span>#</span><span>標的</span>
    <span class="${v.k==='mv'?'on':''}" data-sort="mv">市值億${arrow('mv')}</span>
    <span class="${v.k==='pct'?'on':''}" data-sort="pct">權重${arrow('pct')}</span>
    <span class="${v.k==='shares'?'on':''}" data-sort="shares">${unitName()}數${arrow('shares')}</span></div>`;
  if(!rows.length) return `<div class="alist">${head}<div class="empty" style="padding:12px">— 無 —</div></div>`;
  return `<div class="alist">${head}` + rows.map((r,i)=>{
    const buy = r.delta>0;
    const nb = (r.nbuy?`<span class="nb buy">買${r.nbuy}</span>`:'') + (r.nsell?`<span class="nb sell">賣${r.nsell}</span>`:'');
    const ln2 = r.act==='hold' ? '' : `<div class="ln2"><span class="act ${r.act}">${ACT_LABEL[r.act]}</span>`+
      `<span class="${buy?'buy':'sell'}">${delta(r.delta)} ${unitName()}</span>`+
      (r.dmoney!=null?` · <span class="${buy?'buy':'sell'}">${sgn(r.dmoney)} 億</span>`:'')+
      (r.dpct!=null?` · 權重 <span class="${r.dpct>0?'buy':r.dpct<0?'sell':''}">${sgn(r.dpct)}%</span>`:'')+`</div>`;
    return `<div class="arow ${r.act}"><span class="rk">${i+1}</span>
      <div class="nm"><b>${r.name}</b><span class="cd">${r.ticker}</span>${nb}</div>
      <span class="r">${r.mv!=null?r.mv.toFixed(2):'—'}</span>
      <span class="r">${r.pct.toFixed(2)}%</span>
      <span class="r">${fmt(r.shares)}</span>${ln2}</div>`;
  }).join('') + `</div>`;
}

function renderEtf(e){
  const baseline = e.is_baseline
    ? `<div class="baseline">⚠️ 這是第一次建立基準（目前只有一份資料日期 ${e.data_date}）。等下一次資料日期更新後，就會自動顯示新增 / 加碼 / 減碼 / 出清。</div>`
    : '';
  const cmp = e.is_baseline ? '' : `（對比 ${e.prev_date} → ${e.data_date}）`;
  const stale = (e.is_current === false)
    ? `<div class="baseline">⏳ 此檔來源（${e.source==='xiaoyu'?'籌碼小宇':'MoneyDJ'}）資料日期為 ${e.data_date}，尚未更新到最新交易日。系統每小時會再試，更新到當日後此處會自動刷新。</div>`
    : '';
  const v = VIEW[e.etfid] || (VIEW[e.etfid] = {f:'all', k:'mv', d:-1});
  const cnt = k => k==='all' ? e.rows.length : e.rows.filter(r=>r.act===k).length;
  return `<div class="card" data-etf="${e.etfid}">
    <h2>${e.fund_name} <span class="pill">${e.etfid}</span></h2>
    <div class="sub">資料日期 ${e.data_date}　持股 ${e.holdings_count} 檔　${cmp}　來源 ${e.source==='xiaoyu'?'籌碼小宇':'MoneyDJ（備援）'}</div>
    ${stale}${baseline}
    <div class="fbar">${ACTS.map(([k,l])=>`<button class="fchip ${v.f===k?'on':''}" data-f="${k}">${l}<b>${cnt(k)}</b></button>`).join('')}</div>
    <div class="alist-wrap">${actList(e)}</div>
    <div class="sub">市值＝持有股數 × 當日收盤價；金額為小宇估算的買賣金額；買N／賣N＝追蹤的 ${DATA.etfs.length} 檔中當天有幾檔加碼／減碼。完整持股每日存檔於 <a href="archive/${e.etfid}.csv">archive/${e.etfid}.csv</a>。</div>
  </div>`;
}

// 篩選 / 排序點擊(事件委派,只重繪該檔清單)
document.addEventListener('click', ev=>{
  const card = ev.target.closest('.card[data-etf]');
  if(!card) return;
  const e = DATA.etfs.find(x=>x.etfid===card.dataset.etf);
  const v = VIEW[e.etfid];
  const f = ev.target.closest('[data-f]'), so = ev.target.closest('[data-sort]');
  if(f){ v.f = f.dataset.f;
    card.querySelectorAll('.fchip').forEach(b=>b.classList.toggle('on', b===f)); }
  else if(so){ const k = so.dataset.sort; v.d = (v.k===k) ? -v.d : -1; v.k = k; }
  else return;
  card.querySelector('.alist-wrap').innerHTML = actList(e);
});

// ===== 跨 ETF 共同動作 =====
const shortName = n => n.replace(/^主動/,'');
// 投信買賣超查表(只在投信資料日期 = ETF 資料日期時才標)
const TRUST_MAP = {};
if(DATA.trust){
  ['twse','tpex'].forEach(k=>['buy','sell'].forEach(side=>
    (DATA.trust[k]?.[side]||[]).forEach(r=>{ TRUST_MAP[r.ticker] = r; })));
}
function trustChip(ticker, etfDate){
  const r = TRUST_MAP[ticker];
  if(!r || (etfDate && DATA.trust.data_date !== etfDate)) return '';
  return `<span class="chip trust">🏦 投信${r.lots>0?'買超':'賣超'} ${r.lots.toLocaleString()} 張</span>`;
}
const latestEtfDate = () => DATA.etfs.reduce((m,e)=>e.data_date>m?e.data_date:m,'');

function consTable(list, kind){
  const th = DATA.consensus.threshold;
  if(!list.length) return `<div class="empty">— 今日沒有 ${th} 家以上同步${kind==='buy'?'買進/新增':'賣出/剔除'} —</div>`;
  const cls = kind==='buy'?'buy':'sell';
  return `<table><thead><tr>
      <th>個股</th><th class="num">家數</th><th>哪幾檔 ETF（變化${unitName()}數）</th>
    </tr></thead><tbody>` +
    list.map(x=>`<tr>
      <td>${x.name}<span class="pill"> ${x.ticker}</span><br>${trustChip(x.ticker, latestEtfDate())}</td>
      <td class="num ${cls}" style="font-weight:600">${x.count} 家${x.flag_count?`<br><span class="pill">${kind==='buy'?'🆕 新進':'✖ 剔除'} ${x.flag_count}</span>`:''}</td>
      <td class="wrap">${x.etfs.map(e=>`<span class="chip ${cls}">${shortName(e.fund_name)} ${delta(e.delta)}${e.is_new?' 🆕':''}${e.is_removed?' ✖':''}</span>`).join('')}</td>
    </tr>`).join('') + `</tbody></table>`;
}

function divTable(list){
  if(!list.length) return `<div class="empty">— 今日沒有同一檔同時被買進與賣出 —</div>`;
  return `<table><thead><tr>
      <th>個股</th><th>🔴 買進方</th><th>🟢 賣出方</th>
    </tr></thead><tbody>` +
    list.map(x=>`<tr>
      <td>${x.name}<span class="pill"> ${x.ticker}</span><br><span class="pill">${x.buy_count}買 / ${x.sell_count}賣</span></td>
      <td class="wrap">${x.buyers.map(e=>`<span class="chip buy">${shortName(e.fund_name)} ${delta(e.delta)}${e.is_new?' 🆕':''}</span>`).join('')}</td>
      <td class="wrap">${x.sellers.map(e=>`<span class="chip sell">${shortName(e.fund_name)} ${delta(e.delta)}${e.is_removed?' ✖':''}</span>`).join('')}</td>
    </tr>`).join('') + `</tbody></table>`;
}

function renderConsensus(c){
  if(!c.has_data){
    return `<div class="card"><h2>🤝 跨 ETF 共同動作</h2>
      <div class="baseline">⚠️ 目前各檔多為首次建立基準，還沒有可比對的變化。等資料日期更新、且有至少一檔產生變化後，這裡會列出「多檔 ETF 在同一天對同一檔股票做出相同動作」的個股。</div></div>`;
  }
  const none = (!c.buy.length && !c.sell.length)
    ? `<div class="baseline">今日沒有 ${c.threshold} 家以上 ETF 對同一檔股票做出相同方向的動作。</div>` : '';
  return `<div class="card">
    <h2>🤝 跨 ETF 共同動作 <span class="pill">${c.threshold} 家以上同動作</span></h2>
    <div class="sub">同一天有多檔 ETF 對同一檔股票做出相同方向（買進 / 賣出）的動作，視為投信共識訊號。家數越多訊號越強。</div>
    ${none}
    <div class="grid">
      <div class="box"><h3>🔴 多檔同步買進 / 新增 <span class="pill">${c.buy.length}</span></h3>${consTable(c.buy,'buy')}</div>
      <div class="box"><h3>🟢 多檔同步賣出 / 剔除 <span class="pill">${c.sell.length}</span></h3>${consTable(c.sell,'sell')}</div>
    </div>
    <div class="box" style="margin-top:14px"><h3>⚖️ 分歧：同一檔有人買、有人賣 <span class="pill">${(c.diverge||[]).length}</span></h3>${divTable(c.diverge||[])}</div>
  </div>`;
}

// ===== 投信買賣超 =====
function etfChips(list){
  if(!list || !list.length) return '<span class="pill">—</span>';
  return list.map(e=>`<span class="chip ${e.delta>0?'buy':'sell'}">${shortName(e.fund_name)} ${delta(e.delta)}${e.is_new?' 🆕':''}${e.is_removed?' ✖':''}</span>`).join('');
}
function trustTable(list, kind){
  if(!list || !list.length) return '<div class="empty">— 無 —</div>';
  const cls = kind==='buy'?'buy':'sell';
  return `<table><thead><tr>
      <th class="num">#</th><th>個股</th><th class="num">超張數</th><th class="num">收盤</th><th class="num">漲跌</th><th>主動 ETF 同日動作</th>
    </tr></thead><tbody>` +
    list.map(r=>`<tr>
      <td class="num">${r.rank}</td>
      <td>${r.name}<span class="pill"> ${r.ticker}</span></td>
      <td class="num ${cls}">${r.lots.toLocaleString()}</td>
      <td class="num">${r.close}</td>
      <td class="num">${r.chg}</td>
      <td class="wrap">${etfChips(r.etfs)}</td>
    </tr>`).join('') + `</tbody></table>`;
}
function crossTable(list, kind){
  if(!list.length) return `<div class="empty">— 今日沒有投信${kind==='buy'?'買超':'賣超'}且主動 ETF 同步${kind==='buy'?'加碼':'減碼'}的個股 —</div>`;
  const cls = kind==='buy'?'buy':'sell';
  return `<table><thead><tr>
      <th>個股</th><th class="num">投信超張數</th><th>同向的主動 ETF（變化${unitName()}數）</th>
    </tr></thead><tbody>` +
    list.map(r=>`<tr>
      <td>${r.name}<span class="pill"> ${r.ticker}・${r.market}</span></td>
      <td class="num ${cls}" style="font-weight:600">${r.lots.toLocaleString()}<br><span class="pill">${r.etfs.length} 檔 ETF 同向</span></td>
      <td class="wrap">${etfChips(r.etfs)}</td>
    </tr>`).join('') + `</tbody></table>`;
}
function renderTrust(t){
  const other = (t.etf_other_day||[]).length
    ? `<div class="baseline">⏳ 以下 ETF 資料日期與投信（${t.data_date}）不同，未納入交叉比對：${t.etf_other_day.join('、')}</div>` : '';
  const cross = t.cross || {buy:[],sell:[]};
  return `<div class="card">
    <h2>🏦 投信 × 主動 ETF 同向 <span class="pill">${t.data_date}</span></h2>
    <div class="sub">投信買賣超排行（上市＋上櫃前 50）中，追蹤的主動 ETF 當天也同方向加碼／減碼的個股。ETF 家數越多排越前面。</div>
    ${other}
    <div class="grid">
      <div class="box"><h3>🔴 投信買超 ＋ ETF 加碼 <span class="pill">${cross.buy.length}</span></h3>${crossTable(cross.buy,'buy')}</div>
      <div class="box"><h3>🟢 投信賣超 ＋ ETF 減碼 <span class="pill">${cross.sell.length}</span></h3>${crossTable(cross.sell,'sell')}</div>
    </div>
  </div>` + [['twse','上市'],['tpex','上櫃']].map(([k,label])=>`<div class="card">
    <h2>${label}投信買賣超一日排行 <span class="pill">${t.data_date}・單位：張</span></h2>
    <div class="sub">來源：富邦 DJ。最右欄標出追蹤的主動 ETF 當天對該股的加減碼。</div>
    <div class="box" style="margin-bottom:14px"><h3>🔴 買超 <span class="pill">${t[k].buy.length}</span></h3>${trustTable(t[k].buy,'buy')}</div>
    <div class="box" style="margin-bottom:14px"><h3>🟢 賣超 <span class="pill">${t[k].sell.length}</span></h3>${trustTable(t[k].sell,'sell')}</div>
  </div>`).join('');
}

// ===== 分頁建立 =====
const tabs = document.getElementById('tabs');
const pages = document.getElementById('pages');

let ACTIVE = 0;  // 目前分頁,切換單位重繪後要留在原地

function addTab(label, contentHtml, active){
  const idx = document.querySelectorAll('.tab').length;
  const t=document.createElement('div');
  t.className='tab'+(active?' active':''); t.innerHTML=label;
  const p=document.createElement('div');
  p.className='page'+(active?' active':''); p.id='pg'+idx;
  p.innerHTML=contentHtml;
  t.onclick=()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
    t.classList.add('active'); p.classList.add('active');
    ACTIVE = idx;
  };
  tabs.appendChild(t); pages.appendChild(p);
}

// 內容在建立當下就套用目前單位,故切換單位 = 整個重建
function buildAll(){
  tabs.innerHTML=''; pages.innerHTML='';
  if(!DATA.etfs.length && !DATA.consensus){
    pages.innerHTML='<div class="empty">沒有資料，請先執行 python3 etf_tracker.py</div>';
    return;
  }
  if(DATA.consensus) addTab('🤝 共同動作', renderConsensus(DATA.consensus), false);
  if(DATA.trust) addTab('🏦 投信買賣超', renderTrust(DATA.trust), false);
  DATA.etfs.forEach(e=> addTab(e.fund_name, renderEtf(e), false));
  const all = document.querySelectorAll('.tab');
  if(all.length){
    if(ACTIVE >= all.length) ACTIVE = 0;
    all[ACTIVE].click();
  }
}

// 單位切換鈕
const unitSw = document.getElementById('unitSw');
function paintUnitSw(){
  unitSw.querySelectorAll('button').forEach(b=>
    b.classList.toggle('on', b.dataset.u === UNIT));
}
unitSw.querySelectorAll('button').forEach(b=>{
  b.onclick = ()=>{
    if(UNIT === b.dataset.u) return;
    UNIT = b.dataset.u;
    localStorage.setItem('etfUnit', UNIT);
    paintUnitSw();
    buildAll();
  };
});

paintUnitSw();
buildAll();
</script>
</body>
</html>"""
