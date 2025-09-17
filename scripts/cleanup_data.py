#!/usr/bin/env python3
"""
Скрипт для очистки и синхронизации локальных данных с блокчейном
Удаляет несуществующие транзакции из локального кэша
"""

import os
import json
import sqlite3
from datetime import datetime
import sys

# Добавляем путь к корневой директории
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from scripts.tron_escrow_usdt_client import TronEscrowUSDTClient

class DataCleaner:
    def __init__(self):
        self.root_dir = os.path.dirname(os.path.dirname(__file__))
        self.users_data_file = os.path.join(self.root_dir, 'users_data.json')
        self.scripts_users_data_file = os.path.join(self.root_dir, 'scripts', 'users_data.json')
        self.pending_transactions_file = os.path.join(self.root_dir, 'scripts', 'pending_transactions.json')
        self.db_path = os.path.join(self.root_dir, 'bots', 'unified_escrow.db')
        
        # Создаем TRON клиент для проверки блокчейна
        self.client = TronEscrowUSDTClient()
        
    def load_json_file(self, filepath):
        """Загрузка JSON файла"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️  Ошибка загрузки {filepath}: {e}")
        return {}
    
    def save_json_file(self, filepath, data):
        """Сохранение JSON файла"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"✅ Сохранен {filepath}")
        except Exception as e:
            print(f"❌ Ошибка сохранения {filepath}: {e}")
    
    def get_blockchain_transaction_ids(self):
        """Получение всех существующих ID транзакций из блокчейна"""
        try:
            tx_count = self.client.get_transaction_count()
            if tx_count is None:
                print("❌ Не удалось получить количество транзакций из блокчейна")
                return set()
            
            valid_ids = set()
            for tx_id in range(tx_count):
                tx_info = self.client.get_transaction(tx_id)
                if tx_info:
                    valid_ids.add(tx_id)
            
            print(f"🔗 Найдено {len(valid_ids)} реальных транзакций в блокчейне: {sorted(valid_ids)}")
            return valid_ids
            
        except Exception as e:
            print(f"❌ Ошибка проверки блокчейна: {e}")
            return set()
    
    def cleanup_scripts_users_data(self, valid_tx_ids):
        """Очистка scripts/users_data.json от несуществующих транзакций"""
        print("\n🧹 Очистка scripts/users_data.json...")
        
        data = self.load_json_file(self.scripts_users_data_file)
        if not data:
            print("📁 Файл scripts/users_data.json пустой или не существует")
            return
        
        cleaned = False
        
        for user_id, user_data in data.items():
            if 'transactions' in user_data:
                original_count = len(user_data['transactions'])
                
                # Фильтруем только существующие транзакции
                valid_transactions = []
                invalid_transactions = []
                
                for tx in user_data['transactions']:
                    tx_id = tx.get('id')
                    if tx_id in valid_tx_ids:
                        valid_transactions.append(tx)
                        print(f"✅ Пользователь {user_id}: сохраняем транзакцию ID {tx_id}")
                    else:
                        invalid_transactions.append(tx)
                        print(f"❌ Пользователь {user_id}: удаляем несуществующую транзакцию ID {tx_id}")
                
                user_data['transactions'] = valid_transactions
                
                # Обновляем счетчик созданных транзакций
                user_data['transactions_created'] = len(valid_transactions)
                
                if len(invalid_transactions) > 0:
                    cleaned = True
                    print(f"🗑️  Удалено {len(invalid_transactions)} несуществующих транзакций для пользователя {user_id}")
        
        if cleaned:
            # Создаем бэкап
            backup_file = self.scripts_users_data_file + '.backup.' + datetime.now().strftime('%Y%m%d_%H%M%S')
            self.save_json_file(backup_file, self.load_json_file(self.scripts_users_data_file))
            print(f"💾 Создан бэкап: {os.path.basename(backup_file)}")
            
            # Сохраняем очищенные данные
            self.save_json_file(self.scripts_users_data_file, data)
            print("✅ scripts/users_data.json очищен и обновлен")
        else:
            print("✅ scripts/users_data.json не нуждается в очистке")
    
    def cleanup_database(self, valid_tx_ids):
        """Очистка базы данных от несуществующих транзакций"""
        print("\n🧹 Очистка базы данных...")
        
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            
            # Получаем все транзакции из БД
            cur.execute("SELECT id, user_id, amount_usdt, recipient FROM transactions")
            db_transactions = cur.fetchall()
            
            if not db_transactions:
                print("📁 База данных пуста")
                conn.close()
                return
            
            print(f"📊 Найдено {len(db_transactions)} транзакций в базе данных")
            
            # Находим несуществующие транзакции
            invalid_tx_ids = []
            for tx in db_transactions:
                tx_id, user_id, amount, recipient = tx
                if tx_id not in valid_tx_ids:
                    invalid_tx_ids.append(tx_id)
                    print(f"❌ Найдена несуществующая транзакция в БД: ID {tx_id} (пользователь {user_id})")
                else:
                    print(f"✅ Валидная транзакция в БД: ID {tx_id}")
            
            # Удаляем несуществующие транзакции
            if invalid_tx_ids:
                placeholders = ','.join('?' * len(invalid_tx_ids))
                cur.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", invalid_tx_ids)
                conn.commit()
                print(f"🗑️  Удалено {len(invalid_tx_ids)} несуществующих транзакций из БД")
            else:
                print("✅ База данных не нуждается в очистке")
            
            conn.close()
            
        except Exception as e:
            print(f"❌ Ошибка работы с базой данных: {e}")
    
    def cleanup_pending_transactions(self):
        """Очистка старых ожидающих транзакций (старше 24 часов)"""
        print("\n🧹 Очистка pending_transactions.json...")
        
        data = self.load_json_file(self.pending_transactions_file)
        if not data:
            print("📁 Файл pending_transactions.json пустой или не существует")
            return
        
        current_time = int(datetime.now().timestamp())
        cleaned_data = {}
        removed_count = 0
        
        for tx_uuid, tx_data in data.items():
            created_at = tx_data.get('created_at', 0)
            age_hours = (current_time - created_at) / 3600
            
            if age_hours > 24:  # Старше 24 часов
                print(f"❌ Удаляем старую ожидающую транзакцию {tx_uuid} (возраст: {age_hours:.1f} часов)")
                removed_count += 1
            else:
                cleaned_data[tx_uuid] = tx_data
                print(f"✅ Сохраняем ожидающую транзакцию {tx_uuid} (возраст: {age_hours:.1f} часов)")
        
        if removed_count > 0:
            self.save_json_file(self.pending_transactions_file, cleaned_data)
            print(f"🗑️  Удалено {removed_count} старых ожидающих транзакций")
        else:
            print("✅ pending_transactions.json не нуждается в очистке")
    
    def print_summary(self):
        """Показать итоговую сводку"""
        print("\n" + "="*60)
        print("📊 ИТОГОВАЯ СВОДКА ПОСЛЕ ОЧИСТКИ")
        print("="*60)
        
        # Блокчейн
        try:
            tx_count = self.client.get_transaction_count()
            print(f"🔗 Транзакций в блокчейне: {tx_count}")
        except:
            print("🔗 Транзакций в блокчейне: ❌ Ошибка проверки")
        
        # База данных
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM transactions")
            db_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users")
            users_count = cur.fetchone()[0]
            conn.close()
            print(f"💾 Транзакций в БД: {db_count}")
            print(f"👥 Пользователей в БД: {users_count}")
        except:
            print("💾 База данных: ❌ Ошибка чтения")
        
        # JSON файлы
        scripts_data = self.load_json_file(self.scripts_users_data_file)
        pending_data = self.load_json_file(self.pending_transactions_file)
        
        total_local_tx = 0
        for user_data in scripts_data.values():
            total_local_tx += len(user_data.get('transactions', []))
        
        print(f"📁 Локальных транзакций: {total_local_tx}")
        print(f"⏳ Ожидающих транзакций: {len(pending_data)}")
        
        print("="*60)
    
    def run(self):
        """Запуск полной очистки"""
        print("🚀 НАЧАЛО ОЧИСТКИ И СИНХРОНИЗАЦИИ ДАННЫХ")
        print("="*60)
        
        # Получаем валидные ID из блокчейна
        valid_tx_ids = self.get_blockchain_transaction_ids()
        
        if not valid_tx_ids:
            print("⚠️  Не найдено валидных транзакций в блокчейне. Очистка отменена.")
            return
        
        # Очистка всех источников данных
        self.cleanup_scripts_users_data(valid_tx_ids)
        self.cleanup_database(valid_tx_ids)
        self.cleanup_pending_transactions()
        
        # Итоговая сводка
        self.print_summary()
        
        print("\n✅ ОЧИСТКА ЗАВЕРШЕНА УСПЕШНО!")

def main():
    cleaner = DataCleaner()
    cleaner.run()

if __name__ == "__main__":
    main()