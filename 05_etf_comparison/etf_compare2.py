import os, sys, json, time
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import mean, stdev
from fugle_marketdata import RestClient

A = sys.argv[1] if len(sys.argv) > 1 else "006208"
B = sys.argv[2] if len(sys.argv) > 2 else "0050"
YEARS = int(sys.argv[3]) if len(sys.argv) > 3 else 10
YEAR_DAYS = 245

stock = RestClient(api_key=os.environ["FUGLE_API_KEY"]).stock
today = date.today()
cache_dir = os.path.expanduser("~/fugle/cache_watch")
os.makedirs(cache_dir, exist_ok=True)

def fetch(symbol):
    path = os.path.join(cache_dir, "%s_%s_%dy.json" % (symbol, today.isoformat(), YEARS))
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
            print("  %s 較早資料取得失敗,只用已取得部分: %s" % (symbol, err))
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
    value60 = mean(d["volume"] * d["close"] for d in rows[-60:]) / 1e8
    return dict(dates=dates, closes=closes, tr=tr, pr=pr, events=events, value60=value60)

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

def pct(x, d=1):
    return ("%+." + str(d) + "f%%") % (x * 100)

print("下載資料中(%d 年)..." % YEARS)
raw = {A: build(fetch(A)), B: build(fetch(B))}
start = max(raw[A]["dates"][1], raw[B]["dates"][1])
common = [d for d in sorted(set(raw[A]["dates"]) & set(raw[B]["dates"])) if d >= start]
years = len(common) / YEAR_DAYS
print("比較區間:", common[0], "~", common[-1], "(%d 個交易日,約 %.1f 年)" % (len(common), years))
print()

aligned = {}
for s in (A, B):
    x = raw[s]
    pos = {d: i for i, d in enumerate(x["dates"])}
    idx = [pos[d] for d in common]
    t = [0.0] * len(idx); p = [0.0] * len(idx)
    for k in range(1, len(idx)):
        gt = gp = 1.0
        for j in range(idx[k - 1] + 1, idx[k] + 1):
            gt *= 1 + x["tr"][j]; gp *= 1 + x["pr"][j]
        t[k], p[k] = gt - 1, gp - 1
    ti, pi = index_of(t), index_of(p)
    aligned[s] = t
    dvs = [e for e in x["events"] if e[1] == "除息" and e[0] >= common[0]]
    last_year = (date.fromisoformat(common[-1]) - timedelta(days=365)).isoformat()
    months = sorted(set(e[0][5:7] for e in dvs if e[0] > (date.fromisoformat(common[-1]) - timedelta(days=730)).isoformat()))
    print("==== %s ====" % s)
    print("  最近收盤 %.2f 元 | 近60日平均成交值 %.1f 億元" % (x["closes"][-1], x["value60"]))
    print("  含息總報酬 %s(年化 %s) | 只看價格 %s" % (pct(ti[-1] - 1), pct(ti[-1] ** (1 / years) - 1), pct(pi[-1] - 1)))
    print("  最大回撤(含息) %.1f%% | 年化波動 %.1f%%" % (max_dd(ti) * 100, stdev(t[1:]) * sqrt(YEAR_DAYS) * 100))
    print("  區間內除息 %d 次 | 近12個月殖利率約 %.2f%% | 近兩年除息月份: %s" % (
        len(dvs), sum(e[2] for e in dvs if e[0] > last_year) * 100, ", ".join(months) or "-"))
    for e in [e for e in x["events"] if e[0] >= common[0]][-6:]:
        print("    %s %s %s" % (e[0], e[1], ("%.2f%%" % (e[2] * 100)) if e[1] == "除息" else ("比例 %.3f" % e[2])))
    print()

a, b = aligned[A][1:], aligned[B][1:]
diff = [x - y for x, y in zip(a, b)]
ma, mb = mean(a), mean(b)
corr = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
ia, ib = index_of(aligned[A]), index_of(aligned[B])
print("==== %s 對 %s(兩者追蹤同一指數時,差距主要來自費用、現金與期貨部位、交易成本) ====" % (A, B))
print("  日報酬相關係數 %.4f" % corr)
print("  全期含息報酬差 %s | 年化報酬差 %s" % (pct(ia[-1] - ib[-1], 2), pct(ia[-1] ** (1 / years) - ib[-1] ** (1 / years), 2)))
print("  日報酬差的年化標準差(相對追蹤誤差) %.2f%%" % (stdev(diff) * sqrt(YEAR_DAYS) * 100))
print("  各年度含息報酬:")
by = {}
for d, x, y in zip(common[1:], a, b):
    by.setdefault(d[:4], []).append((x, y))
for yr in sorted(by):
    ga = gb = 1.0
    for x, y in by[yr]:
        ga *= 1 + x; gb *= 1 + y
    tag = "(年初至今)" if yr == common[-1][:4] else ("(部分年度)" if yr == common[0][:4] else "")
    print("    %s: %s %s | %s %s | 差 %s%s" % (yr, A, pct(ga - 1), B, pct(gb - 1), pct(ga - gb, 2), tag))
print()
print("說明:含息報酬假設股利再投入,未扣稅、二代健保與手續費;費用(經理費、保管費)已從淨值扣除,反映在報酬中。")
