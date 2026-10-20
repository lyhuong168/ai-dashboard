"""Daily closing prices + volume for GOOGL, NVDA, AAPL -> data/stock_prices.csv.

Source: Yahoo Finance via the yfinance library (tier 2 market data, not an exchange feed).
Re-runnable: rewrites the CSV from scratch and refreshes the source rows.
"""
import csv

from collectors.common import DATA, add_source, today

TICKERS = {"GOOGL": "Google", "NVDA": "Nvidia", "AAPL": "Apple"}


def run(period="2y"):
    import yfinance as yf

    rows, last = [], {}
    for t in TICKERS:
        hist = yf.Ticker(t).history(period=period, auto_adjust=False)
        if hist.empty:
            raise RuntimeError("no price data returned for %s" % t)
        for ts, r in hist.iterrows():
            rows.append([ts.strftime("%Y-%m-%d"), t, round(float(r["Close"]), 4), int(r["Volume"])])
        last[t] = rows[-1][0]
    rows.sort(key=lambda r: (r[0], r[1]))
    with open(DATA / "stock_prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "ticker", "close", "volume"])
        w.writerows(rows)
    for t, company in TICKERS.items():
        add_source({
            "company": company, "title": "%s daily prices (Yahoo Finance via yfinance)" % t,
            "url": "https://finance.yahoo.com/quote/%s/history" % t, "publisher": "Yahoo Finance (yfinance)",
            "doc_type": "market_data", "tier": "2", "published_date": last[t], "retrieved_date": today()})
    print("prices: %d rows, latest %s" % (len(rows), max(last.values())))


if __name__ == "__main__":
    run()
