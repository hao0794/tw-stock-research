import os, csv, json, time, urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, median
from fugle_marketdata import RestClient

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
EVAL_DAYS = 120

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
end_date = datetime(int(roc[:-4]) + 1911, int(roc[-4:-2]), int(roc[-2:])).date()
start = (end_date - timedelta(days=330)).isoformat()
end = end_date.isoformat()

codes = []
for r in rows:
    code = r["Code"]
    c = num(r["ClosingPrice"])
    if code.isdigit() and len(code) == 4 and not code.startswith("00") and c and c >= 20:
        codes.append(code)

cache_dir = os.path.expanduser("~/fugle/cache/" + end)
os.makedirs(cache_dir, exist_ok=True)

def load(code):
    path = os.path.join(cache_dir, code + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f), None
    last = ""
    for wait in (0, 20, 60):
        time.sleep(wait + 0.5)
        try:
            data = stock.historical.candles(**{"symbol": code, "from": start, "to": end,
                "fields": "open,high,low,close,volume"})["data"]
            with open(path, "w") as f:
                json.dump(data, f)
            return data, None
        except Exception as e:
            last = str(e)[:100]
    return None, last

print("資料日期至:", end, "| 待查股票:", len(codes), "檔(第一次約 5~8 分鐘,之後會用快取,很快)")
all_data, failed = {}, {}
for n, code in enumerate(codes, 1):
    data, err = load(code)
    if data:
        all_data[code] = sorted(data, key=lambda d: d["date"])
    else:
        failed[code] = err
    if n % 100 == 0:
        print("  進度", n, "/", len(codes))

ref = all_data.get("2330")
if not ref:
    raise SystemExit("2330 資料取得失敗,無法決定回測區間")
eval_dates = set(d["date"] for d in ref[-EVAL_DAYS:])
print("回測區間:", min(eval_dates), "~", max(eval_dates), "共", len(eval_dates), "個交易日")

feats = []
for code, data in all_data.items():
    closes = [d["close"] for d in data]
    for i in range(20, len(data)):
        d = data[i]
        if d["date"] not in eval_dates:
            continue
        o, h, l, c, v = d["open"], d["high"], d["low"], d["close"], d["volume"]
        prev = data[i - 1]["close"]
        if not (o and h and l and c and prev) or h <= l or c <= 25:
            continue
        pct = (c / prev - 1) * 100
        shadow = (h - max(o, c)) / (h - l)
        if pct < 3.0 or pct > 9.5 or shadow > 0.15:
            continue
        avg20 = mean(x["volume"] for x in data[i - 20:i])
        if avg20 <= 3_000_000:
            continue
        ratio = v / avg20
        if ratio < 1.5:
            continue
        ma5 = mean(closes[i - 4:i + 1])
        ma10 = mean(closes[i - 9:i + 1])
        ma20 = mean(closes[i - 19:i + 1])
        if not (c > ma5 > ma20):
            continue
        feats.append({"date": d["date"], "code": code, "close": c, "high": h,
                      "pct": pct, "shadow": shadow, "ratio": ratio,
                      "full": c > ma5 > ma10 > ma20,
                      "nxt": data[i + 1] if i + 1 < len(data) else None})

variants = [
    ("基準(你的條件)", dict(r=2.0, s=0.10, p=4.0, full=True)),
    ("量比放寬到 1.5 倍", dict(r=1.5, s=0.10, p=4.0, full=True)),
    ("上影線放寬到 15%", dict(r=2.0, s=0.15, p=4.0, full=True)),
    ("漲幅下限放寬到 3%", dict(r=2.0, s=0.10, p=3.0, full=True)),
    ("均線只要求 收盤>5MA>20MA", dict(r=2.0, s=0.10, p=4.0, full=False)),
    ("以上四項全部放寬", dict(r=1.5, s=0.15, p=3.0, full=False)),
]

def match(f, q):
    return (f["ratio"] > q["r"] and f["shadow"] <= q["s"] and f["pct"] >= q["p"]
            and (f["full"] or not q["full"]))

def outcome(f):
    n = f["nxt"]
    if not n or not all(n.get(k) for k in ("open", "high", "low", "close")):
        return None
    trig = to_tick(f["high"] + tick(f["high"]))
    if n["high"] < trig:
        return "未觸發"
    entry = max(n["open"], trig)
    stop = to_tick(f["close"] * 0.985)
    exit_p = stop if n["low"] <= stop else n["close"]
    return exit_p / entry - 1

print()
print("=== 命中次數與隔日表現(未扣手續費與證交稅,約 0.4~0.6%) ===")
base_hits = []
for name, q in variants:
    hits = [f for f in feats if match(f, q)]
    if name.startswith("基準"):
        base_hits = hits
    days = len(set(f["date"] for f in hits))
    res = [outcome(f) for f in hits]
    known = [x for x in res if x is not None]
    fired = [x for x in known if isinstance(x, float)]
    line = "%s: 命中 %d 筆(%d/%d 天有訊號) | 有次日資料 %d 筆, 觸發買進 %d 筆" % (
        name, len(hits), days, len(eval_dates), len(known), len(fired))
    if fired:
        line += " | 觸發者平均 %.2f%% 中位數 %.2f%% 勝率 %.0f%%" % (
            mean(fired) * 100, median(fired) * 100,
            sum(1 for x in fired if x > 0) / len(fired) * 100)
    print(line)

if base_hits:
    outdir = os.path.expanduser("~/fugle/output")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "backtest2_base.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期", "代號", "收盤", "漲幅%", "量比", "上影線%", "隔日結果"])
        for x in sorted(base_hits, key=lambda z: (z["date"], -z["ratio"])):
            res = outcome(x)
            if res is None:
                res = "無次日資料"
            elif isinstance(res, float):
                res = "%.2f%%" % (res * 100)
            w.writerow([x["date"], x["code"], x["close"], round(x["pct"], 2),
                        round(x["ratio"], 2), round(x["shadow"] * 100, 1), res])
    print("基準條件明細已存檔:", path)

print()
print("查詢失敗:", len(failed), "檔")
for code, msg in list(failed.items())[:10]:
    print("  ", code, msg)
