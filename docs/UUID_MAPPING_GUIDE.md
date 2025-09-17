# 🆔 UUID ↔ Blockchain ID Mapping

## 📋 Обзор

Теперь бот поддерживает два типа ID для сделок:

1. **UUID** (User-Friendly ID) - показывается пользователям при создании сделок
2. **Blockchain ID** (Smart Contract ID) - реальный ID в смарт-контракте

## 🔄 Как это работает

### При создании сделки:
```
Пользователь создает сделку → Бот генерирует UUID → 
Пользователь подписывает в TronLink → Сделка попадает в блокчейн с blockchain_id → 
Бот сохраняет связь UUID ↔ blockchain_id в БД
```

### При подтверждении доставки:
```
Пользователь вводит UUID или blockchain_id → 
Бот ищет blockchain_id в БД → 
Выполняет операции с настоящим blockchain_id
```

## 🎯 Примеры использования

### ✅ Правильные форматы ID:

**UUID сделки** (из сообщений бота):
```
d9f4d52e-7a4e-4f66-b70c-fae4bd787720
```

**Blockchain ID** (числовой):
```
0
1
2
3
```

### ❌ Неправильные форматы:
```
abc123        # Не UUID и не число
-5            # Отрицательное число  
3.14          # Дробное число
random-text   # Не валидный UUID
```

## 🗄️ Структура базы данных

```sql
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,           -- Blockchain ID (0, 1, 2, ...)
    user_id TEXT NOT NULL,           -- Telegram ID пользователя
    amount_usdt REAL NOT NULL,       -- Сумма в USDT
    recipient TEXT NOT NULL,         -- TRON адрес получателя  
    status TEXT NOT NULL,            -- AWAITING_DELIVERY, COMPLETE, etc.
    role TEXT NOT NULL,              -- sender/recipient
    created_at INTEGER NOT NULL,     -- Unix timestamp
    uuid TEXT                        -- UUID сделки (может быть NULL)
);
```

## 🔍 Методы поиска

### По UUID:
```python
transaction = bot.db_get_transaction_by_uuid("d9f4d52e-7a4e-4f66-b70c-fae4bd787720")
blockchain_id = transaction[0]  # Получаем реальный blockchain_id
```

### По Blockchain ID:
```python  
# Стандартный поиск по blockchain_id остается как был
```

## 📝 Процесс работы с ботом

### 1. Создание сделки:
- Пользователь создает сделку через бота
- Бот показывает UUID: `d9f4d52e-7a4e-4f66-b70c-fae4bd787720`
- Пользователь подписывает транзакцию в TronLink
- Сделка получает blockchain_id: `3`
- Бот сохраняет связь в БД

### 2. Подтверждение доставки:
- Пользователь вводит либо UUID, либо blockchain_id
- Бот автоматически определяет тип и находит нужную сделку
- Выполняется подтверждение с правильным blockchain_id

## 🛠️ Технические детали

### Определение типа ID:
```python
if '-' in input_id and len(input_id) > 10:
    # Это UUID, ищем в БД
    db_transaction = bot.db_get_transaction_by_uuid(input_id)
else:
    # Это blockchain_id, используем как есть
    blockchain_id = int(input_id)
```

### Обработка ошибок:
- UUID не найден в БД → Показываем ошибку с кнопками навигации
- Blockchain_id не существует → Проверяем в блокчейне
- Неверный формат → Показываем примеры правильных форматов

## 🎉 Преимущества

✅ **User-Friendly**: Пользователи могут использовать UUID из сообщений бота
✅ **Обратная совместимость**: Старые blockchain_id тоже работают  
✅ **Безопасность**: Проверка существования сделок в блокчейне
✅ **Удобная навигация**: Кнопки возврата при ошибках

## 🚀 Статус

- ✅ Схема БД обновлена (добавлена колонка `uuid`)
- ✅ Методы поиска по UUID добавлены
- ✅ Логика обработки ввода обновлена
- ✅ Пользовательские сообщения обновлены
- ✅ Тестирование завершено

---

**Теперь пользователи могут вводить как UUID сделки из сообщений бота, так и традиционный blockchain ID!** 🎊