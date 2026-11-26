#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主動型 ETF 每日持股追蹤系統
----------------------------------
抓取多檔主動型 ETF 的每日持股（主來源籌碼小宇、備援 MoneyDJ），存成快照，
並比較最新與前一份「資料日期不同」的快照，算出：
  1. 新增標的（相較上一份新買進的）
  2. 剔除持股（上一份有、現在完全沒持有的）
  3. 今日買入前五名（持有股數增加最多）
  4. 今日賣出前五名（持有股數減少最多）
另抓富邦 DJ 上市/上櫃投信買賣超一日排行，與 ETF 加減碼交叉比對。
最後產生一個自包含的網頁儀表板 docs/index.html。

用法：
    python3 etf_tracker.py          # 抓資料 + 產生儀表板
    python3 etf_tracker.py --build  # 只用既有快照重新產生儀表板（不重新抓）
"""

import os
import re
import sys
import json
import html
import subprocess
from collections import defaultdict
from datetime import datetime, timezone, timedelta

# ---- 設定 -------------------------------------------------------------

# 要追蹤的 ETF（代號 -> 名稱；名稱僅供參考，實際以網頁 title 自動解析為準）
ETFS = {
    "00401A": "主動摩根台灣鑫收",
    "00403A": "主動統一升級50",
    "00406A": "主動中信台灣收益",
    "00407A": "主動凱基台灣",
    "00408A": "主動第一金優股息",
    "00409A": "主動復華全球50",
    "00410A": "主動永豐科技趨勢",
    "00412A": "主動安聯亞半導體",
    "00418A": "主動復華台灣新星",
    "00981A": "主動統一台股增長",
    "00982A": "主動群益台灣強棒",
    "00985A": "主動野村台灣50",
    "00990A": "主動元大AI新經濟",
    "00991A": "主動復華未來50",
    "00992A": "主動群益科技創新",
    "00993A": "主動安聯台灣",
    "00994A": "主動第一金台股優",
    "00995A": "主動中信台灣卓越",   # 小宇沒收，只有 MoneyDJ
    "00996A": "主動兆豐台灣豐收",   # 小宇沒收，只有 MoneyDJ
}

# 「經理人在想什麼」分析的對象：這兩檔一定納入，其餘依估算規模補滿 TOP_N 檔
TOP_FIXED = ["00981A", "00403A"]
TOP_N = 5

# 主來源：籌碼小宇（每檔一個 JSON，已算好加碼/減碼/新增/出清，單位為「張」）
XY_URL = "https://xiaoyu-etf.pages.dev/data/etf/{etfid}.json"
# 備援來源：MoneyDJ（單位為「股」，加減碼由本系統自行比對）
BASE_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={etfid}.TW"
# 法人買賣超一日排行（富邦 DJ）：A=DD 投信、A=D 外資；B=0 上市、B=1 上櫃；C=1 一日
INST_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A={a}&B={b}&C=1"
INSTS = {"trust": ("投信", "DD"), "foreign": ("外資", "D")}   # 存檔資料夾 data/<key>/
INST_MARKETS = {"twse": ("上市", 0), "tpex": ("上櫃", 1)}
# 外資投信共同買超用全市場三大法人資料（排行只有前 50，交集會漏掉大半）；抓不到才退回富邦排行交集
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json"
TWSE_QUOTE_URL = ("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                  "?date={ymd}&type=ALLBUT0999&response=json")
TPEX_INST_URL = ("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
                 "?type=Daily&sect=EW&date={y}%2F{m}%2F{d}&response=json")
TPEX_QUOTE_URL = ("https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
                  "?date={y}%2F{m}%2F{d}&type=EW&response=json")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")        # 每日快照
SITE_DIR = os.path.join(ROOT, "docs")        # 產生的儀表板（GitHub Pages 用 /docs）

TPE = timezone(timedelta(hours=8))           # 台灣時區
HIST_DAYS = 20                               # 網頁日期切換可回看的資料日數
PX_DIR = os.path.join(DATA_DIR, "_prices")   # 小宇的每日收盤價/均價（算歷史市值與金額用）

# ---- 抓取與解析 -------------------------------------------------------

def curl_bytes(url):
    """用 curl 抓網頁原始位元組（curl 對這些網站的 TLS 最穩定）。"""
    result = subprocess.run(
        [
            "curl", "-s", "--fail", "--max-time", "30",
            "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            url,
        ],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"抓取失敗 (curl exit {result.returncode})：{url}")
    return result.stdout


def fetch_html(etfid):
    return curl_bytes(BASE_URL.format(etfid=etfid)).decode("utf-8")


def fetch_xiaoyu(etfid):
    """從籌碼小宇抓持股快照，並把它算好的「一日」加減碼一起帶回（xy_d1）。

    小宇持股單位是「張」（零股已捨去），這裡換算成股（×1000）以沿用既有快照格式，
    並標 lot_precision=True，比對時會把兩邊都統一成張，避免零股造成假變化。
    """
    d = json.loads(curl_bytes(XY_URL.format(etfid=etfid)).decode("utf-8"))
    if d.get("code") != etfid or not d.get("snap_dates"):
        raise RuntimeError(f"{etfid}: 小宇資料格式不符")
    def ymd(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"

    latest = d["snap_dates"][0]
    names = d.get("names", {})
    prices = d.get("prices", {})      # 每檔收盤價序列，新到舊，與 snap_dates 對齊

    def build(i, sd):
        holdings = {}
        for code, lots, pct in d["snaps"].get(sd) or []:
            h = {"name": names.get(code, code), "pct": float(pct),
                 "shares": int(round(lots * 1000))}
            arr = prices.get(code) or []
            if i < len(arr) and arr[i]:
                h["price"] = float(arr[i])
            holdings[code] = h
        return {"etfid": etfid, "fund_name": ETFS.get(etfid) or etfid,
                "data_date": ymd(sd), "source": "xiaoyu", "lot_precision": True,
                "holdings": holdings}

    snap = build(0, latest)
    if not snap["holdings"]:
        raise RuntimeError(f"{etfid}: 小宇解析不到任何持股")
    # 補存：小宇有、我方沒存過、又比我方最新快照新的日期（例如小宇晚出、我們那幾次只抓到舊的）
    saved = set(list_snapshot_dates(etfid))
    latest_saved = max(saved) if saved else ""
    snap["backfill"] = [
        b for b in (build(i, sd) for i, sd in enumerate(d["snap_dates"]) if i > 0)
        if b["data_date"] > latest_saved and b["data_date"] not in saved and b["holdings"]
    ]
    # 收盤價 / 成交均價序列（新到舊，與 snap_dates 對齊），供歷史日期估市值與買賣金額
    vwaps = d.get("vwaps", {})
    px = defaultdict(dict)
    for i, sd in enumerate(d["snap_dates"]):
        for code, arr in prices.items():
            if i < len(arr) and arr[i]:
                va = vwaps.get(code) or []
                px[ymd(sd)][code] = [arr[i], va[i] if i < len(va) and va[i] else arr[i]]
    save_prices(etfid, px)

    d1 = (d.get("wins") or {}).get("d1") or {}
    # 只有小宇的 d1 正好是「最新快照 vs 前一份」才帶回，否則交給本系統自行比對
    if d1.get("available") and d.get("date") == latest and d1.get("base"):
        snap["xy_d1"] = {"base": ymd(d1["base"]),
                         "buy": d1.get("buy", []), "sell": d1.get("sell", [])}
    return snap


def fetch_snapshot(etfid):
    """主來源小宇；失敗或資料日期落後於今天時，也試 MoneyDJ，取較新者。
    （2026-11-02 小宇隔天早上才出資料，MoneyDJ 當晚已有，舊條件「落後於已存快照」沒觸發）"""
    saved = list_snapshot_dates(etfid)
    latest_saved = saved[-1] if saved else ""
    snap, err = None, None
    try:
        snap = fetch_xiaoyu(etfid)
    except Exception as e:
        err = e
        print(f"  ⚠️  {etfid} 小宇失敗，改用 MoneyDJ：{e}", file=sys.stderr)
    if snap is None or snap["data_date"] < max(latest_saved, today_tpe()):
        try:
            mdj = parse(fetch_html(etfid), etfid)
            mdj["source"] = "moneydj"
            if snap is None or mdj["data_date"] > snap["data_date"]:
                # MoneyDJ 較新時，小宇那份（含它帶的補存）若也比已存的新，一起補存
                if snap is not None:
                    xy_back = snap.pop("backfill", [])
                    if snap["data_date"] > latest_saved:
                        xy_back.append(snap)
                    mdj["backfill"] = xy_back
                snap = mdj
        except Exception as e:
            if snap is None:
                raise RuntimeError(f"{etfid}: 小宇與 MoneyDJ 都失敗（{err}／{e}）")
    return snap


# 解析資料日期，例如 ...sdate3...>2026/06/05
DATE_RE = re.compile(r"sdate3.*?(\d{4}/\d{2}/\d{2})", re.S)

# 解析每一列持股：名稱+代號、投資比例、持有股數
ROW_RE = re.compile(
    r"col05\"><a[^>]*etfid=([0-9A-Za-z]+)\.TW[^>]*>([^<]+)</a></td>"
    r"<td class=\"col06\">([\d.]+)</td>"
    r"<td class=\"col07\">([\d,]+)</td>",
    re.S,
)

def parse(html_text, etfid):
    """從網頁原始碼解析出資料日期與持股清單。"""
    m = DATE_RE.search(html_text)
    if not m:
        raise RuntimeError(f"{etfid}: 找不到資料日期")
    data_date = m.group(1).replace("/", "-")

    # 基金中文名取自網頁 <title>，例如「主動復華未來50-00991A.TW-ETF持股狀況...」
    name_m = re.search(r"<title>\s*(.*?)-" + re.escape(etfid) + r"\.TW", html_text, re.S)
    fund_name = (name_m.group(1).strip() if name_m
                 else (ETFS.get(etfid) or etfid))

    holdings = {}
    for ticker, raw_name, pct, shares in ROW_RE.findall(html_text):
        # raw_name 形如「台積電(2330.TW)」，去掉括號代號
        clean = re.sub(r"\([0-9A-Za-z]+\.TW\)\s*$", "", raw_name).strip()
        holdings[ticker] = {
            "name": html.unescape(clean),
            "pct": float(pct),
            "shares": int(shares.replace(",", "")),
        }
    if not holdings:
        raise RuntimeError(f"{etfid}: 解析不到任何持股（網頁結構可能改了）")
    return {
        "etfid": etfid,
        "fund_name": fund_name,
        "data_date": data_date,
        "holdings": holdings,
    }


# ---- 快照存取 ---------------------------------------------------------

def snapshot_path(etfid, data_date):
    return os.path.join(DATA_DIR, etfid, f"{data_date}.json")


def save_snapshot(snap):
    folder = os.path.join(DATA_DIR, snap["etfid"])
    os.makedirs(folder, exist_ok=True)
    path = snapshot_path(snap["etfid"], snap["data_date"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return path


def load_prices(etfid):
    path = os.path.join(PX_DIR, f"{etfid}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_ALL_PX = None


def load_all_prices():
    """把所有 ETF 的價格檔合併成一份（日期 -> 代號 -> [收盤, 均價]），
    給只有 MoneyDJ 來源、沒有價格的 ETF 估市值用。"""
    global _ALL_PX
    if _ALL_PX is None:
        _ALL_PX = defaultdict(dict)
        if os.path.isdir(PX_DIR):
            for f in sorted(os.listdir(PX_DIR)):
                if f.endswith(".json"):
                    for d, m in load_prices(f[:-5]).items():
                        _ALL_PX[d].update(m)
    return _ALL_PX


def merged_prices(etfid):
    own = load_prices(etfid)
    out = {}
    for d, m in load_all_prices().items():
        out[d] = {**m, **own.get(d, {})}
    for d, m in own.items():
        out.setdefault(d, m)
    return out


def save_prices(etfid, px):
    """與既有價格檔合併（小宇只給近 61 日，舊的要自己留）。"""
    merged = load_prices(etfid)
    for d, m in px.items():
        merged.setdefault(d, {}).update(m)
    os.makedirs(PX_DIR, exist_ok=True)
    with open(os.path.join(PX_DIR, f"{etfid}.json"), "w", encoding="utf-8") as f:
        json.dump(dict(sorted(merged.items())), f, ensure_ascii=False,
                  separators=(",", ":"))


def list_snapshot_dates(etfid):
    folder = os.path.join(DATA_DIR, etfid)
    if not os.path.isdir(folder):
        return []
    dates = [f[:-5] for f in os.listdir(folder) if f.endswith(".json")]
    return sorted(dates)


def load_snapshot(etfid, data_date):
    with open(snapshot_path(etfid, data_date), encoding="utf-8") as f:
        return json.load(f)


# ---- 比對邏輯 ---------------------------------------------------------

def diff_snapshots(prev, curr, top_n=5, lot=None):
    """比較兩份快照，回傳新增 / 剔除 / 買入前五 / 賣出前五。"""
    prev_h = prev["holdings"] if prev else {}
    curr_h = curr["holdings"]
    # 任一邊來自小宇（只到張），兩邊都統一捨成張再比，避免零股差異變成假買賣
    if lot is None:
        lot = bool((prev or {}).get("lot_precision") or curr.get("lot_precision"))

    def sh(info):
        return int(round(info["shares"] / 1000)) * 1000 if lot else info["shares"]

    added, removed, changes = [], [], []

    for ticker, info in curr_h.items():
        old = prev_h.get(ticker)
        old_shares = sh(old) if old else 0
        delta = sh(info) - old_shares
        if old is None:
            added.append({"ticker": ticker, "name": info["name"],
                          "shares": info["shares"], "pct": info["pct"]})
        if delta != 0:
            changes.append({
                "ticker": ticker, "name": info["name"],
                "delta": delta,
                "old_shares": old_shares, "new_shares": info["shares"],
                "pct": info["pct"], "is_new": old is None,
            })

    for ticker, info in prev_h.items():
        if ticker not in curr_h and sh(info) > 0:   # 不足半張的零股出清，以張計等於沒動
            removed.append({"ticker": ticker, "name": info["name"],
                            "old_shares": info["shares"], "pct": info["pct"]})
            changes.append({
                "ticker": ticker, "name": info["name"],
                "delta": -sh(info),
                "old_shares": sh(info), "new_shares": 0,
                "pct": 0.0, "is_removed": True,
            })

    return _pack_diff(added, removed, changes, top_n)


def _pack_diff(added, removed, changes, top_n=5):
    buys = sorted([c for c in changes if c["delta"] > 0],
                  key=lambda c: c["delta"], reverse=True)[:top_n]
    sells = sorted([c for c in changes if c["delta"] < 0],
                   key=lambda c: c["delta"])[:top_n]

    added.sort(key=lambda x: x["shares"], reverse=True)
    removed.sort(key=lambda x: x["old_shares"], reverse=True)
    # changes = 全部有變動的個股（不只前五），供跨 ETF 共同動作分析使用
    return {"added": added, "removed": removed, "buys": buys, "sells": sells,
            "changes": changes}


def diff_from_xiaoyu(curr, top_n=5):
    """直接採用小宇算好的加碼(buy)/減碼(sell)/新增(new)/出清(clear)，轉成既有 diff 格式。
    money = 小宇估算的買賣金額（億元）。"""
    curr_h = curr["holdings"]
    xy = curr["xy_d1"]
    added, removed, changes = [], [], []
    for e in xy["buy"] + xy["sell"]:
        delta = int(e.get("lots") or 0) * 1000
        if delta == 0:          # 只有零股變動（小宇以張計，△張=0）→ 不算買賣
            continue
        t = e["code"]
        cur = curr_h.get(t)
        new_shares = cur["shares"] if cur else 0
        pct = cur["pct"] if cur else 0.0
        name = cur["name"] if cur else e.get("name", t)
        c = {"ticker": t, "name": name, "delta": delta,
             "old_shares": new_shares - delta, "new_shares": new_shares,
             "pct": pct, "money": e.get("money")}
        if e.get("new"):
            c["is_new"] = True
            added.append({"ticker": t, "name": name, "shares": new_shares, "pct": pct})
        if e.get("clear"):
            c["is_removed"] = True
            removed.append({"ticker": t, "name": name,
                            "old_shares": new_shares - delta, "pct": pct})
        changes.append(c)
    return _pack_diff(added, removed, changes, top_n)


def build_consensus(results, threshold=2):
    """跨 ETF 共同動作：找出同一天有 >=threshold 檔 ETF 做相同方向動作的個股。"""
    buy_map = defaultdict(list)   # ticker -> [{etfid, fund_name, delta, is_new}]
    sell_map = defaultdict(list)
    names = {}
    has_data = False

    for r in results:
        if r["is_baseline"]:
            continue
        has_data = True
        for c in r["diff"]["changes"]:
            names[c["ticker"]] = c["name"]
            entry = {
                "etfid": r["etfid"],
                "fund_name": r["fund_name"],
                "delta": c["delta"],
                "is_new": c.get("is_new", False),
                "is_removed": c.get("is_removed", False),
            }
            (buy_map if c["delta"] > 0 else sell_map)[c["ticker"]].append(entry)

    def collect(m, flag_key):
        out = []
        for ticker, lst in m.items():
            if len(lst) >= threshold:
                out.append({
                    "ticker": ticker,
                    "name": names[ticker],
                    "count": len(lst),
                    "flag_count": sum(1 for e in lst if e[flag_key]),
                    "etfs": sorted(lst, key=lambda e: abs(e["delta"]), reverse=True),
                })
        # 先按「同動作家數」多排序，再按「新進/剔除家數」排序
        out.sort(key=lambda x: (x["count"], x["flag_count"]), reverse=True)
        return out

    # 分歧：同一檔同一天有人買、有人賣
    diverge = []
    for ticker in set(buy_map) & set(sell_map):
        buyers = sorted(buy_map[ticker], key=lambda e: abs(e["delta"]), reverse=True)
        sellers = sorted(sell_map[ticker], key=lambda e: abs(e["delta"]), reverse=True)
        diverge.append({
            "ticker": ticker,
            "name": names[ticker],
            "buyers": buyers,
            "sellers": sellers,
            "buy_count": len(buyers),
            "sell_count": len(sellers),
        })
    # 兩邊都越多、越勢均力敵的排前面
    diverge.sort(key=lambda x: (x["buy_count"] + x["sell_count"],
                                min(x["buy_count"], x["sell_count"])), reverse=True)

    return {
        "has_data": has_data,
        "threshold": threshold,
        "buy": collect(buy_map, "is_new"),
        "sell": collect(sell_map, "is_removed"),
        "diverge": diverge,
    }


# ---- 法人買賣超（富邦 DJ：投信、外資）-------------------------------

INST_DATE_RE = re.compile(r"日期：(\d{1,2})/(\d{1,2})")
INST_ROW_RE = re.compile(
    r"Link2Stk\('([^']+)'\)\">([^<]+)</a></td>\s*"
    r"<td class=\"t3n1\">([-\d,]+)</td>\s*"
    r"<td class=\"t3n1\">([\d.,]+)</td>\s*"
    r"<td class=\"t3\w+\">([^<]*)</td>",
    re.S | re.I,
)


def fetch_inst_market(kind, key):
    """抓一個法人、一個市場的買賣超一日排行，回傳 (資料日期, {buy, sell})。
    網頁買超/賣超兩欄交錯排列，以超張數正負號分邊；投信、外資頁面格式相同。"""
    who, a = INSTS[kind]
    label, b = INST_MARKETS[key]
    text = curl_bytes(INST_URL.format(a=a, b=b)).decode("cp950", errors="replace")
    m = INST_DATE_RE.search(text)
    if not m:
        raise RuntimeError(f"{who}{label}：找不到資料日期")
    # 網頁只給月/日，年份用台灣今天推（跨年時月份比今天大 → 去年）
    now = datetime.now(TPE)
    mon, day = int(m.group(1)), int(m.group(2))
    year = now.year - 1 if (mon, day) > (now.month, now.day) else now.year
    data_date = f"{year}-{mon:02d}-{day:02d}"
    buy, sell = [], []
    for code, raw, lots, close, chg in INST_ROW_RE.findall(text):
        name = html.unescape(raw).strip()
        if name.startswith(code):
            name = name[len(code):]
        row = {"ticker": code, "name": name.strip(),
               "lots": int(lots.replace(",", "")),
               "close": float(close.replace(",", "")),
               "chg": chg.strip()}
        (buy if row["lots"] > 0 else sell).append(row)
    if not buy and not sell:
        raise RuntimeError(f"{who}{label}：解析不到任何排行（網頁結構可能改了）")
    for lst in (buy, sell):
        for i, r in enumerate(lst, 1):
            r["rank"] = i
    return data_date, {"buy": buy, "sell": sell}


def update_inst(kind, fetch=True):
    """抓上市+上櫃某法人買賣超，依資料日期存 data/<kind>/<日期>.json；回傳最新一份。"""
    who, _ = INSTS[kind]
    folder = os.path.join(DATA_DIR, kind)
    if fetch:
        snap = {}
        for key, (label, _) in INST_MARKETS.items():
            try:
                d, data = fetch_inst_market(kind, key)
                snap.setdefault("data_date", d)
                if d != snap["data_date"]:
                    raise RuntimeError(f"{who}{label}日期 {d} 與另一市場 {snap['data_date']} 不一致")
                snap[key] = data
                print(f"  ✅ {who}{label} {d}：買超 {len(data['buy'])}、賣超 {len(data['sell'])}",
                      flush=True)
            except Exception as e:
                print(f"  ⚠️  {who}{label} 失敗：{e}", file=sys.stderr)
        if all(k in snap for k in INST_MARKETS):   # 兩市場都成功才存，避免存半份
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f"{snap['data_date']}.json"), "w",
                      encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
    if not os.path.isdir(folder):
        return None
    dates = sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))
    if not dates:
        return None
    with open(os.path.join(folder, f"{dates[-1]}.json"), encoding="utf-8") as f:
        return json.load(f)


def etf_acts(results, date):
    """資料日期 = date 的 ETF 當天加減碼，回傳 (同日 ETF 清單, {代號: [各 ETF 動作]})。"""
    same_day = [r for r in results if not r["is_baseline"] and r["data_date"] == date]
    acts = defaultdict(list)
    for r in same_day:
        for c in r["diff"]["changes"]:
            acts[c["ticker"]].append({
                "fund_name": r["fund_name"], "delta": c["delta"],
                "is_new": c.get("is_new", False),
                "is_removed": c.get("is_removed", False)})
    for lst in acts.values():
        lst.sort(key=lambda e: abs(e["delta"]), reverse=True)
    return same_day, acts


def build_inst_cross(snap, results):
    """法人買賣超 × 主動 ETF 加減碼交叉：只拿資料日期與該法人排行同一天的 ETF 比。
    在每筆排行上掛 etfs（哪幾檔 ETF 當天也有動作），並整理同向清單。"""
    same_day, acts = etf_acts(results, snap["data_date"])
    cross = {"buy": [], "sell": []}
    for key, (label, _) in INST_MARKETS.items():
        for side in ("buy", "sell"):
            for row in snap[key][side]:
                lst = acts.get(row["ticker"], [])
                row["etfs"] = sorted(lst, key=lambda e: abs(e["delta"]), reverse=True)
                same = [e for e in lst if (e["delta"] > 0) == (side == "buy")]
                if same:
                    cross[side].append({**row, "market": label, "etfs": same})
    for side in cross:
        cross[side].sort(key=lambda x: (len(x["etfs"]), abs(x["lots"])), reverse=True)
    snap["cross"] = cross
    snap["etf_same_day"] = [r["etfid"] for r in same_day]
    snap["etf_other_day"] = [f"{r['etfid']}({r['data_date']})" for r in results
                             if r not in same_day]
    return snap


STOCK_RE = re.compile(r"[1-9]\d{3}")   # 4 位數普通股（排除 ETF／債券 ETF／特別股）


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return None


def fetch_full_inst(date):
    """全市場外資（不含外資自營商）＋投信買賣超與收盤價、成交量（單位：股）。
    上市＝證交所 T86＋MI_INDEX，上櫃＝櫃買 dailyTrade＋dailyQuotes；任一份失敗就整個 raise。"""
    y, m, d = date.split("-")
    ymd, roc = y + m + d, f"{int(y) - 1911}/{m}/{d}"
    out = {}
    j = json.loads(curl_bytes(T86_URL.format(ymd=ymd)))
    if j.get("stat") != "OK" or j.get("date") != ymd:
        raise RuntimeError(f"證交所 T86 {date}：{j.get('stat')}（資料日 {j.get('date')}）")
    f = j["fields"]
    fi, ti = f.index("外陸資買賣超股數(不含外資自營商)"), f.index("投信買賣超股數")
    for r in j["data"]:
        out[r[0].strip()] = {"name": r[1].strip(), "market": "上市",
                             "f": int(_num(r[fi])), "t": int(_num(r[ti]))}
    q = json.loads(curl_bytes(TWSE_QUOTE_URL.format(ymd=ymd)))
    tbl = next((t for t in q.get("tables", []) if "收盤價" in t.get("fields", [])), None)
    if not tbl:
        raise RuntimeError(f"證交所收盤行情 {date}：找不到表格")
    f = tbl["fields"]
    ci, vi, si, di = (f.index("收盤價"), f.index("成交股數"),
                      f.index("漲跌(+/-)"), f.index("漲跌價差"))
    for r in tbl["data"]:
        if r[0] in out:
            sign = "-" if "-" in r[si] else ("+" if "+" in r[si] else "")
            out[r[0]].update(close=_num(r[ci]), vol=_num(r[vi]), chg=sign + r[di].strip())
    # 上櫃：欄位名稱重複，只能依位置取。4＝外資及陸資(不含外資自營商)、13＝投信、
    # 7＝外資自營商、22＝自營商合計、23＝三大法人合計 → 用加總對得上當結構檢查
    j = json.loads(curl_bytes(TPEX_INST_URL.format(y=y, m=m, d=d)))
    t0 = (j.get("tables") or [{}])[0]
    if t0.get("date") != roc or not t0.get("data"):
        raise RuntimeError(f"櫃買三大法人 {date}：資料日 {t0.get('date')}")
    for r in t0["data"]:
        v = [_num(x) for x in r[2:24]]
        if None in v or len(v) != 22 or v[2] + v[5] + v[11] + v[20] != v[21]:
            raise RuntimeError(f"櫃買三大法人欄位對不上（網頁結構可能改了）：{r[:3]}")
        out[r[0].strip()] = {"name": r[1].strip(), "market": "上櫃",
                             "f": int(v[2]), "t": int(v[11])}
    q = json.loads(curl_bytes(TPEX_QUOTE_URL.format(y=y, m=m, d=d)))
    tbl = next((t for t in q.get("tables", []) if t.get("date") == roc), None)
    if not tbl:
        raise RuntimeError(f"櫃買收盤行情 {date}：找不到當日表格")
    f = tbl["fields"]
    ci, vi, di = f.index("收盤"), f.index("成交股數"), f.index("漲跌")
    for r in tbl["data"]:
        if r[0] in out and out[r[0]]["market"] == "上櫃":
            out[r[0]].update(close=_num(r[ci]), vol=_num(r[vi]), chg=r[di].strip())
    return out


def co_from_full(full, date):
    co = {"data_date": date, "source": "full", "buy": [], "sell": []}
    for tk, x in full.items():
        if not STOCK_RE.fullmatch(tk):
            continue
        fl, tl = round(x["f"] / 1000), round(x["t"] / 1000)
        side = "buy" if fl > 0 and tl > 0 else "sell" if fl < 0 and tl < 0 else None
        if not side:
            continue
        close, vol = x.get("close"), x.get("vol")
        co[side].append({
            "ticker": tk, "name": x["name"], "market": x["market"],
            "close": close, "chg": x.get("chg", ""), "f_lots": fl, "t_lots": tl,
            "amount": round((x["f"] + x["t"]) * close / 1e8, 2) if close else None,
            "pct_vol": round((x["f"] + x["t"]) / vol * 100, 1) if vol else None})
    return co


def co_from_rank(foreign, trust):
    """備援：富邦兩份排行（上市＋上櫃各前 50）同方向都上榜的個股。"""
    co = {"data_date": trust["data_date"], "source": "rank", "buy": [], "sell": []}
    for key, (label, _) in INST_MARKETS.items():
        for side in ("buy", "sell"):
            tmap = {r["ticker"]: r for r in trust[key][side]}
            for f in foreign[key][side]:
                t = tmap.get(f["ticker"])
                if not t or not STOCK_RE.fullmatch(f["ticker"]):
                    continue
                co[side].append({
                    "ticker": f["ticker"], "name": f["name"], "market": label,
                    "close": f["close"], "chg": f["chg"],
                    "f_lots": f["lots"], "f_rank": f["rank"],
                    "t_lots": t["lots"], "t_rank": t["rank"],
                    "amount": round((f["lots"] + t["lots"]) * f["close"] / 1e5, 2),
                    "pct_vol": None})
    return co


def build_co(foreign, trust, results, fetch=True):
    """外資 × 投信 共同買超／賣超（同一天、同方向），依資料日期存 data/co/<日期>.json。
    主來源：證交所＋櫃買全市場三大法人；失敗才用富邦排行前 50 交集（名單會短很多）。
    金額＝（外資＋投信股數）× 收盤價，只是估算；排除 ETF／債券 ETF／特別股，只留 4 位數普通股。"""
    if not trust:
        return None
    date = trust["data_date"]
    folder = os.path.join(DATA_DIR, "co")
    path = os.path.join(folder, f"{date}.json")
    co = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            co = json.load(f)
    if fetch and (not co or co.get("source") != "full"):   # 已有全市場版就不重抓
        try:
            co = co_from_full(fetch_full_inst(date), date)
            print(f"  ✅ 全市場共同買超 {date}：買 {len(co['buy'])}、賣 {len(co['sell'])}", flush=True)
        except Exception as e:
            print(f"  ⚠️  全市場三大法人失敗，改用富邦排行交集：{e}", file=sys.stderr)
            if foreign and foreign["data_date"] == date:
                co = co_from_rank(foreign, trust)
        if co:
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(co, f, ensure_ascii=False, indent=2)
    if not co:   # 沒存檔、也沒得抓（例如外資排行還停在前一天）
        if not foreign or foreign["data_date"] != date:
            return {"data_date": date, "foreign_date": (foreign or {}).get("data_date"),
                    "same_day": False, "buy": [], "sell": []}
        co = co_from_rank(foreign, trust)
    co["same_day"] = True
    _, acts = etf_acts(results, date)   # ETF 動作每次現算（ETF 可能比法人晚更新）
    for side in ("buy", "sell"):
        for r in co[side]:
            r["etfs"] = [e for e in acts.get(r["ticker"], []) if (e["delta"] > 0) == (side == "buy")]
        co[side].sort(key=lambda x: abs(x["amount"] or 0), reverse=True)
    return co


# ---- 主流程 -----------------------------------------------------------

def today_tpe():
    return datetime.now(TPE).strftime("%Y-%m-%d")


def update_one(etfid, fetch=True):
    """抓取（或讀取最新快照）並算出比對結果。

    完整存檔策略：每次抓到就存（依資料日期歸檔，同日期覆寫）。這樣只要來源出現
    過的資料日期一律保留下來，不會因為「落後」而漏存，方便日後人工比對。
    來源是否落後於今天只做提示，不影響存檔。
    """
    if fetch:
        snap = fetch_snapshot(etfid)
        for b in snap.pop("backfill", []):
            save_snapshot(b)
            print(f"  ↩️  {etfid} 補存漏掉的 {b['data_date']}（小宇）", flush=True)
        existed = snap["data_date"] in list_snapshot_dates(etfid)
        save_snapshot(snap)
        tag = "（已存在，更新內容）" if existed else "（新資料日期）"
        lag = "" if snap["data_date"] >= today_tpe() else "  ⏳ 落後於今天"
        print(f"  ✅ {etfid} 存檔 {snap['data_date']} {tag}{lag}"
              f"  [{snap.get('source', 'moneydj')}]", flush=True)
    dates = list_snapshot_dates(etfid)
    if not dates:
        raise RuntimeError(f"{etfid}: 沒有任何快照可用")
    curr = load_snapshot(etfid, dates[-1])
    prev = load_snapshot(etfid, dates[-2]) if len(dates) >= 2 else None
    # 首次建立基準時沒有可比對的前一份，diff 留空（避免把全部持股誤標為「新增」）
    if prev is None:
        diff = {"added": [], "removed": [], "buys": [], "sells": [], "changes": []}
    else:
        diff = diff_pair(prev, curr)

    # 日期切換：最近 HIST_DAYS 個資料日各自對前一份，一律以張比對（與小宇口徑一致）
    px = merged_prices(etfid)
    history = []
    for i in range(len(dates) - 1, max(0, len(dates) - 1 - HIST_DAYS), -1):
        last = i == len(dates) - 1
        c = curr if last else load_snapshot(etfid, dates[i])
        p = prev if last else load_snapshot(etfid, dates[i - 1])
        dd = diff if last else diff_pair(p, c)
        history.append({"date": c["data_date"], "prev_date": p["data_date"],
                        "holdings_count": len(c["holdings"]),
                        "rows": build_rows(p, c, dd, px)})
    result = {
        "etfid": etfid,
        "fund_name": ETFS.get(etfid) or curr["fund_name"],
        "aum": estimate_aum(history[0]["rows"] if history else []),
        "data_date": curr["data_date"],
        "prev_date": prev["data_date"] if prev else None,
        "holdings_count": len(curr["holdings"]),
        "is_baseline": prev is None,
        "is_current": curr["data_date"] >= today_tpe(),
        "source": curr.get("source", "moneydj"),
        "diff": diff,
        # 完整持股只留在 data/ 快照與 CSV 封存，網頁改顯示小宇式動作清單（可切日期）
        "history": history,
    }
    return result


def estimate_aum(rows):
    """估算基金規模（億）＝ 有價格的持股市值合計 ÷ 這些持股的權重合計。
    海外/現金部位不在台股持股裡，用權重回推就能估到整檔；有價格的權重太少就不估。"""
    mv = sum(r["mv"] for r in rows if r.get("mv") and r["pct"] > 0)
    pct = sum(r["pct"] for r in rows if r.get("mv") and r["pct"] > 0)
    return round(mv / (pct / 100), 1) if pct >= 10 else None


def pick_top(results):
    """固定納入 TOP_FIXED，其餘依估算規模由大到小補滿 TOP_N 檔。"""
    by_id = {r["etfid"]: r for r in results}
    top = [e for e in TOP_FIXED if e in by_id]
    rest = sorted((r for r in results if r["etfid"] not in top and r.get("aum")),
                  key=lambda r: -r["aum"])
    top += [r["etfid"] for r in rest[:max(0, TOP_N - len(top))]]
    return top


def diff_pair(prev, curr):
    if (curr.get("xy_d1") or {}).get("base") == prev["data_date"]:
        return diff_from_xiaoyu(curr)            # 小宇已算好，且基準日正好是我們的前一份
    return diff_snapshots(prev, curr, lot=True)  # 歷史/備援 → 自行比對，以張為準


def build_rows(prev, curr, diff, px=None):
    """組出小宇式清單：每檔持股（含當日出清）一列，標動作 新增/加碼/減碼/出清/持平。
    mv=市值(億，收盤價)、dmoney=買賣金額(億，小宇值優先，否則以成交均價估)、dpct=權重變化。"""
    prev_h = prev["holdings"] if prev else {}
    chg = {c["ticker"]: c for c in diff["changes"]}
    day_px = (px or {}).get(curr["data_date"], {})

    def yi(shares, price):
        return round(shares * price / 1e8, 2) if price else None

    def close(t, h):
        return (day_px.get(t) or [None])[0] or (h or {}).get("price")

    def vwap(t, h):
        v = day_px.get(t)
        return v[1] if v else (h or {}).get("price")

    rows = []
    for t, h in curr["holdings"].items():
        c = chg.get(t)
        if not c:
            act = "hold"
        elif c.get("is_new"):
            act = "new"
        else:
            act = "add" if c["delta"] > 0 else "reduce"
        old = prev_h.get(t)
        rows.append({
            "ticker": t, "name": h["name"], "act": act,
            "shares": h["shares"], "pct": h["pct"], "mv": yi(h["shares"], close(t, h)),
            "delta": c["delta"] if c else 0,
            "dmoney": (c.get("money") if c and c.get("money") is not None
                       else (yi(c["delta"], vwap(t, h)) if c else None)),
            "dpct": round(h["pct"] - old["pct"], 2) if old else (h["pct"] if prev else None),
        })
    for t, c in chg.items():
        if t in curr["holdings"] or not c.get("is_removed"):
            continue
        old = prev_h.get(t, {})
        rows.append({
            "ticker": t, "name": c["name"], "act": "clear",
            "shares": 0, "pct": 0.0, "mv": 0.0,
            "delta": c["delta"],
            "dmoney": (c.get("money") if c.get("money") is not None
                       else yi(c["delta"], vwap(t, old))),
            "dpct": -old["pct"] if "pct" in old else None,
        })
    return rows


def export_archive():
    """把所有已存快照輸出成每檔一份 CSV（長格式），方便下載 / Excel 人工比對。
    輸出到 docs/archive/<代號>.csv，可從網站直接下載。"""
    import csv
    out_dir = os.path.join(SITE_DIR, "archive")
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for etfid in ETFS:
        dates = list_snapshot_dates(etfid)
        if not dates:
            continue
        rows = []
        for d in dates:
            snap = load_snapshot(etfid, d)
            for t, info in sorted(snap["holdings"].items(),
                                  key=lambda kv: kv[1]["pct"], reverse=True):
                rows.append([d, t, info["name"], info["pct"], info["shares"]])
        path = os.path.join(out_dir, f"{etfid}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["資料日期", "代號", "名稱", "投資比例(%)", "持有股數"])
            w.writerows(rows)
        index.append((etfid, len(dates), dates[0], dates[-1]))
    print("   📦 已輸出 CSV 封存：")
    for etfid, n, first, last in index:
        print(f"      archive/{etfid}.csv（{n} 個資料日期 {first}~{last}）")


def main():
    if "--export" in sys.argv:
        export_archive()
        return
    fetch = "--build" not in sys.argv
    os.makedirs(SITE_DIR, exist_ok=True)
    results = []
    for etfid in ETFS:
        try:
            print(f"[{'抓取' if fetch else '讀取'}] {etfid} ...", flush=True)
            results.append(update_one(etfid, fetch=fetch))
        except Exception as e:  # 單檔失敗不影響其他檔
            print(f"  ⚠️  {etfid} 失敗：{e}", file=sys.stderr)

    inst = {}
    for kind, (who, _) in INSTS.items():
        print(f"[{'抓取' if fetch else '讀取'}] {who}買賣超 ...", flush=True)
        try:
            snap = update_inst(kind, fetch=fetch)
            if snap:
                inst[kind] = build_inst_cross(snap, results)
        except Exception as e:  # 法人排行失敗不影響 ETF 部分
            print(f"  ⚠️  {who}買賣超失敗：{e}", file=sys.stderr)
    trust, foreign = inst.get("trust"), inst.get("foreign")
    try:
        co = build_co(foreign, trust, results, fetch=fetch)
    except Exception as e:
        co = None
        print(f"  ⚠️  共同買超失敗：{e}", file=sys.stderr)

    # 每列標「追蹤的 ETF 中，今天有幾檔加碼/減碼這檔」（小宇的 買N / 賣N）
    # （依資料日期分開算，切到舊日期時也正確）
    nbuy, nsell = defaultdict(int), defaultdict(int)
    for r in results:
        for h in r["history"]:
            for row in h["rows"]:
                if row["delta"]:
                    (nbuy if row["delta"] > 0 else nsell)[(h["date"], row["ticker"])] += 1
    for r in results:
        for h in r["history"]:
            for row in h["rows"]:
                k = (h["date"], row["ticker"])
                row["nbuy"], row["nsell"] = nbuy[k], nsell[k]

    generated_at = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    consensus = build_consensus(results)
    # 共同動作算完後，把每檔完整 changes 從 payload 移除，保持檔案精簡
    for r in results:
        r["diff"].pop("changes", None)
    # 經理人分析：市值前五大（固定 00981A、00403A）的加減碼 → Claude 推論＋本日小結
    top = pick_top(results)
    import analysis
    if fetch:
        try:
            analysis.run([r for r in results if r["etfid"] in top], top)
        except Exception as e:  # 分析失敗不影響持股資料
            print(f"  ⚠️  經理人分析失敗：{e}", file=sys.stderr)
    # 網頁依估算規模排序（大到小），沒估到的放最後
    results.sort(key=lambda r: -(r.get("aum") or 0))
    payload = {"generated_at": generated_at, "consensus": consensus, "etfs": results,
               "trust": trust, "foreign": foreign, "co": co, "top": top, "analysis": analysis.load_recent(HIST_DAYS)}

    # 存一份 JSON 方便除錯 / 之後做 API
    with open(os.path.join(SITE_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 產生自包含儀表板
    from dashboard import render
    html_out = render(payload)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)

    # 每次都輸出完整 CSV 封存（可從網站下載、供人工比對）
    export_archive()

    print(f"\n✅ 完成！產生於 {generated_at}")
    print(f"   儀表板：{os.path.join(SITE_DIR, 'index.html')}")
    for r in results:
        tag = "（首次建立基準）" if r["is_baseline"] else f"（對比 {r['prev_date']}）"
        d = r["diff"]
        print(f"   - {r['fund_name']} {r['data_date']} {tag}："
              f"持股{r['holdings_count']}檔, 新增{len(d['added'])}, "
              f"剔除{len(d['removed'])}, 買入{len(d['buys'])}, 賣出{len(d['sells'])}")


if __name__ == "__main__":
    main()
