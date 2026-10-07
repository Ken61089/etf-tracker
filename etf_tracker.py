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
    "00981A": "主動統一台股增長",
    "00403A": "主動統一升級50",
    "00982A": "主動群益台灣強棒",
    "00991A": "主動復華未來50",
    "00992A": "主動群益科技創新",
}

# 主來源：籌碼小宇（每檔一個 JSON，已算好加碼/減碼/新增/出清，單位為「張」）
XY_URL = "https://xiaoyu-etf.pages.dev/data/etf/{etfid}.json"
# 備援來源：MoneyDJ（單位為「股」，加減碼由本系統自行比對）
BASE_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={etfid}.TW"
# 投信買賣超一日排行（富邦 DJ）：B=0 上市、B=1 上櫃
TRUST_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zg/zgk.djhtm?A=DD&B={b}&C=1"
TRUST_MARKETS = {"twse": ("上市", 0), "tpex": ("上櫃", 1)}

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")        # 每日快照
SITE_DIR = os.path.join(ROOT, "docs")        # 產生的儀表板（GitHub Pages 用 /docs）

TPE = timezone(timedelta(hours=8))           # 台灣時區

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
    latest = d["snap_dates"][0]
    rows = d["snaps"].get(latest) or []
    names = d.get("names", {})
    holdings = {
        code: {"name": names.get(code, code), "pct": float(pct),
               "shares": int(round(lots * 1000))}
        for code, lots, pct in rows
    }
    if not holdings:
        raise RuntimeError(f"{etfid}: 小宇解析不到任何持股")

    def ymd(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"

    snap = {
        "etfid": etfid,
        "fund_name": ETFS.get(etfid) or etfid,
        "data_date": ymd(latest),
        "source": "xiaoyu",
        "lot_precision": True,
        "holdings": holdings,
    }
    d1 = (d.get("wins") or {}).get("d1") or {}
    # 只有小宇的 d1 正好是「最新快照 vs 前一份」才帶回，否則交給本系統自行比對
    if d1.get("available") and d.get("date") == latest and d1.get("base"):
        snap["xy_d1"] = {"base": ymd(d1["base"]),
                         "buy": d1.get("buy", []), "sell": d1.get("sell", [])}
    return snap


def fetch_snapshot(etfid):
    """主來源小宇；失敗或資料日期落後於已存的最新快照時，改試 MoneyDJ，取較新者。"""
    saved = list_snapshot_dates(etfid)
    latest_saved = saved[-1] if saved else ""
    snap, err = None, None
    try:
        snap = fetch_xiaoyu(etfid)
    except Exception as e:
        err = e
        print(f"  ⚠️  {etfid} 小宇失敗，改用 MoneyDJ：{e}", file=sys.stderr)
    if snap is None or snap["data_date"] < latest_saved:
        try:
            mdj = parse(fetch_html(etfid), etfid)
            mdj["source"] = "moneydj"
            if snap is None or mdj["data_date"] > snap["data_date"]:
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

def diff_snapshots(prev, curr, top_n=5):
    """比較兩份快照，回傳新增 / 剔除 / 買入前五 / 賣出前五。"""
    prev_h = prev["holdings"] if prev else {}
    curr_h = curr["holdings"]
    # 任一邊來自小宇（只到張），兩邊都統一捨成張再比，避免零股差異變成假買賣
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


# ---- 投信買賣超（富邦 DJ）--------------------------------------------

TRUST_DATE_RE = re.compile(r"日期：(\d{1,2})/(\d{1,2})")
TRUST_ROW_RE = re.compile(
    r"Link2Stk\('([^']+)'\)\">([^<]+)</a></td>\s*"
    r"<td class=\"t3n1\">([-\d,]+)</td>\s*"
    r"<td class=\"t3n1\">([\d.,]+)</td>\s*"
    r"<td class=\"t3\w+\">([^<]*)</td>",
    re.S | re.I,
)


def fetch_trust_market(key):
    """抓一個市場的投信買賣超一日排行，回傳 (資料日期, {buy, sell})。
    網頁買超/賣超兩欄交錯排列，以超張數正負號分邊。"""
    label, b = TRUST_MARKETS[key]
    text = curl_bytes(TRUST_URL.format(b=b)).decode("cp950", errors="replace")
    m = TRUST_DATE_RE.search(text)
    if not m:
        raise RuntimeError(f"投信{label}：找不到資料日期")
    # 網頁只給月/日，年份用台灣今天推（跨年時月份比今天大 → 去年）
    now = datetime.now(TPE)
    mon, day = int(m.group(1)), int(m.group(2))
    year = now.year - 1 if (mon, day) > (now.month, now.day) else now.year
    data_date = f"{year}-{mon:02d}-{day:02d}"
    buy, sell = [], []
    for code, raw, lots, close, chg in TRUST_ROW_RE.findall(text):
        name = html.unescape(raw).strip()
        if name.startswith(code):
            name = name[len(code):]
        row = {"ticker": code, "name": name.strip(),
               "lots": int(lots.replace(",", "")),
               "close": float(close.replace(",", "")),
               "chg": chg.strip()}
        (buy if row["lots"] > 0 else sell).append(row)
    if not buy and not sell:
        raise RuntimeError(f"投信{label}：解析不到任何排行（網頁結構可能改了）")
    for lst in (buy, sell):
        for i, r in enumerate(lst, 1):
            r["rank"] = i
    return data_date, {"buy": buy, "sell": sell}


def update_trust(fetch=True):
    """抓上市+上櫃投信買賣超，依資料日期存 data/trust/<日期>.json；回傳最新一份。"""
    folder = os.path.join(DATA_DIR, "trust")
    if fetch:
        snap = {}
        for key, (label, _) in TRUST_MARKETS.items():
            try:
                d, data = fetch_trust_market(key)
                snap.setdefault("data_date", d)
                if d != snap["data_date"]:
                    raise RuntimeError(f"投信{label}日期 {d} 與另一市場 {snap['data_date']} 不一致")
                snap[key] = data
                print(f"  ✅ 投信{label} {d}：買超 {len(data['buy'])}、賣超 {len(data['sell'])}",
                      flush=True)
            except Exception as e:
                print(f"  ⚠️  投信{label} 失敗：{e}", file=sys.stderr)
        if all(k in snap for k in TRUST_MARKETS):   # 兩市場都成功才存，避免存半份
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


def build_trust_cross(trust, results):
    """投信買賣超 × 主動 ETF 加減碼交叉：只拿資料日期與投信同一天的 ETF 比。
    在每筆投信排行上掛 etfs（哪幾檔 ETF 當天也有動作），並整理同向清單。"""
    same_day = [r for r in results
                if not r["is_baseline"] and r["data_date"] == trust["data_date"]]
    acts = defaultdict(list)
    for r in same_day:
        for c in r["diff"]["changes"]:
            acts[c["ticker"]].append({
                "fund_name": r["fund_name"], "delta": c["delta"],
                "is_new": c.get("is_new", False),
                "is_removed": c.get("is_removed", False)})
    cross = {"buy": [], "sell": []}
    for key, (label, _) in TRUST_MARKETS.items():
        for side in ("buy", "sell"):
            for row in trust[key][side]:
                lst = acts.get(row["ticker"], [])
                row["etfs"] = sorted(lst, key=lambda e: abs(e["delta"]), reverse=True)
                same = [e for e in lst if (e["delta"] > 0) == (side == "buy")]
                if same:
                    cross[side].append({**row, "market": label, "etfs": same})
    for side in cross:
        cross[side].sort(key=lambda x: (len(x["etfs"]), abs(x["lots"])), reverse=True)
    trust["cross"] = cross
    trust["etf_same_day"] = [r["etfid"] for r in same_day]
    trust["etf_other_day"] = [f"{r['etfid']}({r['data_date']})" for r in results
                              if r not in same_day]
    return trust


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
    elif (curr.get("xy_d1") or {}).get("base") == prev["data_date"]:
        diff = diff_from_xiaoyu(curr)       # 小宇已算好，且基準日正好是我們的前一份
    else:
        diff = diff_snapshots(prev, curr)   # 備援來源或基準日對不上 → 自行比對
    result = {
        "etfid": etfid,
        "fund_name": curr["fund_name"],
        "data_date": curr["data_date"],
        "prev_date": prev["data_date"] if prev else None,
        "holdings_count": len(curr["holdings"]),
        "is_baseline": prev is None,
        "is_current": curr["data_date"] >= today_tpe(),
        "source": curr.get("source", "moneydj"),
        "diff": diff,
        "holdings": [
            {"ticker": t, **info}
            for t, info in sorted(curr["holdings"].items(),
                                  key=lambda kv: kv[1]["pct"], reverse=True)
        ],
    }
    return result


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

    print(f"[{'抓取' if fetch else '讀取'}] 投信買賣超 ...", flush=True)
    trust = None
    try:
        trust = update_trust(fetch=fetch)
        if trust:
            trust = build_trust_cross(trust, results)
    except Exception as e:  # 投信失敗不影響 ETF 部分
        print(f"  ⚠️  投信買賣超失敗：{e}", file=sys.stderr)

    generated_at = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    consensus = build_consensus(results)
    # 共同動作算完後，把每檔完整 changes 從 payload 移除，保持檔案精簡
    for r in results:
        r["diff"].pop("changes", None)
    payload = {"generated_at": generated_at, "consensus": consensus, "etfs": results,
               "trust": trust}

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
