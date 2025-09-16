import yfinance as yf

indexes = {
    "S&P 500": "^GSPC",
    "Dow Jones": "^DJI",
    "NASDAQ": "^IXIC",
    "Nikkei 225": "^N225",
    "Russell 2000": "^RUT"
}
    
def Yfinance_get_index_stats(period):
    result = ""
    for name, ticker in indexes.items():
        data = yf.Ticker(ticker)
        hist = data.history(period=period)

        if hist.empty:
            print(f"{name}: Нет данных за последний месяц")
            continue

        low_price = hist['Low'].min()
        high_price = hist['High'].max()
        close_price = hist['Close'].iloc[-1]

        range_change_pct = ((high_price - low_price) / low_price) * 100

        current_change_pct = ((close_price - low_price) / low_price) * 100

        result += (
            f"{name}:\n"
            f"  Min month: {low_price:.2f}\n"
            f"  Max month: {high_price:.2f}\n"
            f"  Day close price: {close_price:.2f}\n"
            f"  difference (min → max): {range_change_pct:+.2f}%\n"
            f"  difference (min → close): {current_change_pct:+.2f}%\n\n"
        )
    return result