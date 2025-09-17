#!/usr/bin/env python3
"""
Скрипт для синхронизации pending транзакций с блокчейном
"""

import json
import sqlite3
import time
from datetime import datetime
import sys
import os

# Добавляем путь к папке scripts
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(script_dir)

from tron_escrow_usdt_client import TronEscrowUSDTClient
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Конфигурация проекта
class Config:
    def __init__(self):
        self.config = self.load_config()
        
        # TRON настройки
        self.NETWORK = self.config.get('settings', {}).get('default_network', 'shasta')
        network_config = self.config.get('networks', {}).get(self.NETWORK, {})
        self.ESCROW_CONTRACT = network_config.get('escrow_contract', "TB7qTmS58rPHH3N1CahLGfAnm5EsSbCMsu")
        self.USDT_CONTRACT = network_config.get('usdt_contract', "TKZDdu947FtxWHLRKUXnhNZ6bar9RrZ7Wv")
        self.ARBITRATOR_ADDRESS = network_config.get('arbitrator_address', "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2")
        
        # Файлы для хранения данных
        project_root = os.path.dirname(script_dir)
        self.USERS_DATA_FILE = os.path.join(project_root, "users_data.json")
        self.PENDING_TRANSACTIONS_FILE = os.path.join(project_root, "pending_transactions.json")
        
    def load_config(self):
        """Загрузка конфигурации из JSON файла"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
        return {}

def sync_pending_transactions():
    """Синхронизация pending транзакций с блокчейном"""
    config = Config()
    
    # Загружаем pending транзакции
    pending_file = config.PENDING_TRANSACTIONS_FILE
    if not os.path.exists(pending_file):
        print("❌ Файл pending транзакций не найден")
        return
    
    with open(pending_file, 'r', encoding='utf-8') as f:
        pending_transactions = json.load(f)
    
    if not pending_transactions:
        print("✅ Нет pending транзакций для синхронизации")
        return
    
    print(f"🔄 Найдено {len(pending_transactions)} pending транзакций")
    
    # Создаем клиент для чтения блокчейна
    try:
        client = TronEscrowUSDTClient(
            private_key="0000000000000000000000000000000000000000000000000000000000000001",  # Dummy key для чтения
            contract_address=config.ESCROW_CONTRACT,
            network=config.NETWORK
        )
        
        # Получаем общее количество транзакций в блокчейне
        total_transactions = client.get_transaction_count()
        print(f"📊 Всего транзакций в блокчейне: {total_transactions}")
        
        # Подключаемся к базе данных
        db_path = os.path.join(os.path.dirname(__file__), '..', 'bots', 'unified_escrow.db')
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        synced_count = 0
        
        for uuid, tx_data in list(pending_transactions.items()):
            user_id = tx_data.get('user_id')
            amount = tx_data.get('data', {}).get('amount', 0)
            recipient = tx_data.get('data', {}).get('recipient', '')
            created_at = tx_data.get('created_at', int(time.time()))
            
            print(f"\n🔍 Проверяем UUID: {uuid}")
            print(f"   👤 Пользователь: {user_id}")
            print(f"   💰 Сумма: {amount} USDT")
            print(f"   📨 Получатель: {recipient}")
            
            # Проверяем все транзакции в блокчейне, начиная с последней
            found_blockchain_id = None
            
            for blockchain_id in range(total_transactions - 1, -1, -1):
                try:
                    tx_info = client.get_transaction(blockchain_id)
                    if not tx_info:
                        continue
                        
                    # Сравниваем параметры транзакции
                    blockchain_recipient = tx_info.get('recipient', '')
                    blockchain_amount = tx_info.get('amount', 0) / 1000000  # Конвертируем из микро-USDT
                    
                    # Проверяем совпадение по получателю и статусу AWAITING_DELIVERY
                    # (Поскольку amount часто показывает 0 в контракте)
                    tx_state = tx_info.get('state', '')
                    if (blockchain_recipient.lower() == recipient.lower() and 
                        tx_state == 'AWAITING_DELIVERY' and blockchain_id >= total_transactions - 10):  # Проверяем только последние 10 транзакций
                        found_blockchain_id = blockchain_id
                        print(f"   ✅ Найдена в блокчейне с ID: {blockchain_id}")
                        print(f"   📊 Статус: {tx_info.get('state', 'Unknown')}")
                        break
                        
                except Exception as e:
                    print(f"   ⚠️ Ошибка при проверке транзакции {blockchain_id}: {e}")
                    continue
            
            if found_blockchain_id is not None:
                # Добавляем в базу данных
                try:
                    cur.execute("""
                        INSERT OR REPLACE INTO transactions (id, user_id, amount_usdt, recipient, status, role, created_at, uuid)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (found_blockchain_id, user_id, amount, recipient, 'AWAITING_DELIVERY', 'creator', created_at, uuid))
                    
                    # Удаляем из pending
                    del pending_transactions[uuid]
                    synced_count += 1
                    
                    print(f"   🎉 Синхронизировано! UUID {uuid} -> Blockchain ID {found_blockchain_id}")
                    
                except Exception as e:
                    print(f"   ❌ Ошибка при сохранении в БД: {e}")
            else:
                print(f"   ⏳ Транзакция еще не найдена в блокчейне")
        
        # Сохраняем изменения
        conn.commit()
        conn.close()
        
        # Обновляем файл pending транзакций
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(pending_transactions, f, ensure_ascii=False, indent=2)
        
        print(f"\n🎯 Результат синхронизации:")
        print(f"   ✅ Синхронизировано: {synced_count} транзакций")
        print(f"   ⏳ Осталось pending: {len(pending_transactions)} транзакций")
        
    except Exception as e:
        print(f"❌ Ошибка синхронизации: {e}")

if __name__ == "__main__":
    print("🚀 Запуск синхронизации pending транзакций с блокчейном...")
    sync_pending_transactions()
    print("✨ Синхронизация завершена!")