import requests
from datetime import datetime

class FearGreedAPI:
    @staticmethod
    def get_index():
        url = "https://api.alternative.me/fng/"
        response = requests.get(url).json()
        data = response['data'][0]

        value = data['value']
        classification = data['value_classification']
        timestamp = datetime.fromtimestamp(int(data['timestamp']))
        readable_time = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        # Инициализируем result как пустую строку
        result = (
            "📊 Fear & Greed Index\n"
            "------------------------\n"
            f"🧠 Значение:         {value}\n"
            f"📈 Классификация:    {classification}\n"
            f"⏰ Время обновления:  {readable_time}\n"
        )

        return result