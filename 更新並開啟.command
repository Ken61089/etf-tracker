#!/bin/bash
# 點兩下就會：抓取最新持股 → 產生儀表板 → 自動開啟
cd "$(dirname "$0")"
echo "正在更新 ETF 持股資料..."
python3 etf_tracker.py
echo ""
echo "開啟儀表板..."
open docs/index.html
echo "完成，可關閉此視窗。"
