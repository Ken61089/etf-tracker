# -*- coding: utf-8 -*-
"""
經理人在想什麼：把市值前五大主動 ETF 當天的 新增/加碼/減碼/出清 交給 Claude，
推論各檔經理人的布局方向，並寫一段「本日小結」。

- 結果存 data/analysis/<資料日期>.json；同一組輸入（各檔資料日期）已分析過就不再呼叫。
- 只分析「資料日期 = 這幾檔中最新日期」的 ETF；晚出的那檔補上後輸入改變，會自動重跑一次。
- 需要環境變數 ANTHROPIC_API_KEY（GitHub Actions 走 repo secret）；沒設就跳過。
"""

import os
import json
from datetime import datetime, timezone, timedelta

MODEL = "claude-sonnet-5-5"
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data", "analysis")
TPE = timezone(timedelta(hours=8))

TOP_MOVES = 12      # 每檔加碼、減碼各取金額最大的前幾筆（新增/出清全列）

SYSTEM = """你是台股主動型 ETF 的持股變化分析師。使用者會給你幾檔主動型 ETF 同一個資料日的持股異動（新增、加碼、減碼、出清），請推論「這些投信經理人在想什麼、布局什麼」。

寫法：
- 每檔寫一段 2～4 句的分析：先點出最重要的幾筆動作（附張數），再歸納成產業／題材方向，最後一句講整體結構怎麼變（例如更集中、輪動、降低某類曝險）。
- 用你對台股產業的知識判斷個股屬性與題材（例如華邦電＝記憶體、旺矽＝半導體測試、貿聯-KY＝高速傳輸線材、聯電＝成熟製程）。
- 產業面的推論可以寫，但要用「可能」「反映」「顯示」「或許」這類推論語氣，例如「減持華邦電，可能反映對記憶體報價續漲的保留」。
- 本日小結：綜合所有 ETF，點出共同方向（多檔同步加碼／減碼的題材）與分歧（不同經理人配置差異），3～5 句。

嚴格規則：
- 張數、金額、權重只能用資料裡給的數字，不可自己換算出新數字或改寫數字。
- 不可捏造資料中沒有的具體事實：新聞、法說內容、財報數字、報價數字、融資籌碼、目標價都不行。
- 不給買賣建議、不說「值得買進」「可以布局」之類的話；你描述的是經理人的動作與可能想法。
- 資料只有台股部位；含海外持股的 ETF（例如全球型）只就看得到的台股部分推論，不要假設海外部位的動作。
- 一律使用繁體中文與台灣用語。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "etfs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "etfid": {"type": "string"},
                    "headline": {"type": "string"},
                    "analysis": {"type": "string"},
                    "up": {"type": "array", "items": {"type": "string"}},
                    "down": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["etfid", "headline", "analysis", "up", "down"],
                "additionalProperties": False,
            },
        },
        "summary": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["headline", "text"],
            "additionalProperties": False,
        },
    },
    "required": ["etfs", "summary"],
    "additionalProperties": False,
}

ACT_LABEL = {"new": "新增", "add": "加碼", "reduce": "減碼", "clear": "出清"}


def _lots(shares):
    return round(shares / 1000)


def pick_moves(rows):
    """新增、出清全列；加碼、減碼各取金額（沒金額用張數）最大的前 TOP_MOVES 筆。"""
    def size(r):
        return abs(r["dmoney"]) if r.get("dmoney") is not None else abs(r["delta"]) / 1e6
    moves = [r for r in rows if r["act"] in ("new", "clear")]
    for act in ("add", "reduce"):
        moves += sorted((r for r in rows if r["act"] == act), key=size, reverse=True)[:TOP_MOVES]
    return [r for r in moves if _lots(r["delta"]) != 0]


def describe(r, day):
    """把一檔 ETF 當天的資料寫成給模型看的文字。"""
    rows = day["rows"]
    lines = [f"## {r['fund_name']}（{r['etfid']}）資料日 {day['date']}（對比 {day['prev_date']}）"
             + (f"，估算規模約 {r['aum']:.0f} 億" if r.get("aum") else "")]
    top = sorted((x for x in rows if x["act"] != "clear"), key=lambda x: -x["pct"])[:10]
    lines.append("前十大持股：" + "、".join(f"{x['name']} {x['pct']:.2f}%" for x in top))
    moves = pick_moves(rows)
    n_add = sum(1 for x in rows if x["act"] in ("add", "new"))
    n_red = sum(1 for x in rows if x["act"] in ("reduce", "clear"))
    lines.append(f"當日異動：加碼/新增 {n_add} 檔、減碼/出清 {n_red} 檔（下列為主要異動）")
    for x in moves:
        bits = [f"{ACT_LABEL[x['act']]} {x['name']}({x['ticker']}) {_lots(x['delta']):+,} 張"]
        if x.get("dmoney") is not None:
            bits.append(f"約 {x['dmoney']:+.2f} 億")
        if x.get("dpct") is not None:
            bits.append(f"權重 {x['dpct']:+.2f}% → {x['pct']:.2f}%")
        if x.get("nbuy") or x.get("nsell"):
            bits.append(f"追蹤的主動 ETF 當日 {x.get('nbuy', 0)} 檔買／{x.get('nsell', 0)} 檔賣")
        lines.append("- " + "，".join(bits))
    return "\n".join(lines)


def out_path(date):
    return os.path.join(OUT_DIR, f"{date}.json")


def run(top_results, top_ids):
    """分析前五大中「資料日期最新」的那幾檔；同一組輸入已分析過就跳過。"""
    days = [(r, r["history"][0]) for r in top_results if r.get("history")]
    days = [(r, d) for r, d in days if any(x["act"] != "hold" for x in d["rows"])]
    if not days:
        print("  ℹ️  經理人分析：前五大沒有可分析的異動，跳過", flush=True)
        return
    date = max(d["date"] for _, d in days)
    days = [(r, d) for r, d in days if d["date"] == date]
    days.sort(key=lambda rd: top_ids.index(rd[0]["etfid"]))
    sig = [f"{r['etfid']}:{d['prev_date']}>{d['date']}" for r, d in days]

    path = out_path(date)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("sig") == sig:
            print(f"  ℹ️  經理人分析 {date} 已是最新（{len(sig)} 檔），不重跑", flush=True)
            return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ℹ️  沒有 ANTHROPIC_API_KEY，跳過經理人分析", flush=True)
        return

    import anthropic
    client = anthropic.Anthropic()
    prompt = ("以下是主動型 ETF 的持股異動資料，請依指示逐檔分析並寫本日小結。"
              "etfid 請照資料裡的代號填，順序照資料順序。\n\n"
              + "\n\n".join(describe(r, d) for r, d in days))
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        print("  ⚠️  經理人分析：ANTHROPIC_API_KEY 無效", flush=True)
        return
    except anthropic.RateLimitError:
        print("  ⚠️  經理人分析：被限流，下一輪再試", flush=True)
        return
    except anthropic.APIStatusError as e:
        print(f"  ⚠️  經理人分析：API 錯誤 {e.status_code} {e.message}", flush=True)
        return
    except anthropic.APIConnectionError:
        print("  ⚠️  經理人分析：連不上 Anthropic，下一輪再試", flush=True)
        return

    if resp.stop_reason != "end_turn":
        print(f"  ⚠️  經理人分析沒有完成（stop_reason={resp.stop_reason}），保留舊結果", flush=True)
        return
    text = next(b.text for b in resp.content if b.type == "text")
    data = json.loads(text)

    names = {r["etfid"]: r["fund_name"] for r, _ in days}
    aums = {r["etfid"]: r.get("aum") for r, _ in days}
    etfs = [dict(e, fund_name=names[e["etfid"]], aum=aums[e["etfid"]])
            for e in data["etfs"] if e["etfid"] in names]
    out = {
        "date": date,
        "sig": sig,
        "model": resp.model,
        "generated_at": datetime.now(TPE).strftime("%Y-%m-%d %H:%M"),
        "pending": [e for e in top_ids if e not in names],   # 前五大裡還沒更新到這天、或沒異動的
        "summary": data["summary"],
        "etfs": etfs,
        "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  🧠 經理人分析 {date} 完成（{len(etfs)} 檔，"
          f"tokens 入 {resp.usage.input_tokens:,}／出 {resp.usage.output_tokens:,}）", flush=True)


def load_recent(n):
    """最近 n 份分析（新到舊），給網頁的日期切換用。"""
    if not os.path.isdir(OUT_DIR):
        return []
    files = sorted((f for f in os.listdir(OUT_DIR) if f.endswith(".json")), reverse=True)[:n]
    out = []
    for f in files:
        with open(os.path.join(OUT_DIR, f), encoding="utf-8") as fh:
            out.append(json.load(fh))
    return out
