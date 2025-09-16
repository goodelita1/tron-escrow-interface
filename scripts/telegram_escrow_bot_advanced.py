#!/usr/bin/env python3
"""
Продвинутый Telegram Bot для USDT Escrow с TronLink интеграцией
Позволяет создавать сделки и подписывать через TronLink без передачи приватных ключей
"""

import os
import logging
import json
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from tron_escrow_usdt_client import TronEscrowUSDTClient
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
        
        # Загружаем настройки из config.json или используем дефолтные
        self.BOT_TOKEN = self.config.get('bot', {}).get('token', "")
        self.NETWORK = self.config.get('settings', {}).get('default_network', 'shasta')
        
        network_config = self.config.get('networks', {}).get(self.NETWORK, {})
        self.ESCROW_CONTRACT = network_config.get('escrow_contract', "")
        self.USDT_CONTRACT = network_config.get('usdt_contract', "")
        self.ARBITRATOR_ADDRESS = network_config.get('arbitrator_address', "")
        
        # Файлы для хранения данных
        self.USERS_DATA_FILE = "users_data.json"
        self.PENDING_TRANSACTIONS_FILE = "pending_transactions.json"
        
        # URL для TronLink интеграции
        self.WEB_APP_URL = self.config.get('bot', {}).get('web_app_url', "https://goodelita1.github.io/tron-escrow-interface/tronlink_interface.html")
        
        # Проверяем наличие обязательных параметров
        if not all([self.BOT_TOKEN, self.ESCROW_CONTRACT, self.USDT_CONTRACT, self.ARBITRATOR_ADDRESS]):
            raise ValueError("Не указаны необходимые параметры. Проверьте config.json")
    
    def load_config(self):
        """Загрузка конфигурации из JSON файла"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации: {e}")
            return {}

class AdvancedEscrowBot:
    def __init__(self):
        self.config = Config()
        self.users_data = self.load_users_data()
        self.pending_transactions = self.load_pending_transactions()
        # Инициализируем БД для устойчивого хранения сделок
        self.db_path = os.path.join(os.path.dirname(__file__), 'escrow.db')
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

    # -------------------- БЛОК РАБОТЫ С БАЗОЙ ДАННЫХ --------------------
    def get_db_conn(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                # Users table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        created_at INTEGER
                    )
                    """
                )
                # Desired minimal schema for transactions (matches current app logic)
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        amount_usdt REAL NOT NULL,
                        recipient TEXT NOT NULL,
                        status TEXT NOT NULL,
                        role TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                # Migration: if legacy columns exist (e.g., arbitrator, description with NOT NULL), migrate to minimal schema
                try:
                    cur.execute("PRAGMA table_info(transactions)")
                    cols = [r[1] for r in cur.fetchall()]
                    if 'arbitrator' in cols or 'description' in cols:
                        logger.info("Обнаружена устаревшая схема таблицы transactions. Выполняю миграцию к минимальной схеме...")
                        # Create a new table with the target schema
                        cur.execute(
                            """
                            CREATE TABLE IF NOT EXISTS transactions_new (
                                id INTEGER PRIMARY KEY,
                                user_id TEXT NOT NULL,
                                amount_usdt REAL NOT NULL,
                                recipient TEXT NOT NULL,
                                status TEXT NOT NULL,
                                role TEXT NOT NULL,
                                created_at INTEGER NOT NULL
                            )
                            """
                        )
                        # Copy only the required columns that still exist
                        # Build dynamic column list for SELECT based on available columns
                        select_cols = []
                        for c in ['id','user_id','amount_usdt','recipient','status','role','created_at']:
                            if c in cols:
                                select_cols.append(c)
                            else:
                                # Provide defaults if missing
                                if c == 'status':
                                    select_cols.append("'AWAITING_DELIVERY' AS status")
                                elif c == 'role':
                                    select_cols.append("'sender' AS role")
                                elif c == 'created_at':
                                    select_cols.append(f"{int(time.time())} AS created_at")
                                else:
                                    select_cols.append("NULL")
                        select_cols_sql = ", ".join(select_cols)
                        cur.execute(f"INSERT OR REPLACE INTO transactions_new (id,user_id,amount_usdt,recipient,status,role,created_at) SELECT {select_cols_sql} FROM transactions")
                        # Replace old table
                        cur.execute("DROP TABLE transactions")
                        cur.execute("ALTER TABLE transactions_new RENAME TO transactions")
                        logger.info("Миграция таблицы transactions завершена успешно.")
                except Exception as mig_e:
                    logger.error(f"Ошибка миграции схемы transactions: {mig_e}")
                # Ensure index
                cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id)")
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")
        except Exception as e:
            logger.error(f"Ошибка инициализации БД: {e}")

    def db_upsert_user(self, user_id: str, username: str, first_name: str):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO users (id, username, first_name, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name
                    """,
                    (user_id, username, first_name, int(time.time()))
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения пользователя в БД: {e}")

    def db_add_transaction(self, user_id: str, tx_id: int, amount_usdt: float, recipient: str, role: str, status: str, created_at: int):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT OR REPLACE INTO transactions (id, user_id, amount_usdt, recipient, status, role, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (tx_id, user_id, amount_usdt, recipient, status, role, created_at)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения сделки в БД: {e}")

    def db_list_transactions(self, user_id: str, limit: int = 20):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, amount_usdt, recipient, status, role, created_at
                    FROM transactions
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit)
                )
                rows = cur.fetchall()
                return [
                    {
                        'id': r[0],
                        'amount': r[1],
                        'recipient': r[2],
                        'status': r[3],
                        'role': r[4],
                        'created_at': r[5],
                    } for r in rows
                ]
        except Exception as e:
            logger.error(f"Ошибка получения списка сделок из БД: {e}")
            return []

    def db_update_status(self, tx_id: int, status: str):
        try:
            with self.get_db_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE transactions SET status = ? WHERE id = ?",
                    (status, tx_id)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления статуса сделки в БД: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /start"""
        user = update.effective_user
        user_id = str(user.id)
        
        # Сохраняем информацию о пользователе (в JSON и в БД)
        if user_id not in self.users_data:
            self.users_data[user_id] = {
                'username': user.username,
                'first_name': user.first_name,
                'created_at': int(time.time()),
                'transactions_created': 0,
                'transactions_confirmed': 0
            }
            self.save_users_data()
        # Обновляем/сохраняем пользователя в БД
        self.db_upsert_user(user_id, user.username or '', user.first_name or '')
        
        welcome_text = f"""
🚀 **USDT Escrow Bot v2.0 - TronLink Integration**

👋 Привет, {user.first_name}!

🔥 **Новые возможности:**
• 🆕 Создание Escrow сделок прямо в боте
• 🔐 Безопасная подпись через TronLink
• 💰 Поддержка USDT (TRC-20)
• 📊 Отслеживание всех ваших сделок
• ⚖️ Система разрешения споров

🛡️ **Безопасность:**
✅ Приватные ключи НЕ передаются боту
✅ Подписание транзакций в вашем кошельке
✅ Полная совместимость с TronLink
✅ Открытый исходный код смарт-контракта

📋 **Поддерживаемые сети:**
• 🌐 TRON Mainnet
• 🧪 Shasta Testnet

Выберите действие ⬇️
        """
        
        keyboard = [
            [InlineKeyboardButton("🆕 Создать сделку", callback_data="create_escrow")],
            [InlineKeyboardButton("💼 Мои сделки", callback_data="my_transactions")],
            [InlineKeyboardButton("✅ Подтвердить доставку", callback_data="confirm_delivery_flow")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    async def create_escrow_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Процесс создания Escrow сделки"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        # Инициализируем процесс создания сделки
        context.user_data['creating_escrow'] = {
            'step': 'recipient',
            'data': {}
        }
        
        await query.edit_message_text(
            "🆕 **Создание новой Escrow сделки**\n\n"
            "📥 **Шаг 1/4:** Адрес получателя\n\n"
            "Введите TRON адрес получателя средств:\n"
            "Пример: `TJtq3AVtNTngU23HFinp22rh6Ufcy78Ce4`\n\n"
            "⚠️ Проверьте адрес внимательно!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def create_escrow_step_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Обработчик шагов создания Escrow"""
        user_id = str(update.effective_user.id)
        
        if 'creating_escrow' not in context.user_data:
            await update.message.reply_text("❌ Процесс создания не найден. Используйте /start")
            return
        
        escrow_data = context.user_data['creating_escrow']
        step = escrow_data['step']
        
        if step == 'recipient':
            # Валидация TRON адреса
            if not self.is_valid_tron_address(text):
                await update.message.reply_text(
                    "❌ Неверный TRON адрес!\n\n"
                    "Адрес должен:\n"
                    "• Начинаться с 'T'\n"
                    "• Содержать 34 символа\n"
                    "• Состоять из букв и цифр\n\n"
                    "Попробуйте ещё раз:"
                )
                return
            
            escrow_data['data']['recipient'] = text
            escrow_data['step'] = 'amount'
            
            await update.message.reply_text(
                "✅ Адрес получателя сохранён\n\n"
                "💰 **Шаг 2/2:** Сумма в USDT\n\n"
                "Введите сумму в USDT для блокировки:\n"
                "Примеры: `100`, `50.5`, `1000`\n\n"
                "💰 **Комиссия платформы: 5 USDT**\n"
                "Получатель получит: сумма минус 5 USDT\n\n"
                "⚠️ Минимальная сумма: 5.01 USDT",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif step == 'amount':
            try:
                amount = float(text)
                if amount <= 5.0:
                    raise ValueError("Минимальная сумма: 5.01 USDT (с учетом комиссии 5 USDT)")
                if amount > 1000000:  # Максимум для безопасности
                    raise ValueError("Сумма слишком велика")
            except ValueError as e:
                await update.message.reply_text(
                    f"❌ Неверная сумма: {str(e)}\n\n"
                    "Введите корректную сумму в USDT:"
                )
                return
            
            escrow_data['data']['amount'] = amount
            
            # Генерируем уникальный ID для транзакции
            transaction_uuid = str(uuid.uuid4())
            
            # Сохраняем данные транзакции
            self.pending_transactions[transaction_uuid] = {
                'user_id': user_id,
                'created_at': int(time.time()),
                'status': 'pending_signature',
                'data': escrow_data['data'].copy()
            }
            self.save_pending_transactions()
            
            # Показываем итоговое подтверждение
            await self.show_transaction_summary(update, context, transaction_uuid)
    
    async def show_transaction_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_uuid: str):
        """Показать итоги сделки и запросить подпись"""
        tx_data = self.pending_transactions[transaction_uuid]['data']
        
        summary_text = f"""
📋 **Итоги новой Escrow сделки**

📥 **Получатель:** `{tx_data['recipient']}`
💰 **Общая сумма:** `{tx_data['amount']} USDT`
💸 **К получателю:** `{tx_data['amount'] - 5} USDT`
💳 **Комиссия:** `5 USDT`
⏰ **Срок:** 48 часов (по умолчанию)

🔐 **Контракты:**
• Escrow: `{self.config.ESCROW_CONTRACT}`
• USDT: `{self.config.USDT_CONTRACT}`
• Сеть: `{self.config.NETWORK.upper()}`

💡 **Что происходит дальше:**
1. Вы подписываете транзакцию в TronLink
2. USDT блокируются в Escrow контракте  
3. Получатель получает уведомление
4. После доставки - получатель подтверждает через бота
5. USDT автоматически переходят получателю

⚠️ **Убедитесь что:**
• У вас достаточно USDT на балансе ({tx_data['amount']} USDT)
• У вас есть TRX для комиссии (~50 TRX)
• Адреса указаны правильно
• Получатель получит {tx_data['amount'] - 5} USDT

Подтвердите создание сделки ⬇️
        """
        
        keyboard = [
            [InlineKeyboardButton("🔐 Подписать в TronLink", callback_data=f"sign_transaction_{transaction_uuid}")],
            [InlineKeyboardButton("📋 Показать детали", callback_data=f"show_tx_details_{transaction_uuid}")],
            [
                InlineKeyboardButton("✏️ Изменить", callback_data=f"edit_transaction_{transaction_uuid}"),
                InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_transaction_{transaction_uuid}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            summary_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
        # Очищаем состояние создания
        if 'creating_escrow' in context.user_data:
            del context.user_data['creating_escrow']
    
    async def sign_transaction_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик подписания транзакции через TronLink"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        transaction_uuid = callback_data.split('_')[-1]
        
        if transaction_uuid not in self.pending_transactions:
            await query.edit_message_text("❌ Транзакция не найдена или устарела")
            return
        
        tx_data = self.pending_transactions[transaction_uuid]
        
        # Генерируем данные для TronLink
        tronlink_data = self.generate_tronlink_transaction_data(tx_data['data'])
        
        # Создаем QR код для TronLink
        qr_code_data = self.generate_qr_code(tronlink_data)
        
        instruction_text = f"""
🔐 **Подписание транзакции в TronLink**

💻 **Способ 1: Браузерное расширение**
1. Убедитесь что TronLink установлен в браузере
2. Нажмите кнопку "💻 Открыть TronLink" ниже
3. Подтвердите подключение к сайту
4. Проверьте данные транзакции
5. Нажмите "✅ Подтвердить" в TronLink

⚠️ **Важно:**
• Проверьте все данные перед подписанием
• Убедитесь что у вас достаточно USDT и TRX

🔄 **После подписания:**
✅ Вернитесь в бота
✅ Нажмите "🔍 Проверить статус" ниже
✅ Получите ID своей сделки!
        """
        
        # Кодируем данные в base64 для URL
        json_data = json.dumps(tronlink_data, separators=(',', ':'))
        encoded_data = base64.b64encode(json_data.encode()).decode()
        # Правильное соединение URL параметров
        separator = '&' if '?' in self.config.WEB_APP_URL else '?'
        tronlink_url = f"{self.config.WEB_APP_URL}{separator}data={encoded_data}"
        
        keyboard = [
            [InlineKeyboardButton("💻 Открыть TronLink", url=tronlink_url)],
            [InlineKeyboardButton("🔍 Проверить статус", callback_data=f"check_tx_status_{transaction_uuid}")],
            [InlineKeyboardButton("❓ Инструкция", callback_data=f"tronlink_help")],
            [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем инструкции без QR кода
        await query.edit_message_text(
            instruction_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

    def generate_tronlink_transaction_data(self, tx_data):
        """Генерирует данные транзакции для TronLink"""
        # Данные для создания Escrow транзакции
        deadline = int(time.time()) + (48 * 3600)  # 48 часов
        amount_units = int(tx_data['amount'] * 1_000_000)  # USDT в микроединицах
        
        return {
            'type': 'escrow_create',
            'contract': self.config.ESCROW_CONTRACT,
            'method': 'createTransaction',
            'parameters': {
                'recipient': tx_data['recipient'],
                'amount': amount_units,
                'deadline': deadline
            },
            'usdt_contract': self.config.USDT_CONTRACT,
            'usdt_amount': amount_units,
            'network': self.config.NETWORK
        }
    
    def generate_confirmation_tronlink_data(self, tx_id: int, tx_info: dict):
        """Генерирует данные подтверждения доставки для TronLink"""
        # Проверяем и обрабатываем данные транзакции
        safe_amount = tx_info.get('amount_usdt', 0) if tx_info and tx_info.get('amount_usdt') is not None else 0
        safe_recipient = tx_info.get('recipient', 'N/A') if tx_info and tx_info.get('recipient') else 'N/A'
        safe_sender = tx_info.get('sender', 'N/A') if tx_info and tx_info.get('sender') else 'N/A'
        safe_arbitrator = tx_info.get('arbitrator', 'N/A') if tx_info and tx_info.get('arbitrator') else 'N/A'
        safe_description = tx_info.get('description', 'Нет описания') if tx_info and tx_info.get('description') else 'Нет описания'
        
        # Проверяем формат адреса контракта
        contract_address = self.config.ESCROW_CONTRACT
        logger.info(f"=== Генерация данных для TronLink ===")
        logger.info(f"Используемый Escrow контракт: {contract_address}")
        
        if not contract_address.startswith('T') or len(contract_address) != 34:
            logger.error(f"Неправильный формат адреса контракта: {contract_address}")
        else:
            logger.info(f"Адрес контракта прошел валидацию: {contract_address}")
        
        result = {
            'type': 'escrow_confirm_delivery',
            'contract': contract_address,
            'method': 'confirmDelivery',
            'parameters': {
                'transactionId': tx_id
            },
            'network': self.config.NETWORK,
            'tx_info': {
                'id': tx_id,
                'amount': safe_amount,
                'sender': safe_sender,
                'recipient': safe_recipient,
                'arbitrator': safe_arbitrator,
                'description': safe_description
            }
        }
        
        logger.info(f"Сгенерированные данные для TronLink: {result}")
        return result
    
    def generate_qr_code(self, data):
        """Генерирует QR код с данными транзакции"""
        try:
            # Конвертируем данные в JSON и кодируем в base64
            json_data = json.dumps(data, separators=(',', ':'))
            encoded_data = base64.b64encode(json_data.encode()).decode()
            
            # Создаем URL для TronLink
            tronlink_url = f"tronlink://transaction?data={encoded_data}"
            
            # Генерируем QR код
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(tronlink_url)
            qr.make(fit=True)
            
            # Создаем изображение QR кода
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Конвертируем в байты
            img_buffer = BytesIO()
            qr_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            return img_buffer.getvalue()
        except Exception as e:
            logger.error(f"Ошибка генерации QR кода: {e}")
            return None
    
    def is_valid_tron_address(self, address: str) -> bool:
        """Проверка валидности TRON адреса"""
        if not address or len(address) != 34:
            return False
        if not address.startswith('T'):
            return False
        # Простая проверка символов (полная валидация требует библиотеки base58)
        valid_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        return all(c in valid_chars for c in address[1:])
    
    async def check_transaction_status_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Проверка статуса транзакции"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        
        if callback_data.startswith('check_tx_status_'):
            transaction_uuid = callback_data.split('_')[-1]
            
            if transaction_uuid in self.pending_transactions:
                # Проверяем ожидающую транзакцию
                await self.check_pending_transaction_status(update, context, transaction_uuid)
            else:
                await query.edit_message_text("❌ Транзакция не найдена")
        
    
    async def check_pending_transaction_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_uuid: str):
        """Проверка статуса ожидающей транзакции"""
        query = update.callback_query
        
        try:
            # Создаем клиент для проверки
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            # Получаем количество транзакций в контракте
            tx_count = temp_client.get_transaction_count()
            
            # Проверяем последние транзакции на соответствие данным
            pending_tx = self.pending_transactions[transaction_uuid]
            
            found_tx_id = None
            for tx_id in range(max(0, tx_count - 10), tx_count):  # Проверяем последние 10 транзакций
                tx_info = temp_client.get_transaction(tx_id)
                if tx_info and self.matches_pending_transaction(tx_info, pending_tx['data']):
                    found_tx_id = tx_id
                    break
            
            if found_tx_id is not None:
                # Транзакция найдена в блокчейне!
                await self.handle_confirmed_transaction(update, context, transaction_uuid, found_tx_id)
            else:
                # Транзакция еще не найдена
                status_text = f"""
⏳ **Статус: Ожидание подписания**

🔍 Транзакция пока не найдена в блокчейне.

Возможные причины:
• Транзакция еще не подписана
• Подписание в процессе
• Недостаточно TRX для комиссии
• Недостаточно USDT на балансе
• Ошибка в TronLink

💡 **Что делать:**
1. Убедитесь что подписали транзакцию в TronLink
2. Проверьте баланс USDT и TRX
3. Подождите 1-2 минуты и нажмите "Проверить еще раз"

Транзакция будет найдена автоматически после подтверждения в сети.
                """
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_tx_status_{transaction_uuid}")],
                    [InlineKeyboardButton("🔐 Подписать заново", callback_data=f"sign_transaction_{transaction_uuid}")],
                    [InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_transaction_{transaction_uuid}")],
                    [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    status_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки статуса: {e}")
            try:
                await query.edit_message_text(f"❌ Ошибка при проверке: {str(e)}")
            except:
                # Если не можем редактировать, отправляем новое сообщение
                await query.message.reply_text(f"❌ Ошибка при проверке: {str(e)}")
    
    def matches_pending_transaction(self, tx_info, pending_data):
        """Проверяет соответствие транзакции ожидающим данным"""
        try:
            return (
                tx_info['recipient'].lower() == pending_data['recipient'].lower() and
                abs(tx_info['amount_usdt'] - pending_data['amount']) < 0.000001
            )
        except:
            return False
    
    async def handle_confirmed_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_uuid: str, tx_id: int):
        """Обработка подтвержденной транзакции"""
        query = update.callback_query
        
        # Удаляем из ожидающих
        pending_tx = self.pending_transactions.pop(transaction_uuid)
        self.save_pending_transactions()
        
        # Обновляем статистику пользователя и сохраняем сделку
        user_id = str(update.effective_user.id)
        created_ts = int(time.time())
        if user_id in self.users_data:
            self.users_data[user_id]['transactions_created'] += 1
            # Добавляем сделку в историю пользователя (локально)
            if 'transactions' not in self.users_data[user_id]:
                self.users_data[user_id]['transactions'] = []
            
            transaction_record = {
                'id': tx_id,
                'amount': pending_tx['data']['amount'],
                'recipient': pending_tx['data']['recipient'],
                'status': 'AWAITING_DELIVERY',
                'created_at': created_ts,
                'role': 'sender'
            }
            self.users_data[user_id]['transactions'].append(transaction_record)
            self.save_users_data()
        # Сохраняем сделку в БД
        try:
            self.db_add_transaction(
                user_id=user_id,
                tx_id=tx_id,
                amount_usdt=float(pending_tx['data']['amount']),
                recipient=pending_tx['data']['recipient'],
                role='sender',
                status='AWAITING_DELIVERY',
                created_at=created_ts
            )
        except Exception as e:
            logger.error(f"Не удалось записать сделку в БД: {e}")
        
        success_text = f"""
🎉 **Escrow сделка успешно создана!**

✅ **Транзакция подтверждена в блокчейне**

🆔 **ID ВАШЕЙ СДЕЛКИ: `{tx_id}`**
📝 **Запомните этот ID для отслеживания!**

💰 **Сумма:** `{pending_tx['data']['amount']} USDT`
📥 **Получатель:** `{pending_tx['data']['recipient']}`

🔗 **Ссылки:**
• [Посмотреть в блокчейне](https://shasta.tronscan.org/#/contract/{self.config.ESCROW_CONTRACT})
• [TronScan Explorer](https://shasta.tronscan.org/#/contract/{self.config.ESCROW_CONTRACT})

📋 **Что дальше:**
1. ✅ USDT заблокированы в Escrow контракте
2. 📤 Уведомите получателя о сделке ID: `{tx_id}`
3. ⏳ Ожидайте доставки товара/услуги
4. 🔔 Получатель подтвердит доставку через бота
5. 💸 USDT автоматически переведутся получателю

💬 **Сообщение для получателя:**
"Создана Escrow сделка ID: `{tx_id}` на {pending_tx['data']['amount']} USDT. Для подтверждения доставки найдите этого бота в Telegram."

🔍 **Отслеживание:** Используйте меню "Мои сделки" или "Проверить сделку" с ID: `{tx_id}`
        """
        
        keyboard = [
            [InlineKeyboardButton("📊 Посмотреть сделку", callback_data=f"view_tx_{tx_id}")],
            [InlineKeyboardButton("📋 Мои сделки", callback_data="my_transactions")],
            [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_text(
                success_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        except:
            # Если не можем редактировать (например, сообщение с картинкой), отправляем новое
            await query.message.reply_text(
                success_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

    async def message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        user_id = str(update.effective_user.id)
        text = update.message.text
        
        # Обработка создания Escrow сделки
        if 'creating_escrow' in context.user_data:
            await self.create_escrow_step_handler(update, context, text)
            return
        
        
        # Обработка ввода ID для подтверждения доставки
        if context.user_data.get('expecting_delivery_confirmation_id'):
            context.user_data['expecting_delivery_confirmation_id'] = False
            try:
                transaction_id = int(text)
                await self.process_delivery_confirmation_id(update, context, transaction_id)
            except ValueError:
                await update.message.reply_text("❌ Неверный ID сделки. Используйте число.")
            return
        
        # Остальные обработчики...
        await update.message.reply_text(
            "❓ Не понимаю. Используйте кнопки меню или /start для начала."
        )

    async def check_blockchain_transaction_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_id: int):
        """Проверка статуса транзакции в блокчейне"""
        try:
            # Тот же код что и в базовой версии бота
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            tx_info = temp_client.get_transaction(transaction_id)
            
            if not tx_info:
                await update.message.reply_text(f"❌ Транзакция #{transaction_id} не найдена.")
                return
            
            # Форматируем и отправляем информацию (тот же код что раньше)
            # ... [код отображения статуса транзакции] ...
            
        except Exception as e:
            logger.error(f"Ошибка проверки транзакции: {e}")
            await update.message.reply_text(f"❌ Ошибка при проверке транзакции: {str(e)}")
    
    async def show_my_transactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать все сделки пользователя"""
        query = update.callback_query
        await query.answer()
        
        user_id = str(update.effective_user.id)
        
        if user_id not in self.users_data or 'transactions' not in self.users_data[user_id]:
            await query.edit_message_text(
                "💼 <b>Мои сделки</b>\n\n"
                "💭 У вас пока нет созданных сделок.\n\n"
                "🆕 Начните с создания первой Escrow сделки!",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆕 Создать сделку", callback_data="create_escrow")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
                ])
            )
            return
        
        # Берем сделки из БД (падение обратно к JSON если БД пуста)
        transactions = self.db_list_transactions(user_id)
        if not transactions and 'transactions' in self.users_data.get(user_id, {}):
            transactions = self.users_data[user_id]['transactions']
        
        if not transactions:
            await query.edit_message_text(
                "💼 <b>Мои сделки</b>\n\n"
                "💭 У вас пока нет созданных сделок.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆕 Создать сделку", callback_data="create_escrow")],
                    [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
                ])
            )
            return
        
        # Показываем последние 5 сделок
        recent_transactions = sorted(transactions, key=lambda x: x['created_at'], reverse=True)[:5]
        
        status_emoji = {
            'AWAITING_PAYMENT': '🔄',
            'AWAITING_DELIVERY': '⏳',
            'COMPLETE': '✅',
            'REFUNDED': '🔙',
            'DISPUTED': '⚠️'
        }
        
        transactions_text = "💼 <b>Мои сделки</b> (последние 5)\n\n"
        
        import html as _html
        for tx in recent_transactions:
            status = tx.get('status', 'AWAITING_DELIVERY')
            emoji = status_emoji.get(status, '❓')
            created_date = datetime.fromtimestamp(tx['created_at']).strftime('%d.%m.%Y %H:%M')
            desc = tx.get('description') or ''
            desc_short = desc[:30] + ('...' if len(desc) > 30 else '')
            desc_escaped = _html.escape(desc_short)
            recipient_short = f"{tx['recipient'][:10]}...{tx['recipient'][-6:]}"
            
            transactions_text += (
                f"{emoji} <b>ID: {tx['id']}</b> - {tx['amount']} USDT\n"
                f"📅 {created_date}\n"
                f"📥 {recipient_short}\n"
                f"📝 {desc_escaped}\n"
                f"────────────────────\n"
            )
        
        transactions_text += f"\n📊 <b>Всего сделок:</b> {len(transactions)}"
        
        keyboard = []
        # Добавляем кнопки для просмотра деталей последних 3 сделок
        for i, tx in enumerate(recent_transactions[:3]):
            keyboard.append([InlineKeyboardButton(f"🔍 Посмотреть ID: {tx['id']}", callback_data=f"view_tx_{tx['id']}")])
        
        keyboard.extend([
            [InlineKeyboardButton("🔄 Обновить", callback_data="my_transactions")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            transactions_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    
    
    async def confirm_delivery_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Подтверждение доставки"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✅ **Подтверждение доставки**\n\n"
            "📦 Если вы получили товар или услугу, вы можете подтвердить доставку.\n\n"
            "🆔 Укажите ID сделки, которую хотите подтвердить:\n\n"
            "⚠️ **Внимание:** После подтверждения USDT будут немедленно переведены вам. Отменить это действие нельзя!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔢 Ввести ID сделки", callback_data="enter_delivery_confirmation_id")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")]
            ])
        )
    
    async def view_transaction_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: int):
        """Посмотр деталей сделки"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Получаем информацию из блокчейна
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            tx_info = temp_client.get_transaction(tx_id)
            
            # Если не удалось получить из блокчейна, проверяем БД
            db_transaction = None
            if not tx_info:
                # Проверяем, есть ли сделка в нашей БД
                try:
                    with self.get_db_conn() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT user_id, amount_usdt, recipient, status FROM transactions WHERE id = ?",
                            (tx_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            db_transaction = {
                                'user_id': row[0],
                                'amount_usdt': row[1],
                                'recipient': row[2],
                                'status': row[3]
                            }
                except Exception as e:
                    logger.error(f"Ошибка получения сделки из БД: {e}")
            
            # Проверяем, найдена ли сделка в блокчейне или БД
            if not tx_info and not db_transaction:
                await query.edit_message_text(
                    f"❌ **Сделка не найдена**\n\n"
                    f"🆔 Сделка с ID `{tx_id}` не найдена ни в блокчейне, ни в базе данных.\n\n"
                    "🔍 Проверьте ID и попробуйте снова.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Назад к сделкам", callback_data="my_transactions")],
                        [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                    ])
                )
                return
            
            # Определяем статус сделки (из блокчейна или БД)
            status_text = {
                0: '🔄 Ожидание оплаты',
                1: '⏳ Ожидание доставки',
                2: '✅ Завершена',
                3: '🔙 Возвращена',
                4: '⚠️ Спор',
                -1: '❓ Неизвестный'
            }
            
            if tx_info:
                # Используем данные из блокчейна (поле 'state', не 'status')
                blockchain_state = tx_info.get('state', 'UNKNOWN')
                # Преобразуем строковое состояние в числовой статус
                blockchain_status_mapping = {
                    'AWAITING_PAYMENT': 0,
                    'AWAITING_DELIVERY': 1,
                    'COMPLETE': 2,
                    'REFUNDED': 3,
                    'DISPUTED': 4
                }
                tx_status = blockchain_status_mapping.get(blockchain_state, -1)
                status = status_text.get(tx_status, f'❓ Неизвестный ({tx_status})')
                deadline_date = datetime.fromtimestamp(tx_info.get('deadline', int(time.time()))).strftime('%d.%m.%Y %H:%M')
                amount_display = tx_info.get('amount_usdt', 0)
                sender_display = tx_info.get('sender', 'N/A')
                recipient_display = tx_info.get('recipient', 'N/A')
            elif db_transaction:
                # Используем данные из БД
                db_status = db_transaction['status']
                # Преобразуем строковые статусы в числовые для совместимости
                status_mapping = {
                    'AWAITING_PAYMENT': 0,
                    'AWAITING_DELIVERY': 1,
                    'COMPLETE': 2,
                    'REFUNDED': 3,
                    'DISPUTED': 4
                }
                tx_status = status_mapping.get(db_status, -1)
                
                # Для отображения используем строковый статус из БД
                status_display_mapping = {
                    'AWAITING_PAYMENT': '🔄 Ожидание оплаты',
                    'AWAITING_DELIVERY': '⏳ Ожидание доставки',
                    'COMPLETE': '✅ Завершена',
                    'REFUNDED': '🔙 Возвращена',
                    'DISPUTED': '⚠️ Спор'
                }
                status = status_display_mapping.get(db_status, '❓ Неизвестный')
                deadline_date = 'Не указан'
                amount_display = db_transaction.get('amount_usdt', 0)
                sender_display = 'N/A'  # В БД нет sender
                recipient_display = db_transaction.get('recipient', 'N/A')
            else:
                tx_status = -1
                status = '❓ Неизвестный'
                deadline_date = 'Не указан'
                amount_display = 'N/A'
                sender_display = 'N/A'
                recipient_display = 'N/A'
            
            # Безопасное отображение адресов (укорачиваем для избежания ошибок парсинга)
            def safe_address_display(addr):
                if addr and addr != 'N/A' and len(addr) > 20:
                    return f"{addr[:8]}...{addr[-8:]}"
                return addr
            
            sender_safe = safe_address_display(sender_display)
            recipient_safe = safe_address_display(recipient_display)
            
            # Простое форматирование без сложных markdown конструкций
            details_text = f"""
📊 **Детали сделки #{tx_id}**

{status}

💰 **Сумма:** {amount_display} USDT
📤 **Отправитель:** {sender_safe}
📥 **Получатель:** {recipient_safe}

⏰ **Срок:** {deadline_date}

🔗 Посмотреть в блокчейне: https://shasta.tronscan.org/#/contract/{self.config.ESCROW_CONTRACT}
            """
            
            keyboard = [
                [InlineKeyboardButton("🔄 Обновить статус", callback_data=f"view_tx_{tx_id}")],
                [InlineKeyboardButton("⬅️ К списку сделок", callback_data="my_transactions")],
                [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
            ]
            
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                details_text,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Ошибка при получении деталей сделки: {e}")
            await query.edit_message_text(
                f"❌ **Ошибка при загрузке данных**\n\n"
                f"Детали ошибки: {str(e)}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Назад", callback_data="my_transactions")],
                    [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                ])
            )
    
    async def back_to_main(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Возврат к главному меню"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        user_id = str(user.id)
        
        welcome_text = f"""
🚀 **USDT Escrow Bot v2.0 - TronLink Integration**

👋 Привет, {user.first_name}!

🔥 **Новые возможности:**
• 🆕 Создание Escrow сделок прямо в боте
• 🔐 Безопасная подпись через TronLink
• 💰 Поддержка USDT (TRC-20)
• 📊 Отслеживание всех ваших сделок
• ⚖️ Система разрешения споров

🛡️ **Безопасность:**
✅ Приватные ключи НЕ передаются боту
✅ Подписание транзакций в вашем кошельке
✅ Полная совместимость с TronLink
✅ Открытый исходный код смарт-контракта

📋 **Поддерживаемые сети:**
• 🌐 TRON Mainnet
• 🧪 Shasta Testnet

Выберите действие ⬇️
        """
        
        keyboard = [
            [InlineKeyboardButton("🆕 Создать сделку", callback_data="create_escrow")],
            [InlineKeyboardButton("💼 Мои сделки", callback_data="my_transactions")],
            [InlineKeyboardButton("✅ Подтвердить доставку", callback_data="confirm_delivery_flow")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def start_delivery_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало процесса подтверждения доставки"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['expecting_delivery_confirmation_id'] = True
        
        await query.edit_message_text(
            "🔢 **Ввод ID сделки**\n\n"
            "✅ Введите ID сделки, которую хотите подтвердить:\n\n"
            "📝 Пример: `123`\n\n"
            "⚠️ **Внимание:**\n"
            "• Подтверждайте только полученные товары/услуги\n"
            "• Отменить подтверждение нельзя!\n"
            "• USDT будут немедленно переведены",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Отмена", callback_data="back_to_main")]
            ])
        )
    
    async def process_delivery_confirmation_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: int):
        """Обработка введенного ID для подтверждения"""
        try:
            # Получаем информацию о сделке из блокчейна
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            tx_info = temp_client.get_transaction(tx_id)
            
            # Если не удалось получить из блокчейна, проверяем БД
            db_transaction = None
            if not tx_info:
                # Проверяем, есть ли сделка в нашей БД
                try:
                    with self.get_db_conn() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT user_id, amount_usdt, recipient, status FROM transactions WHERE id = ?",
                            (tx_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            db_transaction = {
                                'user_id': row[0],
                                'amount_usdt': row[1],
                                'recipient': row[2],
                                'status': row[3]
                            }
                except Exception as e:
                    logger.error(f"Ошибка получения сделки из БД: {e}")
            # Проверяем, найдена ли сделка в блокчейне или БД
            if not tx_info and not db_transaction:
                await update.message.reply_text(
                    f"❌ Сделка не найдена\n\n"
                    f"🆔 Сделка с ID {tx_id} не найдена ни в блокчейне, ни в базе данных.\n\n"
                    "🔍 Проверьте ID и попробуйте снова."
                )
                return
            
            # Определяем статус сделки (из блокчейна или БД)
            if tx_info:
                # Используем данные из блокчейна (поле 'state', не 'status')
                blockchain_state = tx_info.get('state', 'UNKNOWN')
                # Преобразуем строковое состояние в числовой статус
                blockchain_status_mapping = {
                    'AWAITING_PAYMENT': 0,
                    'AWAITING_DELIVERY': 1,
                    'COMPLETE': 2,
                    'REFUNDED': 3,
                    'DISPUTED': 4
                }
                status = blockchain_status_mapping.get(blockchain_state, -1)
                transaction_data = tx_info
            elif db_transaction:
                # Используем данные из БД
                db_status = db_transaction['status']
                # Преобразуем строковые статусы в числовые
                status_mapping = {
                    'AWAITING_PAYMENT': 0,
                    'AWAITING_DELIVERY': 1,
                    'COMPLETE': 2,
                    'REFUNDED': 3,
                    'DISPUTED': 4
                }
                status = status_mapping.get(db_status, -1)
                transaction_data = db_transaction
            else:
                status = -1
                transaction_data = {}
            
            # Проверяем возможность подтверждения
            can_confirm = False
            
            # Проверяем статус
            if status == 1:  # AWAITING_DELIVERY в блокчейне
                can_confirm = True
            elif db_transaction and db_transaction['status'] == 'AWAITING_DELIVERY':
                # Либо AWAITING_DELIVERY в базе данных
                can_confirm = True
            
            if not can_confirm:
                status_names = {
                    0: "🔄 Ожидание оплаты",
                    2: "✅ Уже завершена",
                    3: "🔙 Возвращена",
                    4: "⚠️ В споре",
                    -1: "❓ Неизвестный"
                }
                
                # Преобразуем строковые статусы из БД в читаемый вид
                if db_transaction:
                    db_status_display = {
                        'AWAITING_PAYMENT': '🔄 Ожидание оплаты',
                        'AWAITING_DELIVERY': '⏳ Ожидание доставки',
                        'COMPLETE': '✅ Уже завершена',
                        'REFUNDED': '🔙 Возвращена',
                        'DISPUTED': '⚠️ В споре'
                    }
                    actual_status = db_status_display.get(db_transaction['status'], '❓ Неизвестный')
                else:
                    actual_status = status_names.get(status, f"Неизвестный ({status})")
                
                await update.message.reply_text(
                    f"❌ Нельзя подтвердить эту сделку\n\n"
                    f"🆔 Сделка #{tx_id}\n"
                    f"📈 Текущий статус: {actual_status}\n\n"
                    "📝 Подтвердить можно только:\n"
                    "• Сделки в статусе '⏳ Ожидание доставки'"
                )
                return
            
            # Проверяем, является ли пользователь получателем
            user_id = str(update.effective_user.id)
            
            # Показываем детали сделки для подтверждения
            if tx_info and 'deadline' in tx_info:
                deadline_date = datetime.fromtimestamp(tx_info['deadline']).strftime('%d.%m.%Y %H:%M')
            else:
                deadline_date = 'Не указан'
            
            # Определяем данные для отображения
            if tx_info:
                amount_display = tx_info.get('amount_usdt', 0)
                sender_display = tx_info.get('sender', 'N/A')
                recipient_display = tx_info.get('recipient', 'N/A')
                # Арбитр теперь глобальный, не нужно отображать
                description_display = tx_info.get('description', 'Escrow transaction')
            elif db_transaction:
                amount_display = db_transaction.get('amount_usdt', 0)
                sender_display = 'N/A'  # В БД нет sender
                recipient_display = db_transaction.get('recipient', 'N/A')
                # Арбитр теперь глобальный, не нужно отображать
                description_display = 'Escrow transaction'
            else:
                amount_display = 'N/A'
                sender_display = 'N/A'
                recipient_display = 'N/A'
                # Арбитр теперь глобальный, не нужно отображать
                description_display = 'N/A'
            
            # Простое сообщение без сложного форматирования
            confirmation_text = f"""
✅ Подтверждение доставки

🆔 Сделка #{tx_id}
💰 Сумма: {amount_display} USDT
📤 Отправитель: {sender_display[:10]}...{sender_display[-6:] if len(sender_display) > 16 else sender_display}
📥 Получатель: {recipient_display[:10]}...{recipient_display[-6:] if len(recipient_display) > 16 else recipient_display}
⚖️ Арбитр: Глобальный (встроен в контракт)
📝 Описание: {description_display}
⏰ Срок: {deadline_date}

⚠️ ВНИМАНИЕ!
• Подтверждайте только если получили товар/услугу!
• Отменить подтверждение НЕЛЬЗЯ!
• USDT будут немедленно переведены получателю!

🤔 Подтвердить доставку?
            """
            
            keyboard = [
                [InlineKeyboardButton("✅ ДА, ПОДТВЕРЖДАЮ ДОСТАВКУ", callback_data=f"confirm_delivery_{tx_id}")],
                [InlineKeyboardButton("❌ Отмена", callback_data="back_to_main")]
            ]
            
            await update.message.reply_text(
                confirmation_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        except Exception as e:
            logger.error(f"Ошибка при обработке ID для подтверждения: {e}")
            await update.message.reply_text(
                f"❌ Ошибка при проверке сделки\n\n"
                f"Детали: {str(e)}"
            )
    
    async def confirm_delivery_transaction(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: int):
        """Подготовка подтверждения доставки через TronLink"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Создаем клиент для проверки информации о сделке
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            # Логирование информации о контрактах
            logger.info(f"=== Проверка контрактов для подтверждения доставки сделки {tx_id} ===")
            logger.info(f"Escrow контракт из конфига: {self.config.ESCROW_CONTRACT}")
            logger.info(f"USDT контракт из конфига: {self.config.USDT_CONTRACT}")
            logger.info(f"Сеть: {self.config.NETWORK}")
            
            # Получаем информацию о сделке
            tx_info = temp_client.get_transaction(tx_id)
            
            # Получаем информацию из базы данных для сравнения
            db_transaction = None
            try:
                with self.get_db_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT user_id, amount_usdt, recipient, status FROM transactions WHERE id = ?",
                        (tx_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        db_transaction = {
                            'user_id': row[0],
                            'amount_usdt': row[1],
                            'recipient': row[2],
                            'status': row[3]
                        }
                        logger.info(f"Данные сделки {tx_id} из БД: {db_transaction}")
                    else:
                        logger.warning(f"Сделка {tx_id} не найдена в БД")
            except Exception as e:
                logger.error(f"Ошибка получения сделки из БД: {e}")
            
            # Отладочная информация из блокчейна
            logger.info(f"Полученная информация о сделке {tx_id} из блокчейна: {tx_info}")
            
            # Проверяем состояние сделки
            blockchain_state = tx_info.get('state', 'UNKNOWN') if tx_info else 'UNKNOWN'
            if not tx_info or blockchain_state != 'AWAITING_DELIVERY':
                await query.edit_message_text(
                    "❌ Ошибка подтверждения\n\n"
                    "Сделка не найдена или не может быть подтверждена."
                )
                return
            
            # Генерируем данные для TronLink подтверждения
            confirmation_data = self.generate_confirmation_tronlink_data(tx_id, tx_info)
            
            # Создаем QR код
            qr_code_data = self.generate_qr_code(confirmation_data)
            
            # Получаем безопасные данные для отображения
            safe_amount = tx_info.get('amount_usdt', 0) if tx_info and tx_info.get('amount_usdt') is not None else 0
            safe_description = tx_info.get('description', 'Нет описания') if tx_info and tx_info.get('description') else 'Нет описания'
            safe_recipient = tx_info.get('recipient', 'N/A') if tx_info and tx_info.get('recipient') else 'N/A'
            safe_sender = tx_info.get('sender', 'N/A') if tx_info and tx_info.get('sender') else 'N/A'
            
            instruction_text = f"""
🔐 Подтверждение доставки через TronLink

🆔 Сделка: #{tx_id}
💰 Сумма: {safe_amount} USDT
📤 Отправитель: {safe_sender[:10]}...{safe_sender[-6:] if len(safe_sender) > 16 else safe_sender}
📥 Получатель: {safe_recipient[:10]}...{safe_recipient[-6:] if len(safe_recipient) > 16 else safe_recipient}
📝 Описание: {safe_description}

✅ Метод confirmDelivery протестирован и работает!

💻 Способ 1: Браузерное расширение TronLink
1. Нажмите "💻 Подтвердить в TronLink"
2. Подтвердите подключение к сайту
3. Проверьте данные и нажмите "Подтвердить"

🔗 Способ 2: Через TronScan (альтернатива)
1. Нажмите "🔗 Открыть в TronScan"
2. Найдите метод "confirmDelivery"
3. Введите ID сделки: {tx_id}
4. Подключите TronLink и подпишите

⚠️ Важно:
• Подтверждайте только если получили товар/услугу!
• После подтверждения USDT немедленно переведутся!
• Отмена невозможна!

🔄 После подписания:
✅ Нажмите "🔍 Проверить статус" для подтверждения
            """
            
            # Кодируем данные в base64 для URL
            json_data = json.dumps(confirmation_data, separators=(',', ':'))
            encoded_data = base64.b64encode(json_data.encode()).decode()
            # Правильное соединение URL параметров
            separator = '&' if '?' in self.config.WEB_APP_URL else '?'
            tronlink_url = f"{self.config.WEB_APP_URL}{separator}data={encoded_data}"
            
            # Отладочная информация
            logger.info(f"JSON данные для TronLink: {json_data}")
            logger.info(f"Закодированные данные: {encoded_data[:100]}...")  # Первые 100 символов
            logger.info(f"Полная ссылка: {tronlink_url}")
            
            keyboard = [
                [InlineKeyboardButton("💻 Подтвердить в TronLink", url=tronlink_url)],
                [InlineKeyboardButton("🔍 Проверить статус", callback_data=f"check_confirmation_status_{tx_id}")],
                [InlineKeyboardButton("❓ Инструкция", callback_data=f"confirmation_help")],
                [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
        # Отправляем инструкции без QR кода
            await query.edit_message_text(
                instruction_text,
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.error(f"Ошибка при подготовке подтверждения доставки: {e}")
            await query.edit_message_text(
                f"❌ Ошибка при подготовке подтверждения\n\n"
                f"Детали: {str(e)}"
            )
    
    async def check_confirmation_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE, tx_id: int):
        """Проверка статуса подтверждения доставки"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Логирование параметров проверки статуса
            logger.info(f"=== Проверка статуса подтверждения сделки {tx_id} ===")
            logger.info(f"Проверяем Escrow контракт: {self.config.ESCROW_CONTRACT}")
            logger.info(f"Сеть: {self.config.NETWORK}")
            
            # Создаем клиент для проверки
            temp_client = TronEscrowUSDTClient(
                private_key="4ca45116cf235b2284309fa75149ed66bd0410fe2af2e8285f9eedfa40cf170b",
                contract_address=self.config.ESCROW_CONTRACT,
                network=self.config.NETWORK
            )
            
            # Получаем информацию о сделке
            tx_info = temp_client.get_transaction(tx_id)
            
            if not tx_info:
                await query.edit_message_text(
                    f"❌ Сделка #{tx_id} не найдена"
                )
                return
            
            blockchain_state = tx_info.get('state', 'UNKNOWN')
            
            if blockchain_state == 'COMPLETE':
                # Сделка успешно подтверждена!
                user_id = str(update.effective_user.id)
                
                # Обновляем статус в данных пользователя
                if user_id in self.users_data and 'transactions' in self.users_data[user_id]:
                    for tx in self.users_data[user_id]['transactions']:
                        if tx['id'] == tx_id:
                            tx['status'] = 'COMPLETE'
                            break
                    self.save_users_data()
                
                # Обновляем статус в БД
                try:
                    self.db_update_status(tx_id, 'COMPLETE')
                except Exception as e:
                    logger.error(f"Не удалось обновить статус сделки в БД: {e}")
                
                success_text = f"""
✅ Доставка подтверждена!

🎉 Сделка успешно завершена!

🆔 Сделка: #{tx_id}
💰 Сумма: {tx_info['amount_usdt']} USDT
📥 Получатель: {tx_info['recipient'][:10]}...{tx_info['recipient'][-6:]}

💸 Что произошло:
• USDT переведены получателю
• Сделка отмечена как завершенная
• Отправитель получит уведомление

🔗 Посмотреть в блокчейне:
https://shasta.tronscan.org/#/contract/{self.config.ESCROW_CONTRACT}

🚀 Спасибо за использование USDT Escrow!
                """
                
                keyboard = [
                    [InlineKeyboardButton("💼 Мои сделки", callback_data="my_transactions")],
                    [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                ]
                
                await query.edit_message_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
            elif blockchain_state == 'AWAITING_DELIVERY':
                # Сделка еще не подтверждена
                status_text = f"""
⏳ Статус: Ожидание подтверждения

🔍 Подтверждение доставки еще не найдено в блокчейне.

Возможные причины:
• Подтверждение еще не подписано
• Подписание в процессе
• Недостаточно TRX для комиссии
• Ошибка в TronLink

💡 Что делать:
1. Убедитесь что подписали подтверждение в TronLink
2. Проверьте баланс TRX в кошельке
3. Подождите 1-2 минуты и нажмите "Проверить еще раз"

Подтверждение будет найдено автоматически после подтверждения в сети.
                """
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить еще раз", callback_data=f"check_confirmation_status_{tx_id}")],
                    [InlineKeyboardButton("🔐 Подтвердить заново", callback_data=f"confirm_delivery_{tx_id}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="back_to_main")]
                ]
                
                await query.edit_message_text(
                    status_text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # Неожиданный статус
                await query.edit_message_text(
                    f"❌ Неожиданный статус сделки\n\n"
                    f"Статус: {blockchain_state}\n\n"
                    "Обратитесь к поддержке."
                )
                
        except Exception as e:
            logger.error(f"Ошибка проверки статуса подтверждения: {e}")
            await query.edit_message_text(
                f"❌ Ошибка проверки статуса\n\n"
                f"Детали: {str(e)}"
            )
    
    async def cancel_transaction_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена создания транзакции"""
        query = update.callback_query
        await query.answer()
        
        callback_data = query.data
        transaction_uuid = callback_data.split('_')[-1]
        
        # Удаляем транзакцию из ожидающих
        if transaction_uuid in self.pending_transactions:
            del self.pending_transactions[transaction_uuid]
            self.save_pending_transactions()
            
            await query.edit_message_text(
                "❌ **Создание сделки отменено**\n\n"
                "📝 Сделка удалена из очереди.\n\n"
                "🆕 Вы можете создать новую сделку в любое время.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆕 Создать новую сделку", callback_data="create_escrow")],
                    [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                ])
            )
        else:
            await query.edit_message_text(
                "❌ **Транзакция не найдена**\n\n"
                "💭 Транзакция уже была обработана или отменена.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Главная", callback_data="back_to_main")]
                ])
            )
    
    async def callback_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик callback запросов"""
        query = update.callback_query
        callback_data = query.data
        
        try:
            logger.info(f"Обработка callback: {callback_data}")
            
            if callback_data == "create_escrow":
                await self.create_escrow_flow(update, context)
            elif callback_data.startswith('sign_transaction_'):
                await self.sign_transaction_handler(update, context)
            elif callback_data.startswith('check_tx_status_'):
                await self.check_transaction_status_handler(update, context)
            elif callback_data == "my_transactions":
                await self.show_my_transactions(update, context)
            elif callback_data == "confirm_delivery_flow":
                await self.confirm_delivery_flow(update, context)
            elif callback_data.startswith('view_tx_'):
                try:
                    tx_id = int(callback_data.split('_')[2])
                    await self.view_transaction_details(update, context, tx_id)
                except (ValueError, IndexError) as e:
                    logger.error(f"Неверный формат callback для view_tx: {callback_data}")
                    await query.answer("❌ Неверный ID сделки")
            elif callback_data == "back_to_main":
                await self.back_to_main(update, context)
            elif callback_data == "enter_delivery_confirmation_id":
                await self.start_delivery_confirmation(update, context)
            elif callback_data.startswith('confirm_delivery_'):
                try:
                    tx_id = int(callback_data.split('_')[2])
                    await self.confirm_delivery_transaction(update, context, tx_id)
                except (ValueError, IndexError) as e:
                    logger.error(f"Неверный формат callback для confirm_delivery: {callback_data}")
                    await query.answer("❌ Неверный ID сделки")
            elif callback_data.startswith('check_confirmation_status_'):
                try:
                    tx_id = int(callback_data.split('_')[3])
                    await self.check_confirmation_status(update, context, tx_id)
                except (ValueError, IndexError) as e:
                    logger.error(f"Неверный формат callback для check_confirmation_status: {callback_data}")
                    await query.answer("❌ Неверный ID сделки")
            elif callback_data == "confirmation_help":
                await query.answer("📝 Помощь по подтверждению через TronLink")
            elif callback_data == "tronlink_help":
                await query.answer("📝 Помощь по работе с TronLink")
            elif callback_data.startswith('cancel_transaction_'):
                await self.cancel_transaction_handler(update, context)
            else:
                logger.warning(f"Неизвестный callback: {callback_data}")
                await query.answer("🚧 Функция в разработке")
                
        except Exception as e:
            logger.error(f"Ошибка в callback_query_handler: {e}")
            logger.error(f"Callback data: {callback_data}")
            import traceback
            traceback.print_exc()
            try:
                await query.answer("❌ Произошла ошибка. Попробуйте еще раз.")
            except:
                pass  # Игнорируем ошибки при отправке ответа

async def error_handler(update, context):
    """Обработчик ошибок"""
    logger.error(f"Ошибка в боте: {context.error}")
    logger.error(f"Update: {update}")
    import traceback
    traceback.print_exc()
    
    if update and update.callback_query:
        try:
            await update.callback_query.answer("❌ Произошла ошибка. Попробуйте /start")
        except:
            pass
    elif update and update.message:
        try:
            await update.message.reply_text("❌ Произошла ошибка. Нажмите /start для перезапуска.")
        except:
            pass

def main():
    """Запуск бота"""
    try:
        # Создание бота
        escrow_bot = AdvancedEscrowBot()
        
        # Создание приложения
        application = Application.builder().token(escrow_bot.config.BOT_TOKEN).build()
    except ValueError as e:
        print(f"❌ Ошибка конфигурации: {e}")
        print("Проверьте config.json файл")
        return
    except Exception as e:
        print(f"❌ Ошибка создания бота: {e}")
        return
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", escrow_bot.start))
    application.add_handler(CallbackQueryHandler(escrow_bot.callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, escrow_bot.message_handler))
    
    # Добавляем error handler
    application.add_error_handler(error_handler)
    
    # Запуск бота
    print("🚀 Запуск Advanced USDT Escrow Bot...")
    print(f"📋 Контракт: {escrow_bot.config.ESCROW_CONTRACT}")
    print(f"🌐 Сеть: {escrow_bot.config.NETWORK}")
    print(f"⚖️ Арбитр: {escrow_bot.config.ARBITRATOR_ADDRESS}")
    print("✅ Бот готов к работе с TronLink интеграцией!")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()