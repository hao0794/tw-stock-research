import os, json
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, median

EVAL_DAYS = 120
COST = 0.005  # 每筆來回成本概估(手續費+證交稅)

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

root = os.path.expanduser("~/fugle/cache")
folders = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
if not folders:
    raise SystemExit("找不到快取資料,請先執行 backtest2.py")
cache_dir = os.path.join(root, folders[-1])

all_data = {}
for fn in os.listdir(cache_dir):
    if fn.endswith(".json"):
        with open(os.path.join(cache_dir, fn)) as f:
            all_data[fn[:-5]] = sorted(json.load(f), key=lambda d: d["date"])

ref = all_data.get("2330")
if not ref:
    raise SystemExit("找不到 2330 資料")
eval_list = sorted(d["date"] for d in ref[-EVAL_DAYS:])
half = len(eval_list) // 2
first_half = set(eval_list[:half])
eval_dates = set(eval_list)
print("快取資料日期至:", folders[-1], "| 股票數:", len(all_data))
print("前半段:", eval_list[0], "~", eval_list[half - 1], "| 後半段:", eval_list[half], "~", eval_list[-1])

def ok(bar):
    return bar and all(bar.get(k) for k in ("open", "high", "low", "close"))

feats = []
for code, data in all_data.items():
    closes = [d["close"] for d in data]
    for i in range(20, len(data) - 1):
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
        n = data[i + 1]
        if not ok(n):
            continue
        n2 = data[i + 2] if i + 2 < len(data) and ok(data[i + 2]) else None
        feats.append({"date": d["date"], "close": c, "high": h, "pct": pct,
                      "shadow": shadow, "ratio": ratio,
                      "full": c > ma5 > ma10 > ma20, "nxt": n, "nxt2": n2})

def match(f, q):
    return (f["ratio"] > q["r"] and f["shadow"] <= q["s"] and f["pct"] >= q["p"]
            and (f["full"] or not q["full"]))

def close_entry(stop=None, days=1):
    def fn(f):
        entry = f["close"]
        bar = f["nxt"] if days == 1 else f["nxt2"]
        if bar is None:
            return None
        if stop is None:
            return bar["close"] / entry - 1
        s = entry * (1 - stop)
        n = f["nxt"]
        if n["open"] <= s:
            return n["open"] / entry - 1
        if n["low"] <= s:
            return s / entry - 1
        return n["close"] / entry - 1
    return fn

def close_to_next_open(f):
    return f["nxt"]["open"] / f["close"] - 1

def open_entry(stop=None):
    def fn(f):
        n = f["nxt"]
        entry = n["open"]
        if stop is not None and n["low"] <= entry * (1 - stop):
            return -stop
        return n["close"] / entry - 1
    return fn

def breakout_entry(stop=None):
    def fn(f):
        n = f["nxt"]
        trig = to_tick(f["high"] + tick(f["high"]))
        if n["high"] < trig:
            return None
        entry = max(n["open"], trig)
        if stop is not None and n["low"] <= entry * (1 - stop):
            return -stop
        return n["close"] / entry - 1
    return fn

combos = [
    ("今收買 → 隔日開盤賣", close_to_next_open),
    ("今收買 → 隔日收盤賣", close_entry()),
    ("今收買 → 隔日收盤賣, 停損2%", close_entry(0.02)),
    ("今收買 → 隔日收盤賣, 停損3%", close_entry(0.03)),
    ("今收買 → 持有兩天收盤賣", close_entry(days=2)),
    ("次開買 → 當日收盤賣", open_entry()),
    ("次開買 → 當日收盤賣, 停損2%", open_entry(0.02)),
    ("次開買 → 當日收盤賣, 停損3%", open_entry(0.03)),
    ("突破買 → 當日收盤賣", breakout_entry()),
    ("突破買 → 當日收盤賣, 停損2%(偏保守)", breakout_entry(0.02)),
    ("突破買 → 當日收盤賣, 停損3%(偏保守)", breakout_entry(0.03)),
    ("突破買 → 當日收盤賣, 停損5%(偏保守)", breakout_entry(0.05)),
]

def stats(vals):
    if not vals:
        return "無資料"
    net = [v - COST for v in vals]
    return "扣成本後平均 %+.2f%% 中位數 %+.2f%% 勝率 %.0f%% (%d筆)" % (
        mean(net) * 100, median(net) * 100,
        sum(1 for v in net if v > 0) / len(net) * 100, len(net))

def half_avg(vals):
    if not vals:
        return "  -  "
    return "%+.2f%%" % ((mean(vals) - COST) * 100)

variants = [
    ("全部放寬(樣本多,較可靠)", dict(r=1.5, s=0.15, p=3.0, full=False)),
    ("基準(你的條件,樣本少)", dict(r=2.0, s=0.10, p=4.0, full=True)),
]

print("(每筆扣 %.1f%% 成本;「前/後」為前半段與後半段扣成本後平均)" % (COST * 100))
for vname, q in variants:
    hits = [f for f in feats if match(f, q)]
    print()
    print("【%s】共 %d 筆訊號" % (vname, len(hits)))
    for cname, fn in combos:
        a, b, allv = [], [], []
        for f in hits:
            r = fn(f)
            if r is None:
                continue
            allv.append(r)
            (a if f["date"] in first_half else b).append(r)
        print("  %s: %s | 前 %s 後 %s" % (cname, stats(allv), half_avg(a), half_avg(b)))

print()
print("=== 測試:免費方案能否取得歷史分鐘K(只呼叫 1 次 API) ===")
try:
    from fugle_marketdata import RestClient
    stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
    last = date.fromisoformat(eval_list[-1])
    res = stock.historical.candles(**{"symbol": "2330",
        "from": (last - timedelta(days=7)).isoformat(), "to": last.isoformat(),
        "timeframe": "5", "fields": "open,high,low,close,volume"})
    rows = res.get("data", []) if isinstance(res, dict) else []
    print("回傳筆數:", len(rows))
    print("前2筆:", rows[:2])
except Exception as e:
    print("失敗:", str(e)[:150])
