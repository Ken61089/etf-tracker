#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主動型 ETF 每日持股追蹤系統
----------------------------------
抓取 MoneyDJ 上多檔主動型 ETF 的每日持股，存成快照，
並比較最新與前一份「資料日期不同」的快照，算出：
  1. 新增標的（相較上一份新買進的）
  2. 剔除持股（上一份有、現在完全沒持有的）
  3. 今日買入前五名（持有股數增加最多）
  4. 今日賣出前五名（持有股數減少最多）
最後產生一個自包含的網頁儀表板 site/index.html。

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
from datetime import datetime, timezone, timedelta

# ---- 設定 -------------------------------------------------------------

# 要追蹤的 ETF（代號 -> 預設顯示名稱，實際名稱會從網頁自動更新）
ETFS = {
    "00981A": "主動統一台股增長",
    "00403A": "主動統一升級50",
    "00982A": "主動統一全球創新",
}

BASE_URL = "https://www.moneydj.com/ETF/X/Basic/Basic0007B.xdjhtm?etfid={etfid}.TW"

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")        # 每日快照
SITE_DIR = os.path.join(ROOT, "docs")        # 產生的儀表板（GitHub Pages 用 /docs）

TPE = timezone(timedelta(hours=8))           # 台灣時區

# ---- 抓取與解析 -------------------------------------------------------

def fetch_html(etfid):
    """用 curl 抓網頁原始碼（curl 對這個網站的 TLS 最穩定）。"""
    url = BASE_URL.format(etfid=etfid)
    result = subprocess.run(
        [
            "curl", "-s", "--fail", "--max-time", "30",
            "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            url,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"抓取 {etfid} 失敗 (curl exit {result.returncode})")
    return result.stdout


# 解析資料日期，例如 ...sdate3...>2026/06/05
DATE_RE = re.compile(r"sdate3.*?(\d{4}/\d{2}/\d{2})", re.S)

# 解析每一列持股：名稱+代號、投資比例、持有股數
ROW_RE = re.compile(
    r"col05\"><a[^>]*etfid=([0-9A-Za-z]+)\.TW[^>]*>([^<]+)</a></td>"
    r"<td class=\"col06\">([\d.]+)</td>"
    r"<td class=\"col07\">([\d,]+)</td>",
    re.S,
)

# 解析網頁上的基金中文名，例如 主動統一台股增長(00981A.TW)-全部持股
NAME_RE = re.compile(r"<h[12][^>]*>\s*([^<(]+?)\s*\([0-9A-Za-z]+\.TW\)")


def parse(html_text, etfid):
    """從網頁原始碼解析出資料日期與持股清單。"""
    m = DATE_RE.search(html_text)
    if not m:
        raise RuntimeError(f"{etfid}: 找不到資料日期")
    data_date = m.group(1).replace("/", "-")

    name_m = NAME_RE.search(html_text)
    fund_name = name_m.group(1).strip() if name_m else ETFS.get(etfid, etfid)

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

    added, removed, changes = [], [], []

    for ticker, info in curr_h.items():
        old = prev_h.get(ticker)
        old_shares = old["shares"] if old else 0
        delta = info["shares"] - old_shares
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
        if ticker not in curr_h:
            removed.append({"ticker": ticker, "name": info["name"],
                            "old_shares": info["shares"], "pct": info["pct"]})
            changes.append({
                "ticker": ticker, "name": info["name"],
                "delta": -info["shares"],
                "old_shares": info["shares"], "new_shares": 0,
                "pct": 0.0, "is_removed": True,
            })

    buys = sorted([c for c in changes if c["delta"] > 0],
                  key=lambda c: c["delta"], reverse=True)[:top_n]
    sells = sorted([c for c in changes if c["delta"] < 0],
                   key=lambda c: c["delta"])[:top_n]

    added.sort(key=lambda x: x["shares"], reverse=True)
    removed.sort(key=lambda x: x["old_shares"], reverse=True)
    return {"added": added, "removed": removed, "buys": buys, "sells": sells}


# ---- 主流程 -----------------------------------------------------------

def update_one(etfid, fetch=True):
    """抓取（或讀取最新快照）並算出比對結果。"""
    if fetch:
        snap = parse(fetch_html(etfid), etfid)
        save_snapshot(snap)
    dates = list_snapshot_dates(etfid)
    if not dates:
        raise RuntimeError(f"{etfid}: 沒有任何快照可用")
    curr = load_snapshot(etfid, dates[-1])
    prev = load_snapshot(etfid, dates[-2]) if len(dates) >= 2 else None
    # 首次建立基準時沒有可比對的前一份，diff 留空（避免把全部持股誤標為「新增」）
    diff = (diff_snapshots(prev, curr) if prev else
            {"added": [], "removed": [], "buys": [], "sells": []})
    result = {
        "etfid": etfid,
        "fund_name": curr["fund_name"],
        "data_date": curr["data_date"],
        "prev_date": prev["data_date"] if prev else None,
        "holdings_count": len(curr["holdings"]),
        "is_baseline": prev is None,
        "diff": diff,
        "holdings": [
            {"ticker": t, **info}
            for t, info in sorted(curr["holdings"].items(),
                                  key=lambda kv: kv[1]["pct"], reverse=True)
        ],
    }
    return result


def main():
    fetch = "--build" not in sys.argv
    os.makedirs(SITE_DIR, exist_ok=True)
    results = []
    for etfid in ETFS:
        try:
            print(f"[{'抓取' if fetch else '讀取'}] {etfid} ...", flush=True)
            results.append(update_one(etfid, fetch=fetch))
        except Exception as e:  # 單檔失敗不影響其他檔
            print(f"  ⚠️  {etfid} 失敗：{e}", file=sys.stderr)

    generated_at = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    payload = {"generated_at": generated_at, "etfs": results}

    # 存一份 JSON 方便除錯 / 之後做 API
    with open(os.path.join(SITE_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 產生自包含儀表板
    from dashboard import render
    html_out = render(payload)
    with open(os.path.join(SITE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)

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
