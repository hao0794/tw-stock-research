import os, time, json, urllib.request
from fugle_marketdata import RestClient

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock

print("=== 1. 證交所全市場日成交資料 ===")
url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
try:
    with urllib.request.urlopen(url, timeout=30) as r:
        rows = json.loads(r.read().decode("utf-8"))
    print("筆數:", len(rows))
    print("第1筆:", rows[0])
    for row in rows:
        if row.get("Code") == "2330":
            print("2330:", row)
except Exception as e:
    print("失敗:", e)

print("=== 2. 富果連續查歷史日K(測速度與限流) ===")
codes = ["2330","2317","2454","2412","2308","2881","2882","2303","3711","2382",
         "2891","1301","2002","1216","2603","2609","2615","3034","2379","2357"]
start = time.time()
ok = 0
for c in codes:
    try:
        stock.historical.candles(**{"symbol": c, "from": "2026-08-20",
            "to": "2026-09-28", "fields": "open,high,low,close,volume"})
        ok += 1
    except Exception as e:
        print(c, "失敗:", str(e)[:150])
        break
print("成功 %d/%d 檔, 耗時 %.1f 秒" % (ok, len(codes), time.time() - start))
