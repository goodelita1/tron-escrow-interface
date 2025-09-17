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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
        
        # Файлы для хранения данных (в папке bots)
        bots_dir = os.path.dirname(__file__)
        self.USERS_DATA_FILE = os.path.join(bots_dir, "users_data.json")
        self.PENDING_TRANSACTIONS_FILE = os.path.join(bots_dir, "pending_transactions.json")
        
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
                        created_at INTEGER NOT NULL,
                        uuid TEXT UNIQUE
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)")
                
                # Миграция: добавляем колонку uuid если её нет
                try:
                    cur.execute("ALTER TABLE transactions ADD COLUMN uuid TEXT UNIQUE")
                    logger.info("Добавлена колонка uuid в таблицу transactions")
                except sqlite3.OperationalError:
                    # Колонка уже существует
                    pass
                
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_uuid ON transactions(uuid)")
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
    
    def db_add_transaction(self, user_id: str, tx_id: int, amount_usdt: float, recipient: str, role: str, status: str, created_at: int, uuid: str = None):
        """Добавление транзакции в БД с UUID"""
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR REPLACE INTO transactions (id, user_id, amount_usdt, recipient, status, role, created_at, uuid)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (tx_id, user_id, amount_usdt, recipient, status, role, created_at, uuid))
                conn.commit()
                logger.info(f"Транзакция добавлена в БД: blockchain_id={tx_id}, uuid={uuid}")
        except Exception as e:
            logger.error(f"Ошибка добавления транзакции в БД: {e}")
    
    def db_get_transaction_by_uuid(self, uuid: str):
        """Получение транзакции по UUID"""
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, user_id, amount_usdt, recipient, status, role, created_at, uuid 
                    FROM transactions WHERE uuid = ?
                """, (uuid,))
                result = cur.fetchone()
                if result:
                    logger.info(f"Найдена транзакция по UUID {uuid}: blockchain_id={result[0]}")
                else:
                    logger.info(f"Транзакция с UUID {uuid} не найдена в БД")
                return result
        except Exception as e:
            logger.error(f"Ошибка поиска транзакции по UUID: {e}")
            return None
    
    def db_update_transaction_mapping(self, uuid: str, blockchain_id: int):
        """Обновление связи UUID -> blockchain_id"""
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE transactions SET id = ? WHERE uuid = ?
                """, (blockchain_id, uuid))
                conn.commit()
                logger.info(f"Обновлена связь: UUID {uuid} -> blockchain_id {blockchain_id}")
        except Exception as e:
            logger.error(f"Ошибка обновления связи: {e}")

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
            [InlineKeyboardButton("✅ Подтвердить сделку", callback_data='confirm_escrow')],
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
        """Начало создания новой эскроу сделки"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        transaction_id = str(uuid.uuid4())
        
        # Сохраняем состояние пользователя
        self.user_states[user_id] = {
            'state': 'waiting_recipient',
            'transaction_id': transaction_id,
            'data': {}
        }
        
        # Сохраняем UUID в pending_transactions для отслеживания
        self.pending_transactions[transaction_id] = {
            'user_id': user_id,
            'created_at': int(time.time()),
            'status': 'creating',
            'data': {}
        }
        self.save_pending_transactions()
        
        keyboard = [[InlineKeyboardButton("⬅️ Отмена", callback_data='escrow_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "🆕 **Создание Escrow сделки**\n\n"
            f"🆔 ID: `{transaction_id}`\n\n"
            "📨 **Шаг 1/2: Адрес получателя**\n\n"
            "Введите TRON адрес получателя USDT:\n"
            "(Например: TJtq3AVtNTngU23HFinp22rh6Ufcy78Ce4)"
        )
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстового ввода пользователя"""
        user_id = str(update.effective_user.id)
        
        if user_id not in self.user_states:
            return  # Пользователь не в процессе создания сделки
        
        user_state = self.user_states[user_id]
        text = update.message.text.strip()
        
        if user_state['state'] == 'waiting_recipient':
            await self.handle_recipient_input(update, context, text)
        elif user_state['state'] == 'waiting_amount':
            await self.handle_amount_input(update, context, text)
        elif user_state['state'] == 'waiting_transaction_id':
            await self.handle_transaction_id_input(update, context, text)
    
    async def handle_recipient_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, recipient_address: str):
        """Обработка ввода адреса получателя"""
        user_id = str(update.effective_user.id)
        
        # Проверяем формат TRON адреса
        if not recipient_address.startswith('T') or len(recipient_address) != 34:
            await update.message.reply_text(
                "⚠️ **Некорректный адрес!**\n\n"
                "TRON адрес должен:\n"
                "• Начинаться с 'T'\n"
                "• Содержать 34 символа\n\n"
                "Повторите попытку:",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Сохраняем адрес и переходим к следующему шагу
        self.user_states[user_id]['data']['recipient'] = recipient_address
        self.user_states[user_id]['state'] = 'waiting_amount'
        
        keyboard = [[InlineKeyboardButton("⬅️ Отмена", callback_data='escrow_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Адрес принят: `{recipient_address}`\n\n"
            "💰 **Шаг 2/2: Сумма**\n\n"
            "Введите сумму USDT:\n"
            "Например: 10 или 10.5",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_amount_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, amount_text: str):
        """Обработка ввода суммы"""
        user_id = str(update.effective_user.id)
        
        try:
            amount = float(amount_text)
            if amount <= 0 or amount > 10000:
                raise ValueError("Некорректная сумма")
        except ValueError:
            await update.message.reply_text(
                "⚠️ **Некорректная сумма!**\n\n"
                "Введите положительное число от 0.1 до 10000 USDT\n"
                "Повторите попытку:",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Преобразуем в микро-единицы USDT (6 десятичных знаков)
        usdt_amount = int(amount * 1000000)
        
        # Сохраняем данные и сразу создаем финальную ссылку
        user_state = self.user_states[user_id]
        transaction_id = user_state['transaction_id']
        data = user_state['data']
        data['amount'] = amount
        data['usdt_amount'] = usdt_amount
        
        # Формируем данные для TronLink (только 3 параметра для смарт-контракта)
        transaction_data = {
            "type": "escrow_create",
            "contract": self.config.ESCROW_CONTRACT,
            "parameters": {
                "recipient": data['recipient'],
                "amount": usdt_amount,
                "deadline": int(time.time()) + 48*3600  # 48 часов
            },
            "usdt_contract": self.config.USDT_CONTRACT,
            "usdt_amount": usdt_amount,
            "network": self.config.NETWORK,
            "display_info": {
                "arbitrator": self.config.ARBITRATOR_ADDRESS,
                "description": f"Escrow сделка {amount} USDT"
            }
        }
        
        # Отладочный вывод
        logger.info(f"Transaction data: {json.dumps(transaction_data, indent=2)}")
        
        # Кодируем данные
        encoded_data = base64.b64encode(json.dumps(transaction_data).encode()).decode()
        # Добавляем timestamp для обхода кеша браузера
        cache_buster = int(time.time())
        tronlink_url = f"{self.config.WEB_APP_URL}?data={encoded_data}&v={cache_buster}"
        
        logger.info(f"Generated URL length: {len(tronlink_url)}")
        logger.info(f"URL: {tronlink_url[:200]}...")
        
        # Обновляем pending_transactions с полными данными
        if transaction_id in self.pending_transactions:
            self.pending_transactions[transaction_id].update({
                'status': 'pending_signature',
                'data': {
                    'recipient': data['recipient'],
                    'amount': amount
                }
            })
            self.save_pending_transactions()
            logger.info(f"Обновлен UUID {transaction_id} в pending_transactions")
        
        # Очищаем состояние пользователя
        del self.user_states[user_id]
        
        keyboard = [
            [InlineKeyboardButton("💳 Подписать через TronLink", url=tronlink_url)],
            [InlineKeyboardButton("📝 Проверить статус", callback_data=f'check_tx_status_{transaction_id}')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='escrow_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        summary_text = (
            "✅ **Escrow сделка готова!**\n\n"
            f"🆔 ID: `{transaction_id}`\n"
            f"📨 Получатель: `{data['recipient']}`\n"
            f"💰 Сумма: {amount} USDT\n\n"
            "📋 **Дальше:**\n"
            "1. Нажмите 'Подписать через TronLink'\n"
            "2. Откроется браузер с интерфейсом\n"
            "3. Подтвердите транзакцию в TronLink\n\n"
            "⚠️ Убедитесь, что TronLink установлен и разблокирован!"
        )
        
        await update.message.reply_text(summary_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_transaction_id_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_id: str):
        """Обработка ввода transaction ID (поддерживает UUID и blockchain ID)"""
        user_id = str(update.effective_user.id)
        input_id = transaction_id.strip()
        
        # Определяем тип ввода: UUID или blockchain ID
        tx_id = None
        is_uuid = False
        
        # Проверяем, является ли это UUID (содержит тире и буквы)
        if '-' in input_id and len(input_id) > 10:
            # Это похоже на UUID - ищем в базе данных
            db_transaction = self.db_get_transaction_by_uuid(input_id)
            if db_transaction:
                tx_id = db_transaction[0]  # blockchain_id из БД
                is_uuid = True
                logger.info(f"Найден UUID {input_id} -> blockchain_id {tx_id} в БД")
            else:
                # UUID не найден - показываем ошибку
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='confirm_escrow')],
                    [InlineKeyboardButton("🏠 Главная", callback_data='back_to_main')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"❌ UUID сделки не найден!\n\n"
                    f"🆔 Сделка с UUID {input_id} не найдена в базе данных.\n\n"
                    "🔍 Проверьте правильность UUID и попробуйте снова.",
                    reply_markup=reply_markup
                )
                return
        else:
            # Проверяем формат blockchain ID (целое число)
            try:
                tx_id = int(input_id)
                if tx_id < 0:
                    raise ValueError("Отрицательный ID")
                logger.info(f"Введен blockchain_id: {tx_id}")
            except ValueError:
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='confirm_escrow')],
                    [InlineKeyboardButton("🏠 Главная", callback_data='back_to_main')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "⚠️ **Некорректный ID!**\n\n"
                    "Введите один из вариантов:\n\n"
                    "• **UUID сделки** (из сообщения бота)\n"
                    "например: `d9f4d52e-7a4e-4f66-b70c-fae4bd787720`\n\n"
                    "• **Blockchain ID** (число)\n"
                    "например: `3`\n\n"
                    "🔄 Попробуйте снова!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
        
        # НОВАЯ ПРОВЕРКА: Проверяем существование сделки в блокчейне
        try:
            temp_client = TronEscrowUSDTClient(
                private_key="0000000000000000000000000000000000000000000000000000000000000001",  # Dummy key для чтения
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            tx_info = temp_client.get_transaction(tx_id)
            
            if not tx_info:
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='confirm_escrow')],
                    [InlineKeyboardButton("🏠 Главная", callback_data='back_to_main')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"❌ **Сделка не найдена!**\n\n"
                    f"🆔 Сделка с ID {tx_id} не существует в блокчейне.\n\n"
                    "🔍 Проверьте правильность ID и попробуйте снова.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
            
            # Проверяем статус сделки
            if tx_info.get('state') != 'AWAITING_DELIVERY':
                status_display = {
                    'AWAITING_PAYMENT': '🔄 Ожидание оплаты',
                    'COMPLETE': '✅ Уже завершена',
                    'REFUNDED': '🔙 Возвращена',
                    'DISPUTED': '⚠️ В споре'
                }.get(tx_info.get('state'), '❓ Неизвестный')
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Попробовать снова", callback_data='confirm_escrow')],
                    [InlineKeyboardButton("🏠 Главная", callback_data='back_to_main')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"❌ **Нельзя подтвердить эту сделку!**\n\n"
                    f"🆔 Сделка #{tx_id}\n"
                    f"📊 Текущий статус: {status_display}\n\n"
                    "📝 Подтвердить можно только сделки\n"
                    "в статусе '⏳ Ожидание доставки'",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return
                
        except Exception as e:
            logger.error(f"Ошибка проверки сделки: {e}")
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data='confirm_escrow')],
                [InlineKeyboardButton("🏠 Главная", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ **Ошибка проверки сделки!**\n\n"
                f"Детали: {str(e)}\n\n"
                "Попробуйте снова или обратитесь к поддержке.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return
        
        # Формируем данные для TronLink (тип confirm_delivery)
        transaction_data = {
            "type": "confirm_delivery",
            "contract": self.config.ESCROW_CONTRACT,
            "parameters": {
                "transactionId": tx_id
            },
            "network": self.config.NETWORK,
            "display_info": {
                "arbitrator": self.config.ARBITRATOR_ADDRESS,
                "description": f"Подтверждение сделки {tx_id}"
            }
        }
        
        # Отладочный вывод
        logger.info(f"Confirm transaction data: {json.dumps(transaction_data, indent=2)}")
        
        # Кодируем данные
        encoded_data = base64.b64encode(json.dumps(transaction_data).encode()).decode()
        # Добавляем timestamp для обхода кеша браузера
        cache_buster = int(time.time())
        tronlink_url = f"{self.config.WEB_APP_URL}?data={encoded_data}&v={cache_buster}"
        
        logger.info(f"Generated confirm URL length: {len(tronlink_url)}")
        logger.info(f"Confirm URL: {tronlink_url[:200]}...")
        
        # Получаем информацию о сделке из БД или блокчейна
        amount_info = ""
        recipient_info = ""
        
        # Если UUID был передан, ищем в БД
        if is_uuid:
            try:
                db_transaction = self.db_get_transaction_by_uuid(input_id)
                if db_transaction:
                    amount_info = f"💰 Сумма: {db_transaction[2]} USDT\n"
                    recipient_info = f"👤 Получатель: {db_transaction[3]}\n"
            except:
                pass
        
        # Если не нашли в БД, пытаемся получить из блокчейна
        if not amount_info:
            try:
                blockchain_amount = tx_info.get('amount', 0) / 1000000
                blockchain_recipient = tx_info.get('recipient', '')
                if blockchain_amount > 0:
                    amount_info = f"💰 Сумма: {blockchain_amount:.1f} USDT\n"
                if blockchain_recipient:
                    recipient_info = f"👤 Получатель: {blockchain_recipient}\n"
            except:
                pass
        
        # Очищаем состояние пользователя
        del self.user_states[user_id]
        
        keyboard = [
            [InlineKeyboardButton("✅ Подтвердить через TronLink", url=tronlink_url)],
            [InlineKeyboardButton("⬅️ Назад", callback_data='escrow_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        summary_text = (
            "✅ **Ссылка подтверждения готова!**\n\n"
            f"🔢 Transaction ID: `{tx_id}`\n"
            f"{amount_info}"
            f"{recipient_info}\n"
            "📋 **Дальше:**\n"
            "1. Нажмите 'Подтвердить через TronLink'\n"
            "2. Откроется браузер с интерфейсом\n"
            "3. Подтвердите транзакцию в TronLink\n\n"
            "⚠️ **ВНИМАНИЕ:** Подтверждайте только \n"
            "после получения товара/услуги!"
        )
        
        await update.message.reply_text(summary_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

    async def my_transactions_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр сделок пользователя"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        try:
            # Получаем подтвержденные сделки из БД
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_id,))
                confirmed_transactions = cur.fetchall()
            
            # Получаем ожидающие сделки
            pending_transactions = []
            for uuid, tx_data in self.pending_transactions.items():
                if tx_data.get('user_id') == user_id:
                    pending_transactions.append({
                        'uuid': uuid,
                        'status': tx_data.get('status', 'unknown'),
                        'amount': tx_data.get('data', {}).get('amount', 0),
                        'recipient': tx_data.get('data', {}).get('recipient', 'N/A'),
                        'created_at': tx_data.get('created_at', 0)
                    })
            
            # Сортируем по времени создания
            pending_transactions.sort(key=lambda x: x['created_at'], reverse=True)
            
            if not confirmed_transactions and not pending_transactions:
                text = "📋 У вас пока нет сделок."
            else:
                text = "📋 Ваши сделки:\n\n"
                
                # Показываем ожидающие сделки
                if pending_transactions:
                    text += "⏳ Ожидают подписания:\n"
                    for pending in pending_transactions[:3]:  # Показываем последние 3
                        created_date = datetime.fromtimestamp(pending['created_at']).strftime("%Y-%m-%d %H:%M")
                        status_emoji = "🔄" if pending['status'] == 'pending_signature' else "🔧"
                        text += (
                            f"{status_emoji} UUID: {pending['uuid']}\n"
                            f"💰 Сумма: {pending['amount']} USDT\n"
                            f"👤 Получатель: {pending['recipient']}\n"
                            f"📅 {created_date}\n\n"
                        )
                
                # Показываем подтвержденные сделки
                if confirmed_transactions:
                    text += "✅ Подтвержденные в блокчейне:\n"
                    for tx in confirmed_transactions[:5]:  # Показываем последние 5
                        tx_id, _, amount, recipient, status, role, created_at, uuid_field = tx
                        created_date = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M")
                        if uuid_field:
                            display_id = f"UUID: {uuid_field}"
                        else:
                            display_id = f"ID: {tx_id}"
                        text += (
                            f"✅ {display_id}\n"
                            f"💰 Сумма: {amount} USDT\n"
                            f"👤 Получатель: {recipient}\n"
                            f"📄 Статус: {status}\n"
                            f"📅 {created_date}\n\n"
                        )
                    
        except Exception as e:
            logger.error(f"Ошибка в my_transactions_handler: {e}")
            text = f"❌ Ошибка получения данных: {e}"
            
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='escrow_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup)

    async def confirm_escrow_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало подтверждения эскроу сделки"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        # Сохраняем состояние пользователя
        self.user_states[user_id] = {
            'state': 'waiting_transaction_id',
            'data': {}
        }
        
        keyboard = [[InlineKeyboardButton("⬅️ Отмена", callback_data='escrow_menu')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = (
            "✅ **Подтверждение эскроу сделки**\n\n"
            "📨 Введите ID сделки для подтверждения:\n\n"
            "🆔 **UUID сделки** (из сообщения бота):\n"
            "`f703898c-663c-4972-b03f-50c885d60e9e`\n\n"
            "🔢 **Или Blockchain ID** (число):\n"
            "`5`\n\n"
            "ℹ️ **Когда подтверждать:**\n"
            "• Когда вы получили товар/услугу\n"
            "• Когда уверены в качестве\n"
            "• После этого средства перейдут продавцу"
        )
        
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

    async def check_tx_status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка статуса транзакции с автосинхронизацией"""
        query = update.callback_query
        await query.answer()
        
        # Извлекаем UUID из callback_data
        tx_uuid = query.data.replace('check_tx_status_', '')
        user_id = str(update.effective_user.id)
        
        logger.info(f"Проверка статуса UUID: {tx_uuid}")
        
        # Проверяем, есть ли UUID уже в БД
        db_transaction = self.db_get_transaction_by_uuid(tx_uuid)
        
        if db_transaction:
            # UUID уже связан с blockchain ID
            blockchain_id = db_transaction[0]
            status = db_transaction[4]
            amount = db_transaction[2]
            recipient = db_transaction[3]
            
            text = (
                "✅ Сделка подтверждена в блокчейне!\n\n"
                f"🆔 UUID: {tx_uuid}\n"
                f"🔢 Blockchain ID: {blockchain_id}\n"
                f"💰 Сумма: {amount} USDT\n"
                f"📨 Получатель: {recipient}\n"
                f"📊 Статус: {status}\n\n"
                "🎉 Сделка готова к подтверждению!"
            )
            
        elif tx_uuid in self.pending_transactions:
            # UUID в pending - проверяем блокчейн
            pending_data = self.pending_transactions[tx_uuid]
            amount = pending_data.get('data', {}).get('amount', 0)
            recipient = pending_data.get('data', {}).get('recipient', '')
            
            try:
                # Создаем клиент для проверки блокчейна
                temp_client = TronEscrowUSDTClient(
                    private_key="0000000000000000000000000000000000000000000000000000000000000001",
                    contract_address=self.config.ESCROW_CONTRACT,
                    network=self.config.NETWORK
                )
                
                # Получаем общее количество транзакций
                total_transactions = temp_client.get_transaction_count()
                
                # Ищем среди последних 10 транзакций
                found_blockchain_id = None
                
                for blockchain_id in range(total_transactions - 1, max(-1, total_transactions - 10), -1):
                    try:
                        tx_info = temp_client.get_transaction(blockchain_id)
                        if not tx_info:
                            continue
                            
                        blockchain_recipient = tx_info.get('recipient', '')
                        tx_state = tx_info.get('state', '')
                        
                        # Проверяем совпадение по получателю и статусу AWAITING_DELIVERY
                        if (blockchain_recipient.lower() == recipient.lower() and 
                            tx_state == 'AWAITING_DELIVERY'):
                            found_blockchain_id = blockchain_id
                            break
                            
                    except Exception as e:
                        logger.warning(f"Ошибка при проверке транзакции {blockchain_id}: {e}")
                        continue
                
                if found_blockchain_id is not None:
                    # Найдена в блокчейне - сохраняем в БД
                    created_at = pending_data.get('created_at', int(time.time()))
                    self.db_add_transaction(
                        user_id=user_id,
                        tx_id=found_blockchain_id,
                        amount_usdt=amount,
                        recipient=recipient,
                        role='creator',
                        status='AWAITING_DELIVERY',
                        created_at=created_at,
                        uuid=tx_uuid
                    )
                    
                    # Удаляем из pending
                    del self.pending_transactions[tx_uuid]
                    self.save_pending_transactions()
                    
                    logger.info(f"✅ Автосинхронизация: UUID {tx_uuid} -> Blockchain ID {found_blockchain_id}")
                    
                    text = (
                        "✅ Сделка найдена в блокчейне!\n\n"
                        f"🆔 UUID: {tx_uuid}\n"
                        f"🔢 Blockchain ID: {found_blockchain_id}\n"
                        f"💰 Сумма: {amount} USDT\n"
                        f"📨 Получатель: {recipient}\n"
                        f"📊 Статус: AWAITING_DELIVERY\n\n"
                        "🎉 Автоматически синхронизировано!\n"
                        "✅ Сделка готова к подтверждению!"
                    )
                else:
                    # Не найдена в блокчейне
                    text = (
                        "⏳ Сделка еще не подписана\n\n"
                        f"🆔 UUID: {tx_uuid}\n"
                        f"💰 Сумма: {amount} USDT\n"
                        f"📨 Получатель: {recipient}\n"
                        f"📊 Статус: pending_signature\n\n"
                        "❗ Подпишите транзакцию через TronLink,\n"
                        "а затем нажмите Проверить статус снова."
                    )
                    
            except Exception as e:
                logger.error(f"Ошибка проверки блокчейна: {e}")
                text = (
                    f"❌ Ошибка проверки блокчейна\n\n"
                    f"🆔 UUID: {tx_uuid}\n"
                    f"⚠️ Ошибка: {str(e)}\n\n"
                    "🔄 Попробуйте позже."
                )
        else:
            # UUID нигде не найден
            text = (
                f"❌ UUID не найден\n\n"
                f"🆔 UUID: {tx_uuid}\n\n"
                "⚠️ Данный UUID не найден ни в базе данных,\n"
                "ни в ожидающих транзакциях."
            )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Проверить снова", callback_data=f'check_tx_status_{tx_uuid}')],
            [InlineKeyboardButton("⬅️ Назад к эскроу", callback_data='escrow_menu')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup)

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
            
        # Главные меню (обработка перенесена в эскроу секцию)
        elif data == 'crypto_menu':
            await self.crypto_menu(update, context)
            
        # Эскроу функции
        elif data == 'create_escrow':
            await self.create_escrow_handler(update, context)
        elif data == 'confirm_escrow':
            await self.confirm_escrow_handler(update, context)
        elif data == 'my_transactions':
            await self.my_transactions_handler(update, context)
        elif data == 'escrow_menu':
            # Очищаем состояние пользователя при возврате к меню
            user_id = str(update.effective_user.id)
            if user_id in self.user_states:
                del self.user_states[user_id]
            await self.escrow_menu(update, context)
            
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
        
        # Проверка статуса транзакции с автосинхронизацией
        elif data.startswith('check_tx_status_'):
            await self.check_tx_status_handler(update, context)
        
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
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_input))
        
        # Запускаем бота
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")
        raise

if __name__ == "__main__":
    main()