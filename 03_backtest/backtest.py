import os, csv, json, time, urllib.request
from datetime import datetime, timedelta
from statistics import mean
from fugle_marketdata import RestClient

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock

def num(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None

url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
with urllib.request.urlopen(url, timeout=30) as r:
    rows = json.loads(r.read().decode("utf-8"))

roc = rows[0]["Date"]
end_date = datetime(int(roc[:-4]) + 1911, int(roc[-4:-2]), int(roc[-2:])).date()
start = (end_date - timedelta(days=85)).isoformat()
end = end_date.isoformat()

codes = []
for r in rows:
    code = r["Code"]
    c = num(r["ClosingPrice"])
    if code.isdigit() and len(code) == 4 and not code.startswith("00") and c and c >= 20:
        codes.append(code)
print("回測資料日期至:", end, "| 待查股票:", len(codes), "檔(約需 3~6 分鐘,請等待)")

N = 20
hits, failed, seen = [], [], set()
for n, code in enumerate(codes, 1):
    time.sleep(0.15)
    data = None
    for _ in range(3):
        try:
            data = stock.historical.candles(**{"symbol": code, "from": start, "to": end,
                "fields": "open,high,low,close,volume"})["data"]
            break
        except Exception:
            time.sleep(5)
    if not data:
        failed.append(code)
        continue
    data = sorted(data, key=lambda d: d["date"])
    for i in range(max(20, len(data) - N), len(data)):
        d = data[i]
        seen.add(d["date"])
        o, h, l, c, v = d["open"], d["high"], d["low"], d["close"], d["volume"]
        prev = data[i - 1]["close"]
        if not (o and h and l and c and prev) or h <= l or c <= 25:
            continue
        pct = (c / prev - 1) * 100
        shadow = (h - max(o, c)) / (h - l)
        if not (4.0 <= pct <= 9.5 and shadow <= 0.10):
            continue
        avg20 = mean(x["volume"] for x in data[i - 20:i])
        if avg20 <= 3_000_000 or v <= 2 * avg20:
            continue
        cl = [x["close"] for x in data[:i + 1]]
        ma5, ma10, ma20 = mean(cl[-5:]), mean(cl[-10:]), mean(cl[-20:])
        if not (c > ma5 > ma10 > ma20):
            continue
        hits.append({"日期": d["date"], "代號": code, "收盤": c,
                     "漲幅%": round(pct, 2), "爆量倍數": round(v / avg20, 2)})
    if n % 100 == 0:
        print("  進度", n, "/", len(codes))

print("查詢失敗:", len(failed), "檔")
print("回測交易日數:", len(seen), "| 命中總數:", len(hits))
by_day = {}
for x in hits:
    by_day.setdefault(x["日期"], []).append(x)
for day in sorted(seen):
    print(day, "命中", len(by_day.get(day, [])), "檔")

if hits:
    outdir = os.path.expanduser("~/fugle/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "backtest.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(hits[0].keys()))
        w.writeheader()
        w.writerows(sorted(hits, key=lambda d: (d["日期"], -d["爆量倍數"])))
    print("已存檔:", path)
