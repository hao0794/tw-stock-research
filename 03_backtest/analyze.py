import os, json
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, median

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
print("快取資料日期至:", folders[-1], "| 股票數:", len(all_data))

ref = all_data.get("2330")
if not ref:
    raise SystemExit("找不到 2330 資料")
eval_dates = set(d["date"] for d in ref[-EVAL_DAYS:])

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
        if not all(n.get(k) for k in ("open", "high", "low", "close")):
            continue
        feats.append({"date": d["date"], "close": c, "high": h, "pct": pct,
                      "shadow": shadow, "ratio": ratio,
                      "full": c > ma5 > ma10 > ma20, "nxt": n})

def match(f, q):
    return (f["ratio"] > q["r"] and f["shadow"] <= q["s"] and f["pct"] >= q["p"]
            and (f["full"] or not q["full"]))

def show(name, vals):
    if not vals:
        print("  %s: 無資料" % name)
        return
    print("  %s: 平均 %.2f%% | 中位數 %.2f%% | 勝率 %.0f%% | %d 筆" % (
        name, mean(vals) * 100, median(vals) * 100,
        sum(1 for v in vals if v > 0) / len(vals) * 100, len(vals)))

variants = [
    ("基準(你的條件)", dict(r=2.0, s=0.10, p=4.0, full=True)),
    ("全部放寬(樣本較多)", dict(r=1.5, s=0.15, p=3.0, full=False)),
]

print("(以下皆未扣手續費與證交稅,約 0.4~0.6%)")
for name, q in variants:
    hits = [f for f in feats if match(f, q)]
    print()
    print("【%s】共 %d 筆訊號" % (name, len(hits)))
    print(" 一、不設任何進場規則,看訊號股隔天的走勢:")
    show("隔日開盤 對 今日收盤(跳空)", [f["nxt"]["open"] / f["close"] - 1 for f in hits])
    show("隔日開盤買、收盤賣(日內)", [f["nxt"]["close"] / f["nxt"]["open"] - 1 for f in hits])
    show("今日收盤買、隔日收盤賣", [f["nxt"]["close"] / f["close"] - 1 for f in hits])
    fired_a, fired_b = [], []
    for f in hits:
        n = f["nxt"]
        trig = to_tick(f["high"] + tick(f["high"]))
        if n["high"] < trig:
            continue
        entry = max(n["open"], trig)
        stop = to_tick(f["close"] * 0.985)
        fired_b.append(n["close"] / entry - 1)
        fired_a.append((stop if n["low"] <= stop else n["close"]) / entry - 1)
    print(" 二、依你的規則(次日突破今日最高價+1檔才買),共觸發 %d 筆:" % len(fired_a))
    show("出場A:碰到停損(收盤-1.5%)就出場,偏保守", fired_a)
    show("出場B:不設停損,持有到當天收盤,偏樂觀", fired_b)
