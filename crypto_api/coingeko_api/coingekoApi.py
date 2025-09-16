from pycoingecko import CoinGeckoAPI

cg = CoinGeckoAPI()
        
def CoinGeko_market_cap(coin_id, interval):
    result = ""
    data = cg.get_coin_by_id(id=coin_id)
    market_cap = data['market_data']['market_cap']['usd']
    change_procents_per_time = data['market_data'][interval]

    result += (
        f"Рыночная капитализация {coin_id.capitalize()}: {market_cap:,} USD\n"
        f"Изменение: {change_procents_per_time['usd']:.2f}%"
    )
    return result
        
def CoinGeko_btc_dominance():
    result = ""
    global_data = cg.get_global()
    btc_dominance = global_data['market_cap_percentage']['btc']

    result += (
        f"Доминация Bitcoin: {btc_dominance:.2f}%"
    )
    return result