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
  td.wrap{white-space:normal}
  .empty{color:var(--sub);font-size:13px;padding:8px 2px}
  .baseline{background:#2a2410;border:1px solid #5a4d18;color:#e8d27a;
    padding:10px 14px;border-radius:10px;font-size:13px;margin-bottom:14px}
  details{margin:6px 0 14px}
  summary{cursor:pointer;color:var(--accent);font-size:13px;padding:6px 0}
  .full td:first-child{white-space:normal}
  .page{display:none} .page.active{display:block}
  footer{color:var(--sub);font-size:12px;text-align:center;margin-top:30px}
  a{color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📊 主動型 ETF 每日持股追蹤</h1>
    <span class="meta" id="genAt"></span>
  </header>
  <div class="tabs" id="tabs"></div>
  <div id="pages"></div>
  <footer>
    資料來源：MoneyDJ 理財網 ｜ 紅=買入/新增，綠=賣出/剔除（依台股慣例）<br>
    比對基準為「資料日期」變化，非日曆日。
  </footer>
</div>

<script id="payload" type="application/json">/*__DATA__*/</script>
<script>
const DATA = JSON.parse(document.getElementById('payload').textContent);
const fmt = n => (n==null?'':Number(n).toLocaleString());
const delta = n => (n>0?'+':'') + Number(n).toLocaleString();

document.getElementById('genAt').textContent = '更新時間：' + DATA.generated_at;

function rowsBuySell(list, kind){
  if(!list.length) return '<div class="empty">— 無 —</div>';
  const cls = kind==='buy'?'buy':'sell';
  return `<table><thead><tr>
      <th>個股</th><th class="num">變化股數</th><th class="num">→ 持有</th><th class="num">比例%</th>
    </tr></thead><tbody>` +
    list.map(c=>`<tr>
      <td>${c.name}<span class="pill"> ${c.ticker}</span>${c.is_new?'<span class="tag new">新增</span>':''}${c.is_removed?'<span class="tag rm">剔除</span>':''}</td>
      <td class="num ${cls}">${delta(c.delta)}</td>
      <td class="num">${fmt(c.new_shares)}</td>
      <td class="num">${c.pct.toFixed(2)}</td>
    </tr>`).join('') + `</tbody></table>`;
}

function rowsAddRm(list, kind){
  if(!list.length) return '<div class="empty">— 無 —</div>';
  if(kind==='add'){
    return `<table><thead><tr><th>個股</th><th class="num">持有股數</th><th class="num">比例%</th></tr></thead><tbody>`+
      list.map(x=>`<tr><td>${x.name}<span class="pill"> ${x.ticker}</span></td>
        <td class="num buy">${fmt(x.shares)}</td><td class="num">${x.pct.toFixed(2)}</td></tr>`).join('')+`</tbody></table>`;
  }
  return `<table><thead><tr><th>個股</th><th class="num">原持股</th></tr></thead><tbody>`+
    list.map(x=>`<tr><td>${x.name}<span class="pill"> ${x.ticker}</span></td>
      <td class="num sell">${fmt(x.old_shares)}</td></tr>`).join('')+`</tbody></table>`;
}

function fullTable(holdings){
  return `<table class="full"><thead><tr><th>個股</th><th class="num">比例%</th><th class="num">持有股數</th></tr></thead><tbody>`+
    holdings.map(h=>`<tr><td>${h.name}<span class="pill"> ${h.ticker}</span></td>
      <td class="num">${h.pct.toFixed(2)}</td><td class="num">${fmt(h.shares)}</td></tr>`).join('')+
    `</tbody></table>`;
}

function renderEtf(e){
  const d = e.diff;
  const baseline = e.is_baseline
    ? `<div class="baseline">⚠️ 這是第一次建立基準（目前只有一份資料日期 ${e.data_date}）。等下一次資料日期更新後，就會自動顯示新增 / 剔除 / 買賣前五。</div>`
    : '';
  const cmp = e.is_baseline ? '' : `（對比 ${e.prev_date} → ${e.data_date}）`;
  const stale = (e.is_current === false)
    ? `<div class="baseline">⏳ 此檔來源（MoneyDJ）資料日期為 ${e.data_date}，尚未更新到最新交易日。系統每小時會再試，更新到當日後此處會自動刷新。</div>`
    : '';
  return `<div class="card">
    <h2>${e.fund_name} <span class="pill">${e.etfid}</span></h2>
    <div class="sub">資料日期 ${e.data_date}　持股 ${e.holdings_count} 檔　${cmp}</div>
    ${stale}${baseline}
    <div class="grid">
      <div class="box"><h3>🔴➕ 新增標的 <span class="pill">${d.added.length}</span></h3>${rowsAddRm(d.added,'add')}</div>
      <div class="box"><h3>🟢➖ 剔除持股 <span class="pill">${d.removed.length}</span></h3>${rowsAddRm(d.removed,'rm')}</div>
      <div class="box"><h3>🔴 今日買入前五</h3>${rowsBuySell(d.buys,'buy')}</div>
      <div class="box"><h3>🟢 今日賣出前五</h3>${rowsBuySell(d.sells,'sell')}</div>
    </div>
    <details><summary>展開完整持股（${e.holdings_count} 檔）</summary>${fullTable(e.holdings)}</details>
  </div>`;
}

// ===== 跨 ETF 共同動作 =====
const shortName = n => n.replace(/^主動/,'');

function consTable(list, kind){
  const th = DATA.consensus.threshold;
  if(!list.length) return `<div class="empty">— 今日沒有 ${th} 家以上同步${kind==='buy'?'買進/新增':'賣出/剔除'} —</div>`;
  const cls = kind==='buy'?'buy':'sell';
  return `<table><thead><tr>
      <th>個股</th><th class="num">家數</th><th>哪幾檔 ETF（變化股數）</th>
    </tr></thead><tbody>` +
    list.map(x=>`<tr>
      <td>${x.name}<span class="pill"> ${x.ticker}</span></td>
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

// ===== 分頁建立 =====
const tabs = document.getElementById('tabs');
const pages = document.getElementById('pages');

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
  };
  tabs.appendChild(t); pages.appendChild(p);
}

if(DATA.consensus) addTab('🤝 共同動作', renderConsensus(DATA.consensus), true);
DATA.etfs.forEach((e,i)=> addTab(e.fund_name, renderEtf(e), !DATA.consensus && i===0));
if(!DATA.etfs.length){ pages.innerHTML='<div class="empty">沒有資料，請先執行 python3 etf_tracker.py</div>'; }
</script>
</body>
</html>"""
