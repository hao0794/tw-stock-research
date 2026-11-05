import os
from fugle_marketdata import RestClient

client = RestClient(api_key=os.environ["FUGLE_API_KEY"])
stock = client.stock

print("=== 歷史日K ===")
try:
    candles = stock.historical.candles(**{
        "symbol": "2330", "from": "2026-08-20", "to": "2026-09-28",
        "fields": "open,high,low,close,volume"})
    data = candles["data"]
    print("筆數:", len(data))
    print("前2筆:", data[:2])
    print("後2筆:", data[-2:])
except Exception as e:
    print("錯誤:", e)

print("=== 全市場快照(上市) ===")
try:
    snap = stock.snapshot.quotes(market="TSE")
    print("筆數:", len(snap["data"]))
    print("第1筆:", snap["data"][0])
except Exception as e:
    print("錯誤:", e)
