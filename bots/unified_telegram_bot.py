#!/usr/bin/env python3
"""
Объединенный Telegram Bot для USDT Escrow и криптоаналитики
Содержит функционал эскроу-сделок на TRON и аналитику криптовалют
"""

import os
import logging
import json
import uuid
import sys
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Добавляем путь к проекту для импорта модулей
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Импорты для криптоаналитики
from crypto_api.binance_api.binanceApi import Candles_info_binanceApi, get_binance_funding_rate
from crypto_api.coingeko_api.coingekoApi import CoinGeko_market_cap, CoinGeko_btc_dominance
from crypto_api.yfinance_api.yfinanceApi import Yfinance_get_index_stats
from crypto_api.bybit_api.bybitApi import get_funding_rate, get_long_short_ratio
from crypto_api.alternativeme_api.alternativemeApi import FearGreedAPI

# Импорт для эскроу (копируем из скриптов)
from scripts.tron_escrow_usdt_client import TronEscrowUSDTClient
from binance.client import Client
import time
import qrcode
from io import BytesIO
import base64
import sqlite3

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
class Config:
    def __init__(self):
        self.config = self.load_config()
        
        # Токен бота (из переменных окружения или config)
        self.BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN') or self.config.get('bot', {}).get('token')
        
        if not self.BOT_TOKEN:
            raise ValueError("Токен бота не указан! Укажите TELEGRAM_BOT_TOKEN в .env файле или в config.json")
        
        # TRON настройки
        self.NETWORK = self.config.get('settings', {}).get('default_network', 'shasta')
        network_config = self.config.get('networks', {}).get(self.NETWORK, {})
        self.ESCROW_CONTRACT = network_config.get('escrow_contract', "TWHHy4MM95NdRQcWWoJZSQeZg3KmmTsUXt")
        self.USDT_CONTRACT = network_config.get('usdt_contract', "TKZDdu947FtxWHLRKUXnhNZ6bar9RrZ7Wv")
        self.ARBITRATOR_ADDRESS = network_config.get('arbitrator_address', "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2")
        
        # Файлы для хранения данных
        self.USERS_DATA_FILE = "users_data.json"
        self.PENDING_TRANSACTIONS_FILE = "pending_transactions.json"
        
        # URL для TronLink интеграции
        self.WEB_APP_URL = self.config.get('bot', {}).get('web_app_url', "https://goodelita1.github.io/tron-escrow-interface/tronlink_interface.html")
        
    def load_config(self):
        """Загрузка конфигурации из JSON файла"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
        return {}

class UnifiedCryptoBot:
    # ================== КРИПТОВАЛЮТЫ И КОНСТАНТЫ ==================
    COINS = {
        "eth": "ETHUSDT", "btc": "BTCUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
        "ldo": "LDOUSDT", "atom": "ATOMUSDT", "uni": "UNIUSDT", "near": "NEARUSDT",
        "ltc": "LTCUSDT", "link": "LINKUSDT", "dot": "DOTUSDT", "doge": "DOGEUSDT",
        "avax": "AVAXUSDT", "ape": "APEUSDT", "ada": "ADAUSDT", "op": "OPUSDT",
        "arb": "ARBUSDT", "pol": "POLUSDT", "trx": "TRXUSDT", "bch": "BCHUSDT"
    }
    
    TIMEFRAMES = {
        "15m": (Client.KLINE_INTERVAL_15MINUTE, "15 минут"),
        "1h": (Client.KLINE_INTERVAL_1HOUR, "1 час"),
        "4h": (Client.KLINE_INTERVAL_4HOUR, "4 часа"), 
        "1d": (Client.KLINE_INTERVAL_1DAY, "1 день"),
        "1w": (Client.KLINE_INTERVAL_1WEEK, "1 неделя"),
        "1m": (Client.KLINE_INTERVAL_1MONTH, "1 месяц")
    }
    
    def __init__(self):
        self.config = Config()
        self.users_data = self.load_users_data()
        self.pending_transactions = self.load_pending_transactions()
        self.db_path = os.path.join(os.path.dirname(__file__), 'unified_escrow.db')
        self.user_states = {}  # Добавляем стек состояний для навигации
        self.init_db()

    def load_users_data(self):
        """Загрузка данных пользователей"""
        try:
            if os.path.exists(self.config.USERS_DATA_FILE):
                with open(self.config.USERS_DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки данных пользователей: {e}")
        return {}
    
    def save_users_data(self):
        """Сохранение данных пользователей"""
        try:
            with open(self.config.USERS_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.users_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных пользователей: {e}")
    
    def load_pending_transactions(self):
        """Загрузка ожидающих транзакций"""
        try:
            if os.path.exists(self.config.PENDING_TRANSACTIONS_FILE):
                with open(self.config.PENDING_TRANSACTIONS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки ожидающих транзакций: {e}")
        return {}
    
    def save_pending_transactions(self):
        """Сохранение ожидающих транзакций"""
        try:
            with open(self.config.PENDING_TRANSACTIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.pending_transactions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения ожидающих транзакций: {e}")

    def get_db_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        created_at INTEGER
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        amount_usdt REAL NOT NULL,
                        recipient TEXT NOT NULL,
                        status TEXT NOT NULL,
                        role TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)")
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")

    def db_upsert_user(self, user_id: str, username: str, first_name: str):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO users (id, username, first_name, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        username = excluded.username,
                        first_name = excluded.first_name
                """, (user_id, username, first_name, int(time.time())))
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя в БД: {e}")

    # ================== ГЛАВНОЕ МЕНЮ ==================
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start с объединенным меню"""
        user = update.effective_user
        user_id = str(user.id)
        username = user.username or "неизвестно"
        first_name = user.first_name or "неизвестно"
        
        # Сохраняем пользователя в БД
        self.db_upsert_user(user_id, username, first_name)
        
        # Сохраняем базовые данные пользователя
        if user_id not in self.users_data:
            self.users_data[user_id] = {
                'username': username,
                'first_name': first_name,
                'created_at': datetime.now().isoformat()
            }
            self.save_users_data()

        keyboard = [
            [InlineKeyboardButton("💰 Эскроу сделки", callback_data='escrow_menu')],
            [InlineKeyboardButton("📊 Криптоаналитика", callback_data='crypto_menu')],
            [InlineKeyboardButton("👤 Мой профиль", callback_data='my_profile')],
            [InlineKeyboardButton("ℹ️ Справка", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            f"🤖 Добро пожаловать в Unified Crypto Bot!\n\n"
            f"👋 Привет, {first_name}!\n\n"
            f"🔐 **Эскроу сделки** - безопасные P2P сделки с USDT на TRON\n"
            f"📈 **Криптоаналитика** - данные с бирж и индексы рынка\n\n"
            f"Выберите нужный раздел:"
        )
        
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== ЭСКРОУ МЕНЮ ==================
    async def escrow_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню эскроу функций"""
        keyboard = [
            [InlineKeyboardButton("🆕 Создать сделку", callback_data='create_escrow')],
            [InlineKeyboardButton("📋 Мои сделки", callback_data='my_transactions')],
            [InlineKeyboardButton("🔍 Статус сделки", callback_data='check_transaction')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "💰 **Эскроу сделки**\n\n"
            f"🌐 Сеть: {self.config.NETWORK}\n"
            f"📋 Контракт: `{self.config.ESCROW_CONTRACT}`\n"
            f"⚖️ Арбитр: `{self.config.ARBITRATOR_ADDRESS}`\n\n"
            "Выберите действие:"
        )
        
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== КРИПТОВАЛЮТЫ И КОНСТАНТЫ ==================
    COINS = {
        "eth": "ETHUSDT", "btc": "BTCUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
        "ldo": "LDOUSDT", "atom": "ATOMUSDT", "uni": "UNIUSDT", "near": "NEARUSDT",
        "ltc": "LTCUSDT", "link": "LINKUSDT", "dot": "DOTUSDT", "doge": "DOGEUSDT",
        "avax": "AVAXUSDT", "ape": "APEUSDT", "ada": "ADAUSDT", "op": "OPUSDT",
        "arb": "ARBUSDT", "pol": "POLUSDT", "trx": "TRXUSDT", "bch": "BCHUSDT"
    }
    
    TIMEFRAMES = {
        "15m": (Client.KLINE_INTERVAL_15MINUTE, "15 минут"),
        "1h": (Client.KLINE_INTERVAL_1HOUR, "1 час"),
        "4h": (Client.KLINE_INTERVAL_4HOUR, "4 часа"), 
        "1d": (Client.KLINE_INTERVAL_1DAY, "1 день"),
        "1w": (Client.KLINE_INTERVAL_1WEEK, "1 неделя"),
        "1m": (Client.KLINE_INTERVAL_1MONTH, "1 месяц")
    }
    
    def __init__(self):
        self.config = Config()
        self.users_data = self.load_users_data()
        self.pending_transactions = self.load_pending_transactions()
        self.db_path = os.path.join(os.path.dirname(__file__), 'unified_escrow.db')
        self.user_states = {}  # Добавляем стек состояний для навигации
        self.init_db()
    
    def create_coins_menu(self):
        """Создает меню выбора криптовалют"""
        buttons = []
        row = []
        for i, coin in enumerate(self.COINS, start=1):
            row.append(InlineKeyboardButton(coin.upper(), callback_data=f'coin_{coin}'))
            if i % 4 == 0:  # 4 монеты в ряд
                buttons.append(row)
                row = []
        if row:  # остатки
            buttons.append(row)
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data='crypto_menu')])
        return InlineKeyboardMarkup(buttons)
    
    def create_timeframes_menu(self, coin):
        """Создает меню временных интервалов для конкретной монеты"""
        buttons = []
        for tf, (_, label) in self.TIMEFRAMES.items():
            buttons.append([InlineKeyboardButton(label, callback_data=f'chart_{coin}_{tf}')])
        buttons.append([InlineKeyboardButton("⬅️ Назад к монетам", callback_data='coins_chart_menu')])
        return InlineKeyboardMarkup(buttons)
    
    def create_funding_coins_menu(self):
        """Создает меню выбора монет для funding rates"""
        buttons = []
        row = []
        for i, coin in enumerate(self.COINS, start=1):
            row.append(InlineKeyboardButton(coin.upper(), callback_data=f'funding_{coin}'))
            if i % 4 == 0:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data='crypto_menu')])
        return InlineKeyboardMarkup(buttons)
        
    def create_longshort_coins_menu(self):
        """Создает меню выбора монет для long/short ratio"""
        buttons = []
        row = []
        for i, coin in enumerate(self.COINS, start=1):
            row.append(InlineKeyboardButton(coin.upper(), callback_data=f'longshort_{coin}'))
            if i % 4 == 0:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data='crypto_menu')])
        return InlineKeyboardMarkup(buttons)

    # ================== КРИПТОАНАЛИТИКА МЕНЮ ==================
    async def crypto_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню криптоаналитики"""
        keyboard = [
            [InlineKeyboardButton("📈 Графики монет", callback_data='coins_chart_menu')],
            [InlineKeyboardButton("₿ BTC Dominance", callback_data='btc_dominance')],
            [InlineKeyboardButton("🔥 Fear & Greed", callback_data='fear_greed')],
            [InlineKeyboardButton("📊 Фондовые индексы", callback_data='stock_indexes')],
            [InlineKeyboardButton("💹 Funding Rates", callback_data='funding_rates_menu')],
            [InlineKeyboardButton("⚖️ Long/Short Ratio", callback_data='longshort_menu')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "📊 **Криптоаналитика**\n\n"
            "🔸 **Графики монет** - 20 криптовалют, 6 таймфреймов\n"
            "🔸 **BTC Dominance** - доминация Bitcoin\n" 
            "🔸 **Fear & Greed** - индекс страха и жадности\n"
            "🔸 **Фондовые индексы** - S&P 500, NASDAQ и др.\n"
            "🔸 **Funding Rates** - ставки финансирования\n"
            "🔸 **Long/Short Ratio** - соотношения позиций\n\n"
            "Выберите категорию:"
        )
        
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== ОБРАБОТЧИКИ КРИПТОАНАЛИТИКИ ==================
    async def btc_dominance_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик BTC доминации"""
        query = update.callback_query
        await query.answer()
        
        try:
            response = CoinGeko_btc_dominance()
            text = f"₿ **Bitcoin Dominance**\n\n{response}"
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        # Добавляем кнопку назад
        keyboard = [[InlineKeyboardButton("⬅️ Назад к анализу", callback_data='crypto_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def fear_greed_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик Fear & Greed Index"""
        query = update.callback_query
        await query.answer()
        
        try:
            text = FearGreedAPI.get_index()
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад к анализу", callback_data='crypto_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def stock_indexes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик фондовых индексов"""
        query = update.callback_query
        await query.answer()
        
        try:
            response = Yfinance_get_index_stats('1d')
            text = f"📊 **Фондовые индексы (1 день)**\n\n{response}"
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад к анализу", callback_data='crypto_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== FUNDING RATES ДЛЯ ВСЕХ МОНЕТ ==================
    async def funding_rates_menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню выбора монет для funding rates"""
        query = update.callback_query
        await query.answer()
        
        text = (
            "💹 **Funding Rates**\n\n"
            "🔸 Данные с Binance и Bybit\n"
            "🔸 20 криптовалют доступны\n\n"
            "Выберите монету:"
        )
        
        reply_markup = self.create_funding_coins_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def funding_coin_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик funding rate для конкретной монеты"""
        query = update.callback_query
        data = query.data
        coin = data.split('_')[1]  # funding_btc -> btc
        
        await query.answer()
        
        if coin not in self.COINS:
            await query.edit_message_text("❌ Неизвестная монета")
            return
        
        try:
            symbol = self.COINS[coin]
            
            # Получаем данные с обеих бирж
            binance_result = get_binance_funding_rate(symbol, 1)
            bybit_result = get_funding_rate(symbol)
            
            text = (
                f"💹 **{coin.upper()} Funding Rates**\n\n"
                f"🔸 **Binance:**\n{binance_result}\n\n"
                f"🔸 **Bybit:**\n{bybit_result}"
            )
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад к funding", callback_data='funding_rates_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    # ================== LONG/SHORT RATIO ДЛЯ ВСЕХ МОНЕТ ==================
    async def longshort_menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню выбора монет для long/short ratio"""
        query = update.callback_query
        await query.answer()
        
        text = (
            "⚖️ **Long/Short Ratio**\n\n"
            "🔸 Данные с Bybit\n"
            "🔸 20 криптовалют доступны\n\n"
            "Выберите монету:"
        )
        
        reply_markup = self.create_longshort_coins_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def longshort_coin_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик long/short ratio для конкретной монеты"""
        query = update.callback_query
        data = query.data
        coin = data.split('_')[1]  # longshort_btc -> btc
        
        await query.answer()
        
        if coin not in self.COINS:
            await query.edit_message_text("❌ Неизвестная монета")
            return
        
        try:
            symbol = self.COINS[coin]
            
            # Получаем long/short ratio с Bybit
            response = get_long_short_ratio(symbol, "1h", "linear")
            
            text = f"⚖️ **{coin.upper()} Long/Short Ratio**\n\n{response}"
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад к long/short", callback_data='longshort_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== НОВЫЕ ОБРАБОТЧИКИ МОНЕТ ==================
    async def coins_chart_menu_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню выбора криптовалют для графиков"""
        query = update.callback_query
        await query.answer()
        
        text = (
            "📈 **Графики монет**\n\n"
            "🔸 20 криптовалют доступны\n"
            "🔸 6 временных интервалов\n\n"
            "Выберите криптовалюту:"
        )
        
        reply_markup = self.create_coins_menu()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def coin_timeframes_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик выбора конкретной монеты"""
        query = update.callback_query
        data = query.data
        coin = data.split('_')[1]  # coin_eth -> eth
        
        await query.answer()
        
        if coin not in self.COINS:
            await query.edit_message_text("❌ Неизвестная монета")
            return
        
        text = (
            f"📈 **{coin.upper()} - Графики**\n\n"
            f"Тикер: `{self.COINS[coin]}`\n\n"
            "Выберите временной интервал:"
        )
        
        reply_markup = self.create_timeframes_menu(coin)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def chart_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик получения графика конкретной монеты"""
        query = update.callback_query
        data = query.data
        _, coin, timeframe = data.split('_', 2)  # chart_eth_1h -> ['chart', 'eth', '1h']
        
        await query.answer()
        
        if coin not in self.COINS or timeframe not in self.TIMEFRAMES:
            await query.edit_message_text("❌ Неверные параметры")
            return
        
        try:
            symbol = self.COINS[coin]
            interval, timeframe_label = self.TIMEFRAMES[timeframe]
            
            response = Candles_info_binanceApi(interval, symbol, 1)
            text = f"📈 **{coin.upper()} ({timeframe_label})**\n\n{response}"
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
        
        keyboard = [[InlineKeyboardButton(f"⬅️ Назад к {coin.upper()}", callback_data=f'coin_{coin}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== ПРОСТЫЕ ЭСКРОУ ФУНКЦИИ (из оригинала) ==================
    async def create_escrow_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Создание новой эскроу сделки"""
        query = update.callback_query
        await query.answer()
        
        transaction_id = str(uuid.uuid4())
        
        keyboard = [
            [InlineKeyboardButton("💳 Подписать через TronLink", 
                                web_app=WebAppInfo(url=self.config.WEB_APP_URL))],
            [InlineKeyboardButton("📝 Проверить статус", callback_data=f'check_tx_status_{transaction_id}')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='escrow_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🆕 **Создание новой сделки**\n\n"
            f"🆔 ID сделки: `{transaction_id}`\n\n"
            "📋 Инструкции:\n"
            "1. Нажмите 'Подписать через TronLink'\n"
            "2. В открывшемся окне введите данные сделки\n"
            "3. Подпишите транзакцию в TronLink\n"
            "4. Проверьте статус сделки\n\n"
            "⚠️ Убедитесь что у вас установлен TronLink!"
        )
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def my_transactions_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр сделок пользователя"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
                transactions = cur.fetchall()
                
            if not transactions:
                text = "📋 У вас пока нет активных сделок."
            else:
                text = "📋 **Ваши сделки:**\n\n"
                for tx in transactions:
                    tx_id, _, amount, recipient, status, role, created_at = tx
                    created_date = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
                    text += (
                        f"🆔 ID: {tx_id}\n"
                        f"💰 Сумма: {amount} USDT\n"
                        f"👤 Получатель: {recipient[:10]}...\n"
                        f"📊 Статус: {status}\n"
                        f"🎭 Роль: {role}\n"
                        f"📅 Создано: {created_date}\n\n"
                    )
                    
        except Exception as e:
            text = f"❌ Ошибка получения данных: {e}"
            
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='escrow_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== NAVIGATION HANDLERS ==================
    async def back_to_main_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Возврат в главное меню"""
        await self.start_command(update, context)

    async def my_profile_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Профиль пользователя"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        user_id = str(user.id)
        
        # Получаем статистику пользователя
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ?", (user_id,))
                tx_count = cur.fetchone()[0]
                
        except:
            tx_count = 0
            
        text = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: `{user.id}`\n"
            f"👤 Имя: {user.first_name or 'неизвестно'}\n"
            f"📧 Username: @{user.username or 'не указан'}\n"
            f"📊 Сделок: {tx_count}\n"
            f"🌐 Сеть: {self.config.NETWORK}\n"
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def help_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Справка"""
        query = update.callback_query
        await query.answer()
        
        text = (
            "ℹ️ **Справка по боту**\n\n"
            "**💰 Эскроу сделки:**\n"
            "• Безопасные P2P сделки с USDT\n"
            "• Используется смарт-контракт на TRON\n"
            "• Интеграция с TronLink кошельком\n\n"
            "**📊 Криптоаналитика:**\n"
            "• Bitcoin доминация (CoinGecko)\n"
            "• Данные по Ethereum (Binance)\n"
            "• Fear & Greed Index\n"
            "• Фондовые индексы (Yahoo Finance)\n"
            "• Funding rates (Binance, Bybit)\n"
            "• Long/Short соотношения\n\n"
            "**🔒 Безопасность:**\n"
            "• Боту не передаются приватные ключи\n"
            "• Подписание через TronLink\n"
            "• Данные хранятся локально\n\n"
            "❓ Вопросы? Свяжитесь с администратором."
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    # ================== CALLBACK QUERY ROUTER ==================
    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Главный роутер callback запросов"""
        query = update.callback_query
        data = query.data
        
        logger.info(f"Обработка callback: {data}")
        
        # Навигация
        if data == 'back_to_main':
            await self.back_to_main_handler(update, context)
        elif data == 'my_profile':
            await self.my_profile_handler(update, context)
        elif data == 'help':
            await self.help_handler(update, context)
            
        # Главные меню
        elif data == 'escrow_menu':
            await self.escrow_menu(update, context)
        elif data == 'crypto_menu':
            await self.crypto_menu(update, context)
            
        # Эскроу функции
        elif data == 'create_escrow':
            await self.create_escrow_handler(update, context)
        elif data == 'my_transactions':
            await self.my_transactions_handler(update, context)
            
        # Криптоаналитика - основные функции
        elif data == 'btc_dominance':
            await self.btc_dominance_handler(update, context)
        elif data == 'fear_greed':
            await self.fear_greed_handler(update, context)
        elif data == 'stock_indexes':
            await self.stock_indexes_handler(update, context)
            
        # Графики монет
        elif data == 'coins_chart_menu':
            await self.coins_chart_menu_handler(update, context)
        elif data.startswith('coin_'):
            await self.coin_timeframes_handler(update, context) 
        elif data.startswith('chart_'):
            await self.chart_handler(update, context)
            
        # Funding rates для всех монет
        elif data == 'funding_rates_menu':
            await self.funding_rates_menu_handler(update, context)
        elif data.startswith('funding_') and data != 'funding_rates_menu':
            await self.funding_coin_handler(update, context)
            
        # Long/Short ratio для всех монет
        elif data == 'longshort_menu':
            await self.longshort_menu_handler(update, context)
        elif data.startswith('longshort_'):
            await self.longshort_coin_handler(update, context)
        
        # Проверка статуса транзакции (упрощенно)
        elif data.startswith('check_tx_status_'):
            await query.answer()
            tx_id = data.replace('check_tx_status_', '')
            text = (
                f"🔍 **Проверка статуса сделки**\n\n"
                f"🆔 ID: `{tx_id}`\n"
                f"📊 Статус: В ожидании\n\n"
                f"💡 Функция будет доступна после настройки TRON клиента."
            )
            keyboard = [[InlineKeyboardButton("⬅️ Назад к эскроу", callback_data='escrow_menu')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        
        else:
            await query.answer("❌ Неизвестная команда")

def main():
    """Запуск бота"""
    print("🚀 Запуск Unified Crypto & Escrow Bot...")
    
    try:
        bot = UnifiedCryptoBot()
        print(f"📋 Токен бота загружен")
        print(f"🌐 Сеть TRON: {bot.config.NETWORK}")
        print(f"📋 Контракт: {bot.config.ESCROW_CONTRACT}")
        print(f"⚖️ Арбитр: {bot.config.ARBITRATOR_ADDRESS}")
        print("✅ Бот готов к работе с объединенным функционалом!")
        
        # Создаем приложение
        application = Application.builder().token(bot.config.BOT_TOKEN).build()
        
        # Добавляем обработчики
        application.add_handler(CommandHandler("start", bot.start_command))
        application.add_handler(CallbackQueryHandler(bot.callback_query_handler))
        
        # Запускаем бота
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    main()