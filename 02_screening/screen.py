import os, csv, json, time, urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean
from fugle_marketdata import RestClient

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock

def tick(p):
    if p < 10: return 0.01
    if p < 50: return 0.05
    if p < 100: return 0.1
    if p < 500: return 0.5
    if p < 1000: return 1.0
    return 5.0

def to_tick(p):
    t = Decimal(str(tick(p)))
    return float((Decimal(str(p)) / t).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * t)

def num(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None

print("下載證交所全市場資料...")
url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
with urllib.request.urlopen(url, timeout=30) as r:
    rows = json.loads(r.read().decode("utf-8"))

roc = rows[0]["Date"]
trade_date = datetime(int(roc[:-4]) + 1911, int(roc[-4:-2]), int(roc[-2:])).date()

# 第一階段初篩
cands = []
for r in rows:
    code = r["Code"]
    if not (code.isdigit() and len(code) == 4) or code.startswith("00"):
        continue
    o, h = num(r["OpeningPrice"]), num(r["HighestPrice"])
    l, c = num(r["LowestPrice"]), num(r["ClosingPrice"])
    chg, vol = num(r["Change"]), num(r["TradeVolume"])
    if None in (o, h, l, c, chg, vol):
        continue
    prev = c - chg
    if prev <= 0 or c <= 25 or h <= l:
        continue
    pct = chg / prev * 100
    shadow = (h - max(o, c)) / (h - l)
    # 今日量需 > 2 倍且20日均量 > 3000張，所以今日量至少 6000 張(6,000,000 股)
    if 4.0 <= pct <= 9.5 and shadow <= 0.10 and vol >= 6_000_000:
        cands.append(dict(code=code, name=r["Name"], o=o, h=h, l=l, c=c, vol=vol, pct=pct, shadow=shadow))

print("資料日期:", trade_date, "| 初篩通過:", len(cands), "檔")

# 第二階段：用富果歷史日K檢查均線與均量
start = (trade_date - timedelta(days=70)).isoformat()
end = trade_date.isoformat()

def get_candles(code):
    for _ in range(3):
        try:
            res = stock.historical.candles(**{"symbol": code, "from": start, "to": end,
                "fields": "open,high,low,close,volume"})
            return res["data"]
        except Exception as e:
            print("  ", code, "查詢失敗，5 秒後重試:", str(e)[:80])
            time.sleep(5)
    return None

results, skipped = [], []
for x in cands:
    time.sleep(0.2)
    data = get_candles(x["code"])
    if not data:
        skipped.append(x["code"]); continue
    data = sorted(data, key=lambda d: d["date"])
    if data[-1]["date"] != end or len(data) < 21:
        skipped.append(x["code"]); continue
    closes = [d["close"] for d in data]
    vols = [d["volume"] for d in data]
    ma5, ma10, ma20 = mean(closes[-5:]), mean(closes[-10:]), mean(closes[-20:])
    avg20 = mean(vols[-21:-1])
    ratio = x["vol"] / avg20 if avg20 else 0
    c = x["c"]
    print("  診斷", x["code"], x["name"], "收盤", c, "MA5/10/20", round(ma5, 2), round(ma10, 2), round(ma20, 2), "量比", round(ratio, 2), "20日均量(張)", round(avg20 / 1000))
    if not (avg20 > 3_000_000 and ratio > 2 and c > ma5 > ma10 > ma20):
        continue
    cum20 = (c / closes[-21] - 1) * 100
    bias = (c / ma20 - 1) * 100
    results.append({
        "代號": x["code"], "名稱": x["name"], "收盤": c, "漲幅%": round(x["pct"], 2),
        "爆量倍數": round(ratio, 2),
        "明日買進觸發價": to_tick(x["h"] + tick(x["h"])),
        "早盤量能檢驗(張,09:30前)": round(x["vol"] * 0.20 / 1000),
        "停損防守價": to_tick(c * 0.985),
        "上影線比例%": round(x["shadow"] * 100, 1),
        "20日累積漲幅%": round(cum20, 1),
        "對20MA乖離%": round(bias, 1),
        "位階提示": "高位階" if cum20 > 20 else "",
    })

results.sort(key=lambda d: d["爆量倍數"], reverse=True)
results = results[:10]

print("最終入選:", len(results), "檔 | 資料不足略過:", len(skipped), "檔", skipped)
if not results:
    print("今日無符合標的")
for x in results:
    print(x)

if results:
    outdir = os.path.expanduser("~/fugle/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "screen_%s.csv" % trade_date)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print("已存檔:", path)
