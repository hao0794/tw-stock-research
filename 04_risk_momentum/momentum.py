import os, json, time, bisect
from datetime import date, datetime, timedelta
from math import ceil
from statistics import mean, median
from fugle_marketdata import RestClient

YEARS = 4                 # 抓幾年歷史(每次請求最多一年)
COST = 0.005              # 每個持有期換股一次的來回成本概估
MIN_LOTS = 3000           # 母體:近60日平均成交量下限(張)
THROTTLE = float(os.environ.get("MOM_THROTTLE", "0.4"))
BENCH = "0050"

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
today = date.today()

# ---------- 母體:沿用先前下載的快取,取流動性足夠者 ----------
root = os.path.expanduser("~/fugle/cache")
folders = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))) if os.path.isdir(root) else []
if not folders:
    raise SystemExit("找不到先前的快取資料,請先執行 backtest2.py")
src = os.path.join(root, folders[-1])
universe = []
for fn in sorted(os.listdir(src)):
    if not fn.endswith(".json"):
        continue
    with open(os.path.join(src, fn)) as f:
        data = sorted(json.load(f), key=lambda d: d["date"])
    data = [d for d in data if d.get("volume") is not None]
    if len(data) >= 60 and mean(d["volume"] for d in data[-60:]) / 1000 >= MIN_LOTS:
        universe.append(fn[:-5])
print("母體(近60日平均成交量 >= %d 張):%d 檔" % (MIN_LOTS, len(universe)))

# ---------- 下載歷史(可中斷續跑,已下載的會用快取) ----------
cache_dir = os.path.expanduser("~/fugle/cache_mom")
os.makedirs(cache_dir, exist_ok=True)

def call(symbol, start, end):
    err = ""
    for wait in (0, 60, 120):
        time.sleep(wait + THROTTLE)
        try:
            return stock.historical.candles(**{"symbol": symbol, "from": start.isoformat(),
                "to": end.isoformat(), "timeframe": "D", "fields": "close,volume,change"})["data"], ""
        except Exception as e:
            err = str(e)[:80]
    return None, err

def fetch(symbol):
    path = os.path.join(cache_dir, "%s_%s.json" % (symbol, today.isoformat()))
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f), ""
    rows, end = {}, today
    for k in range(YEARS):
        start = end - timedelta(days=364)
        data, err = call(symbol, start, end)
        if data is None:
            return None, err
        for d in data:
            rows[d["date"]] = d
        end = start - timedelta(days=1)
    out = sorted(rows.values(), key=lambda d: d["date"])
    with open(path, "w") as f:
        json.dump(out, f)
    return out, ""

def build(rows):
    rows = [d for d in rows if d.get("close") and d.get("volume") is not None]
    if rows and rows[-1]["date"] == today.isoformat() and datetime.now().hour < 15:
        rows = rows[:-1]
    n = len(rows)
    closes = [d["close"] for d in rows]
    refs = [None]
    for i in range(1, n):
        ch = rows[i].get("change")
        ref = rows[i]["close"] - ch if ch is not None else closes[i - 1]
        refs.append(ref if ref > 0 else closes[i - 1])
    adj = [0.0] * n
    adj[-1] = closes[-1]
    for i in range(n - 1, 0, -1):
        adj[i - 1] = adj[i] * refs[i] / closes[i]
    return [d["date"] for d in rows], adj

series, failed = {}, {}
codes = [BENCH] + universe
t0 = time.time()
for n, code in enumerate(codes, 1):
    rows, err = fetch(code)
    if rows:
        dates, adj = build(rows)
        if len(dates) > 300:
            series[code] = (dates, adj)
    else:
        failed[code] = err
    if n % 20 == 0 or n == len(codes):
        print("  進度 %d/%d | 已用 %.0f 分鐘 | 失敗 %d 檔" % (n, len(codes), (time.time() - t0) / 60, len(failed)))
if BENCH not in series:
    raise SystemExit("0050 資料取得失敗,無法比較")
if failed:
    print("下載失敗(可再執行一次補齊):", ", ".join(list(failed)[:15]), "..." if len(failed) > 15 else "")

# ---------- 月底日期(以 0050 的交易日為準) ----------
bdates = series[BENCH][0]
month_end = {}
for d in bdates:
    month_end[d[:7]] = d
me = [month_end[m] for m in sorted(month_end)]
print("資料區間:", bdates[0], "~", bdates[-1], "| 月底觀察點:", len(me))

def px(code, d):
    dates, adj = series[code]
    i = bisect.bisect_right(dates, d) - 1
    if i < 0:
        return None
    if (date.fromisoformat(d) - date.fromisoformat(dates[i])).days > 7:
        return None
    return adj[i]

def ret(code, d0, d1):
    a, b = px(code, d0), px(code, d1)
    return b / a - 1 if a and b else None

signals = [
    ("過去3個月動能", lambda c, k: ret(c, me[k - 3], me[k])),
    ("過去6個月動能(略過最近1個月)", lambda c, k: ret(c, me[k - 6], me[k - 1])),
    ("過去12個月動能(略過最近1個月)", lambda c, k: ret(c, me[k - 12], me[k - 1])),
]
ks = list(range(12, len(me) - 3))
if len(ks) < 12:
    raise SystemExit("可用的觀察月份太少,請確認資料是否完整")
half = len(ks) // 2
stocks = [c for c in series if c != BENCH]

def pct(x):
    return "%+.1f%%" % (x * 100)

for hold in (1, 3):
    for sname, sfn in signals:
        rec = {"bench": [], "uni": [], "med": [], "t20": [], "t10": [], "t1": [], "b20": [], "n": []}
        for k in ks:
            fwd_b = ret(BENCH, me[k], me[k + hold])
            if fwd_b is None:
                continue
            pairs = []
            for c in stocks:
                s, f = sfn(c, k), ret(c, me[k], me[k + hold])
                if s is not None and f is not None:
                    pairs.append((s, f))
            if len(pairs) < 40:
                continue
            pairs.sort(key=lambda p: -p[0])
            n = len(pairs)
            n20, n10 = max(1, round(n * 0.2)), max(1, round(n * 0.1))
            rec["bench"].append(fwd_b)
            rec["uni"].append(mean(p[1] for p in pairs))
            rec["med"].append(median(p[1] for p in pairs))
            rec["t20"].append(mean(p[1] for p in pairs[:n20]))
            rec["t10"].append(mean(p[1] for p in pairs[:n10]))
            rec["t1"].append(pairs[0][1])
            rec["b20"].append(mean(p[1] for p in pairs[-n20:]))
            rec["n"].append(n)
        m = len(rec["bench"])
        if m == 0:
            continue
        print()
        print("【%s | 每月選股、持有%d個月 | 觀察 %d 個月,平均母體 %d 檔】" % (sname, hold, m, mean(rec["n"])))
        print("  0050 平均 %s | 全體等權重平均 %s | 全體中位數 %s | 後20%%平均 %s" % (
            pct(mean(rec["bench"])), pct(mean(rec["uni"])), pct(mean(rec["med"])), pct(mean(rec["b20"]))))
        for label, key in (("前20%", "t20"), ("前10%", "t10")):
            ex_u = [a - b for a, b in zip(rec[key], rec["uni"])]
            ex_b = [a - b for a, b in zip(rec[key], rec["bench"])]
            h = len(ex_u) // 2
            print("  %s: 平均 %s | 贏全體 %.0f%% 的月份 | 對全體平均超額 %s(前半 %s 後半 %s) | 對0050超額 %s, 扣成本後 %s" % (
                label, pct(mean(rec[key])), sum(1 for x in ex_u if x > 0) / len(ex_u) * 100,
                pct(mean(ex_u)), pct(mean(ex_u[:h])), pct(mean(ex_u[h:])),
                pct(mean(ex_b)), pct(mean(ex_b) - COST)))
        t1 = rec["t1"]
        win = sum(1 for a, b in zip(t1, rec["bench"]) if a > b) / len(t1) * 100
        print("  只買第1名一檔: 平均 %s | 中位數 %s | 最差 %s | 最好 %s | 贏0050 %.0f%% 的月份" % (
            pct(mean(t1)), pct(median(t1)), pct(min(t1)), pct(max(t1)), win))

print()
print("說明:價格為還原權息後收盤價,不含現金股息;母體以今天的流動性條件挑選,有倖存者偏差;每個持有期以換股一次扣成本。")
