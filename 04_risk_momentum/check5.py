import os, json, time
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import mean, median, stdev
from fugle_marketdata import RestClient

SYMBOLS = ["2884", "2887", "2412", "2892", "2801"]
NAMES = {"2884": "玉山金", "2887": "台新新光金", "2412": "中華電", "2892": "第一金", "2801": "彰銀"}
BENCH = "0050"
YEARS = 3          # 抓幾年歷史(每次請求最多一年,所以分段抓)
COST = 0.005       # 每筆來回成本概估
HARD_STOP = 0.08   # 固定百分比停損
YEAR_DAYS = 245

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
cache_dir = os.path.expanduser("~/fugle/cache_watch")
os.makedirs(cache_dir, exist_ok=True)
today = date.today()

def fetch(symbol):
    path = os.path.join(cache_dir, "%s_%s.json" % (symbol, today.isoformat()))
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, end, err = {}, today, ""
    for k in range(YEARS):
        start = end - timedelta(days=364)
        data = None
        for wait in (0, 20, 60):
            time.sleep(wait + 0.5)
            try:
                data = stock.historical.candles(**{"symbol": symbol, "from": start.isoformat(),
                    "to": end.isoformat(), "timeframe": "D",
                    "fields": "open,high,low,close,volume,change"})["data"]
                break
            except Exception as e:
                err = str(e)[:100]
        if data is None:
            if k == 0:
                raise SystemExit("%s 查詢失敗: %s" % (symbol, err))
            print(symbol, "較早期資料取得失敗,僅用已取得的部分:", err)
            break
        for d in data:
            rows[d["date"]] = d
        end = start - timedelta(days=1)
    out = sorted(rows.values(), key=lambda d: d["date"])
    with open(path, "w") as f:
        json.dump(out, f)
    return out

def build(rows):
    rows = [d for d in rows if d.get("close") and d.get("volume") is not None]
    if rows and rows[-1]["date"] == today.isoformat() and datetime.now().hour < 15:
        rows = rows[:-1]  # 盤中尚未完成的今日資料不用
    n = len(rows)
    closes = [d["close"] for d in rows]
    refs, flags = [None], []
    for i in range(1, n):
        ch = rows[i].get("change")
        ref = rows[i]["close"] - ch if ch is not None else closes[i - 1]
        if ref <= 0:
            ref = closes[i - 1]
        refs.append(ref)
        if abs(ref - closes[i - 1]) / closes[i - 1] > 0.003:
            flags.append(rows[i]["date"])
    adj = [0.0] * n
    adj[-1] = closes[-1]
    for i in range(n - 1, 0, -1):
        adj[i - 1] = adj[i] * refs[i] / closes[i]
    return rows, closes, adj, flags

def max_dd(series):
    peak, m = series[0], 0.0
    for x in series:
        peak = max(peak, x)
        m = max(m, (peak - x) / peak)
    return m

def rets(series):
    return [series[i] / series[i - 1] - 1 for i in range(1, len(series))]

def pearson(a, b):
    ma, mb = mean(a), mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else float("nan")

def simulate(adj, rule):
    n, trades, i = len(adj), [], 60
    while i < n:
        if not (adj[i] > mean(adj[i - 19:i + 1]) and adj[i] > mean(adj[i - 59:i + 1])):
            i += 1
            continue
        entry, exit_j = adj[i], None
        for j in range(i + 1, n):
            c = adj[j]
            if ((rule["ma"] and c < mean(adj[j - rule["ma"] + 1:j + 1]))
                    or (rule["stop"] and c <= entry * (1 - rule["stop"]))
                    or (rule["low10"] and c < min(adj[j - 10:j]))):
                exit_j = j
                break
        if exit_j is None:
            trades.append({"ret": adj[-1] / entry - 1, "days": n - 1 - i, "open": True, "early": False})
            break
        after = adj[exit_j + 1:exit_j + 21]
        early = bool(after) and max(after) >= adj[exit_j] * 1.05
        trades.append({"ret": adj[exit_j] / entry - 1, "days": exit_j - i, "open": False, "early": early})
        i = exit_j + 1
    return trades

rules = [
    ("跌破20日均線", dict(ma=20, stop=0, low10=False)),
    ("跌破60日均線", dict(ma=60, stop=0, low10=False)),
    ("硬停損8%", dict(ma=0, stop=HARD_STOP, low10=False)),
    ("硬停損8% + 跌破20日均線", dict(ma=20, stop=HARD_STOP, low10=False)),
    ("硬停損8% + 跌破60日均線", dict(ma=60, stop=HARD_STOP, low10=False)),
    ("收盤跌破前10日最低收盤", dict(ma=0, stop=0, low10=True)),
]

print("下載歷史資料(第一次約 1 分鐘)...")
bench_rows, _, bench_adj, _ = build(fetch(BENCH))
bench_map = {d["date"]: a for d, a in zip(bench_rows, bench_adj)}

for sym in SYMBOLS:
    rows, closes, adj, flags = build(fetch(sym))
    n = len(rows)
    print()
    print("==== %s %s | 資料 %s ~ %s(%d 個交易日)====" % (sym, NAMES.get(sym, ""), rows[0]["date"], rows[-1]["date"], n))
    if n < 300:
        print("  注意:資料不足 300 個交易日,測試結果參考性低")
    y = adj[-YEAR_DAYS:]
    common = [d["date"] for d in rows[-YEAR_DAYS:] if d["date"] in bench_map]
    sa = {d["date"]: a for d, a in zip(rows, adj)}
    ra = [sa[common[i]] / sa[common[i - 1]] - 1 for i in range(1, len(common))]
    rb = [bench_map[common[i]] / bench_map[common[i - 1]] - 1 for i in range(1, len(common))]
    corr = pearson(ra, rb) if len(ra) > 30 else float("nan")
    value = mean(d["volume"] * d["close"] for d in rows[-60:]) / 1e8
    print("  收盤 %.2f | 近1年最大回撤 %.1f%% | 全期最大回撤 %.1f%% | 年化波動 %.0f%% | 日均成交值 %.1f億" % (
        closes[-1], max_dd(y) * 100, max_dd(adj) * 100, stdev(rets(y)) * sqrt(YEAR_DAYS) * 100, value))
    print("  與0050相關係數(近1年) %.2f | 20MA%s 60MA%s | 距近60日高點 %.1f%%" % (
        corr, "上" if adj[-1] > mean(adj[-20:]) else "下", "上" if adj[-1] > mean(adj[-60:]) else "下",
        (adj[-1] / max(adj[-60:]) - 1) * 100))
    print("  疑似除權息日(價格已還原) %d 個: %s" % (len(flags), ", ".join(flags[-6:]) if flags else "無"))
    print("  出場規則測試(進場條件:收盤站上20與60日均線;一次一筆;已扣成本 %.1f%%):" % (COST * 100))
    for name, rule in rules:
        tr = simulate(adj, rule)
        if not tr:
            print("   %s: 無交易" % name)
            continue
        net = [t["ret"] - COST for t in tr]
        comp = 1.0
        for r in net:
            comp *= 1 + r
        closed = [t for t in tr if not t["open"]]
        early = sum(1 for t in closed if t["early"])
        print("   %s: %d筆 勝率%.0f%% 平均%+.1f%% 中位數%+.1f%% 最差%+.1f%% 平均持有%d天 賣早%s 累積%+.0f%%" % (
            name, len(tr), sum(1 for r in net if r > 0) / len(net) * 100, mean(net) * 100,
            median(net) * 100, min(net) * 100, mean(t["days"] for t in tr),
            ("%d/%d" % (early, len(closed))) if closed else "-", (comp - 1) * 100))
    print("   對照:自第61天起買進持有不動: %+.0f%%(未含股息、未扣成本)" % ((adj[-1] / adj[60] - 1) * 100))

print()
print("說明:價格為還原權息後的收盤價,不含現金股息;賣早=出場後20個交易日內曾比出場價高5%以上")
