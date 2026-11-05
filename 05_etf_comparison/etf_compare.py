import os, json, time
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import mean, stdev
from fugle_marketdata import RestClient

SYMBOLS = [("00919", "群益台灣精選高息"), ("0050", "元大台灣50")]
YEARS = 4
YEAR_DAYS = 245

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
today = date.today()
cache_dir = os.path.expanduser("~/fugle/cache_watch")
os.makedirs(cache_dir, exist_ok=True)

def fetch(symbol):
    path = os.path.join(cache_dir, "%s_%s.json" % (symbol, today.isoformat()))
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    rows, end = {}, today
    for k in range(YEARS):
        start = end - timedelta(days=364)
        data, err = None, ""
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
            break
        if not data:
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
        rows = rows[:-1]
    dates = [d["date"] for d in rows]
    closes = [d["close"] for d in rows]
    tr, pr, events = [None], [None], []
    for i in range(1, len(rows)):
        ch = rows[i].get("change")
        ref = rows[i]["close"] - ch if ch is not None else closes[i - 1]
        if ref <= 0:
            ref = closes[i - 1]
        prev = closes[i - 1]
        ratio = ref / prev
        tr.append(closes[i] / ref - 1)
        if ratio < 0.7:
            pr.append(closes[i] / ref - 1)
            events.append((dates[i], "分割/調整", ratio))
        else:
            pr.append(closes[i] / prev - 1)
            if prev - ref > prev * 0.003:
                events.append((dates[i], "除息", (prev - ref) / prev))
    return dates, closes, tr, pr, events

def index_of(daily):
    out = [1.0]
    for r in daily[1:]:
        out.append(out[-1] * (1 + r))
    return out

def max_dd(series):
    peak, m = series[0], 0.0
    for x in series:
        peak = max(peak, x)
        m = max(m, (peak - x) / peak)
    return m

def pct(x):
    return "%+.1f%%" % (x * 100)

print("下載資料中...")
raw = {s: build(fetch(s)) for s, _ in SYMBOLS}

start = max(raw[s][0][1] for s, _ in SYMBOLS)
common = sorted(set(raw["00919"][0]) & set(raw["0050"][0]))
common = [d for d in common if d >= start]
print("比較區間:", common[0], "~", common[-1], "(%d 個交易日)" % len(common))
print()

aligned = {}
for s, name in SYMBOLS:
    dates, closes, tr, pr, events = raw[s]
    pos = {d: i for i, d in enumerate(dates)}
    idx = [pos[d] for d in common]
    t = [0.0] + [None] * (len(idx) - 1)
    p = [0.0] + [None] * (len(idx) - 1)
    for k in range(1, len(idx)):
        gt = gp = 1.0
        for j in range(idx[k - 1] + 1, idx[k] + 1):
            gt *= 1 + tr[j]
            gp *= 1 + pr[j]
        t[k], p[k] = gt - 1, gp - 1
    ti, pi = index_of(t), index_of(p)
    years = len(common) / YEAR_DAYS
    dvs = [e for e in events if e[1] == "除息" and e[0] >= common[0]]
    last_year = (date.fromisoformat(common[-1]) - timedelta(days=365)).isoformat()
    aligned[s] = t
    print("==== %s %s ====" % (s, name))
    print("  含息總報酬 %s(年化 %s) | 只看價格 %s | 配息貢獻約 %s" % (
        pct(ti[-1] - 1), pct(ti[-1] ** (1 / years) - 1), pct(pi[-1] - 1), pct(ti[-1] - pi[-1])))
    print("  最大回撤(含息) %.1f%% | 年化波動 %.0f%%" % (max_dd(ti) * 100, stdev(t[1:]) * sqrt(YEAR_DAYS) * 100))
    print("  區間內除息 %d 次 | 近12個月殖利率合計約 %.1f%%" % (
        len(dvs), sum(e[2] for e in dvs if e[0] > last_year) * 100))
    for e in [e for e in events if e[0] >= common[0]][-8:]:
        print("    %s %s %s" % (e[0], e[1], ("%.2f%%" % (e[2] * 100)) if e[1] == "除息" else ("比例 %.3f" % e[2])))
    print("  各年度含息報酬:")
    by_year = {}
    for d, r in zip(common[1:], t[1:]):
        by_year.setdefault(d[:4], []).append(r)
    for y in sorted(by_year):
        g = 1.0
        for r in by_year[y]:
            g *= 1 + r
        print("    %s: %s%s" % (y, pct(g - 1), "(年初至今)" if y == common[-1][:4] else ("(部分年度)" if y == common[0][:4] else "")))
    print()

a, b = aligned["00919"][1:], aligned["0050"][1:]
ma, mb = mean(a), mean(b)
corr = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / sqrt(
    sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
print("00919 與 0050 日報酬相關係數: %.2f" % corr)
print("說明:含息總報酬假設股利再投入、未扣稅與二代健保;只看價格=不含配息;配息組成(是否含收益平準金)價格資料看不出來。")
