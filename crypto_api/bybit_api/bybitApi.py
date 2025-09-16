from pybit.unified_trading import HTTP
from datetime import datetime, timezone, timedelta

def get_long_short_ratio(symbol="ETHUSDT", period="5min", category="linear"):
    session = HTTP()
    resp = session.get_long_short_ratio(
        category=category,
        symbol=symbol,
        period=period,
        limit=1
    )

    ratios = resp.get("result", {}).get("list", [])
    if not ratios:
        result = "Нет данных"
        return result

    for entry in ratios:
        ts = int(entry["timestamp"]) / 1000
        t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        result = f"{t}:\nLong: {entry['buyRatio']}%\nShort: {entry['sellRatio']}%"
    return result

def get_funding_rate(symbol, limit=1):
    """
    Получает funding rate от Bybit
    """
    try:
        session = HTTP()

        # Просто получаем последние funding rates без startTime
        response = session.get_funding_rate_history(
            category="linear",
            symbol=symbol,
            limit=limit
        )

        rates = response.get("result", {}).get("list", [])
        if not rates:
            return f"Нет данных funding rate для {symbol}"

        results = []
        for item in rates:
            ts = int(item.get("fundingRateTimestamp") or item.get("timestamp") or 0)
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            funding_rate = float(item.get("fundingRate", 0)) * 100
            results.append(f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')} — Funding Rate: {funding_rate:.5f}%")

        return "\n".join(results)

    except Exception as e:
        return f"Ошибка при получении funding rate для {symbol}: {e}"