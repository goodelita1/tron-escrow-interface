from datetime import datetime, timezone, timedelta
import os
from dotenv import load_dotenv
from binance.client import Client

load_dotenv()

api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

client = Client(api_key, api_secret)

def Candles_info_binanceApi(interval, symbol, limit):
    candles = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    result = ""
    for c in candles:
        open_price = float(c[1])
        high_price = float(c[2])
        low_price = float(c[3])
        close_price = float(c[4])
        avg_price = (high_price + low_price) / 2

        open_time = datetime.fromtimestamp(c[0] / 1000)

        result += (
            f"Open time: {open_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Open: {open_price}\n"
            f"High: {high_price}\n"
            f"Low: {low_price}\n"
            f"Close: {close_price}\n"
            f"Average Price: {avg_price:.4f}\n"
            "------------------------\n"
        )
    return result

def get_binance_funding_rate(symbol, limit=1, hours=8):
    """
    symbol: тикер, например 'BTCUSDT'
    limit: количество последних записей
    hours: если указано, возвращает данные только за последние N часов
    """
    client = Client()
    try:
        funding_rates = client.futures_funding_rate(symbol=symbol, limit=limit)
        result_list = []

        now = datetime.now(timezone.utc)
        if hours:
            cutoff = now - timedelta(hours=hours)
        else:
            cutoff = None

        for item in funding_rates:
            ts = int(item['fundingTime'])
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            if cutoff and dt < cutoff:
                continue  # пропускаем записи старше указанного периода

            rate = float(item['fundingRate']) * 100
            result_list.append(f"{dt.strftime('%Y-%m-%d %H:%M:%S %Z')} — Funding Rate: {rate:.5f}%")

        if not result_list:
            return f"Нет данных funding rate для {symbol} за последние {hours} часов"
        
        return "\n".join(result_list)

    except Exception as e:
        return f"Ошибка при получении funding rate Binance: {e}"