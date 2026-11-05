import os, json, csv, urllib.request
from math import sqrt
from statistics import mean, stdev

MAX_DD = 0.20        # 可接受的最大回撤
MIN_DAYS = 200       # 至少要有的交易日數(排除新上市)
MIN_LOTS = 3000      # 近60日平均成交量下限(張)
TRADING_DAYS = 245   # 一年約略交易日數

root = os.path.expanduser("~/fugle/cache")
folders = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
if not folders:
    raise SystemExit("找不到快取資料,請先執行 backtest2.py")
cache_dir = os.path.join(root, folders[-1])

names = {}
try:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    with urllib.request.urlopen(url, timeout=30) as r:
        for row in json.loads(r.read().decode("utf-8")):
            names[row["Code"]] = row["Name"]
except Exception as e:
    print("取得股票名稱失敗(不影響計算):", str(e)[:80])

rows, first_date, last_date = [], None, None
for fn in os.listdir(cache_dir):
    if not fn.endswith(".json"):
        continue
    code = fn[:-5]
    with open(os.path.join(cache_dir, fn)) as f:
        data = sorted(json.load(f), key=lambda d: d["date"])
    data = [d for d in data if d.get("close") and d.get("volume") is not None]
    if len(data) < MIN_DAYS:
        continue
    first_date = data[0]["date"] if not first_date else min(first_date, data[0]["date"])
    last_date = data[-1]["date"] if not last_date else max(last_date, data[-1]["date"])
    closes = [d["close"] for d in data]
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = max(mdd, (peak - c) / peak)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    last60 = data[-60:]
    rows.append({
        "code": code, "name": names.get(code, ""), "close": closes[-1],
        "mdd": mdd, "vol": stdev(rets) * sqrt(TRADING_DAYS),
        "lots": mean(d["volume"] for d in last60) / 1000,
        "value": mean(d["volume"] * d["close"] for d in last60) / 1e8,
        "ma20": closes[-1] > mean(closes[-20:]),
        "ma60": closes[-1] > mean(closes[-60:]),
    })

print("資料區間:", first_date, "~", last_date, "| 歷史足夠的股票:", len(rows), "檔")
liquid = [r for r in rows if r["lots"] >= MIN_LOTS]
print("其中近60日平均成交量 >= %d 張:" % MIN_LOTS, len(liquid), "檔")
print()
print("最大回撤分布(僅計流動性合格者):")
for th in (0.15, 0.20, 0.25, 0.30, 0.40):
    print("  回撤 <= %d%%: %d 檔" % (th * 100, sum(1 for r in liquid if r["mdd"] <= th)))

picked = sorted((r for r in liquid if r["mdd"] <= MAX_DD), key=lambda r: -r["value"])
print()
print("符合回撤 <= %d%% 的共 %d 檔(依日均成交值由大到小,不是推薦順序):" % (MAX_DD * 100, len(picked)))
for r in picked[:40]:
    print("  %s %s | 收盤 %.2f | 回撤 %.1f%% | 年化波動 %.0f%% | 日均成交值 %.1f億 | 20MA%s 60MA%s" % (
        r["code"], r["name"], r["close"], r["mdd"] * 100, r["vol"] * 100, r["value"],
        "上" if r["ma20"] else "下", "上" if r["ma60"] else "下"))
if len(picked) > 40:
    print("  ...其餘請看 CSV")

if picked:
    outdir = os.path.expanduser("~/fugle/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "candidates_dd%d.csv" % (MAX_DD * 100))
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["代號", "名稱", "收盤", "最大回撤%", "年化波動%", "日均成交值(億)", "站上20MA", "站上60MA"])
        for r in picked:
            w.writerow([r["code"], r["name"], r["close"], round(r["mdd"] * 100, 1),
                        round(r["vol"] * 100), round(r["value"], 1),
                        "是" if r["ma20"] else "否", "是" if r["ma60"] else "否"])
    print("已存檔:", path)
