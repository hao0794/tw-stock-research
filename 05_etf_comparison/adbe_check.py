import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf

TICKER = "ADBE"
BENCH = "SPY"
TW = "0050.TW"
FX = "TWD=X"

print("下載資料中(Yahoo Finance)...")
raw = yf.download([TICKER, BENCH, TW, FX], period="max", auto_adjust=True, progress=False)
px = raw["Close"].dropna(how="all")
if TICKER not in px or px[TICKER].dropna().empty:
    raise SystemExit("取不到 %s 資料,請稍後再試" % TICKER)

def pct(x):
    return "  -  " if x is None or pd.isna(x) else "%+.1f%%" % (x * 100)

def max_dd(s):
    s = s.dropna()
    return (s / s.cummax() - 1).min()

us = px[[TICKER, BENCH]].dropna()
last = us.index[-1]
print("資料至:", last.date(), "| ADBE 最近收盤(還原) %.2f 美元" % us[TICKER].iloc[-1])
print()

print("=== 一、含息報酬:ADBE vs S&P 500(美元計價) ===")
for yrs in (1, 3, 5, 10, 15):
    start = last - pd.DateOffset(years=yrs)
    seg = us[us.index >= start]
    if seg.index[0] > start + pd.Timedelta(days=10):
        continue
    a = seg[TICKER].iloc[-1] / seg[TICKER].iloc[0] - 1
    b = seg[BENCH].iloc[-1] / seg[BENCH].iloc[0] - 1
    print("  近%2d年: ADBE %s(年化 %s) | S&P500 %s(年化 %s)" % (
        yrs, pct(a), pct((1 + a) ** (1 / yrs) - 1), pct(b), pct((1 + b) ** (1 / yrs) - 1)))

print()
print("=== 二、風險 ===")
ath = us[TICKER].cummax().iloc[-1]
ath_day = us[TICKER].idxmax()
r = us.pct_change().dropna()
r5 = r[r.index >= last - pd.DateOffset(years=5)]
print("  距歷史高點 %s(高點在 %s)" % (pct(us[TICKER].iloc[-1] / ath - 1), ath_day.date()))
print("  近5年最大回撤: ADBE %s | S&P500 %s" % (
    pct(max_dd(us[TICKER][us.index >= last - pd.DateOffset(years=5)])),
    pct(max_dd(us[BENCH][us.index >= last - pd.DateOffset(years=5)]))))
print("  近5年年化波動: ADBE %.0f%% | S&P500 %.0f%%" % (
    r5[TICKER].std() * np.sqrt(252) * 100, r5[BENCH].std() * np.sqrt(252) * 100))
print("  近5年與 S&P500 日報酬相關係數: %.2f" % r5[TICKER].corr(r5[BENCH]))
roll = (us / us.shift(252) - 1).dropna()
roll10 = roll[roll.index >= last - pd.DateOffset(years=10)]
if len(roll10):
    win = (roll10[TICKER] > roll10[BENCH]).mean()
    print("  近10年中,任一天買進持有1年,ADBE 贏 S&P500 的比例: %.0f%%" % (win * 100))

print()
print("=== 三、各年度含息報酬(美元) ===")
yearly = us.resample("YE").last().pct_change().dropna()
for d, row in yearly.tail(10).iterrows():
    print("  %d: ADBE %s | S&P500 %s%s" % (d.year, pct(row[TICKER]), pct(row[BENCH]),
          "(年初至今)" if d.year == last.year else ""))

print()
print("=== 四、換成台幣看(含匯率影響) ===")
if FX in px and TW in px:
    tw = pd.concat([px[TICKER], px[FX], px[TW]], axis=1, keys=["adbe", "fx", "tw"]).ffill().dropna()
    tw["adbe_twd"] = tw["adbe"] * tw["fx"]
    for yrs in (1, 3, 5):
        seg = tw[tw.index >= last - pd.DateOffset(years=yrs)]
        print("  近%d年: ADBE(台幣計) %s | 匯率變動 %s | 0050 %s" % (
            yrs, pct(seg["adbe_twd"].iloc[-1] / seg["adbe_twd"].iloc[0] - 1),
            pct(seg["fx"].iloc[-1] / seg["fx"].iloc[0] - 1),
            pct(seg["tw"].iloc[-1] / seg["tw"].iloc[0] - 1)))
    wk = tw[tw.index >= last - pd.DateOffset(years=3)][["adbe_twd", "tw"]].resample("W-FRI").last().pct_change().dropna()
    print("  近3年 ADBE(台幣計)與 0050 週報酬相關係數: %.2f" % wk["adbe_twd"].corr(wk["tw"]))
else:
    print("  匯率或 0050 資料取得失敗,略過")

print()
print("=== 五、基本面與估值(Yahoo 資料,僅供參考,請以 Adobe 財報為準) ===")
try:
    t = yf.Ticker(TICKER)
    info = t.info or {}
    def g(k, fmt="%.2f", scale=1):
        v = info.get(k)
        return "-" if v is None else fmt % (v * scale)
    print("  市值 %s 億美元 | 本益比(過去12月) %s | 預估本益比 %s" % (
        g("marketCap", "%.0f", 1e-8), g("trailingPE", "%.1f"), g("forwardPE", "%.1f")))
    print("  營收成長(最近一季年增) %s%% | 毛利率 %s%% | 營業利益率 %s%% | 淨利率 %s%%" % (
        g("revenueGrowth", "%.1f", 100), g("grossMargins", "%.1f", 100),
        g("operatingMargins", "%.1f", 100), g("profitMargins", "%.1f", 100)))
    print("  自由現金流 %s 億美元 | 現金股利: %s" % (
        g("freeCashflow", "%.0f", 1e-8), "無" if not info.get("dividendRate") else g("dividendRate")))
    fin = t.income_stmt
    if fin is not None and not fin.empty and "Total Revenue" in fin.index:
        rev = fin.loc["Total Revenue"].dropna().sort_index()
        ni = fin.loc["Net Income"].reindex(rev.index) if "Net Income" in fin.index else None
        print("  年度營收(億美元)與年增率:")
        prev = None
        for d, v in rev.items():
            gr = "" if prev is None else "(年增 %s)" % pct(v / prev - 1)
            n = "" if ni is None or pd.isna(ni[d]) else " | 淨利 %.0f" % (ni[d] / 1e8)
            print("    %s: %.0f%s%s" % (d.date(), v / 1e8, gr, n))
            prev = v
except Exception as e:
    print("  基本面資料取得失敗:", str(e)[:100])

print()
print("說明:價格為 Yahoo 還原價(含股息再投入、已處理分割);未扣手續費、匯費與稅;台幣計價用每日匯率換算。")
