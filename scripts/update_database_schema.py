#!/usr/bin/env python3
"""
Скрипт для обновления схемы базы данных
Добавляет поле uuid для связи между bot UUID и blockchain ID
"""

import sqlite3
import os
import sys

def update_database_schema():
    """Обновление схемы базы данных"""
    
    # Путь к базе данных
    db_path = os.path.join(os.path.dirname(__file__), '..', 'bots', 'unified_escrow.db')
    
    print("🔧 Обновление схемы базы данных...")
    print(f"📁 База данных: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # Проверяем текущую схему
        cur.execute("PRAGMA table_info(transactions)")
        columns = cur.fetchall()
        
        print("\n📊 Текущие колонки в таблице transactions:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        # Проверяем, есть ли уже колонка uuid
        column_names = [col[1] for col in columns]
        if 'uuid' in column_names:
            print("✅ Колонка 'uuid' уже существует")
        else:
            print("\n🆕 Добавляем колонку 'uuid'...")
            cur.execute("ALTER TABLE transactions ADD COLUMN uuid TEXT")
            
            # Создаем индекс для быстрого поиска по UUID
            print("📇 Создаем индекс для UUID...")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_transactions_uuid ON transactions(uuid)")
            
            conn.commit()
            print("✅ Колонка 'uuid' добавлена успешно")
        
        # Показываем обновленную схему
        cur.execute("PRAGMA table_info(transactions)")
        updated_columns = cur.fetchall()
        
        print("\n📊 Обновленная схема таблицы transactions:")
        for col in updated_columns:
            print(f"  - {col[1]} ({col[2]})" + (" [НОВОЕ]" if col[1] == 'uuid' else ""))
        
        # Показываем индексы
        cur.execute("PRAGMA index_list(transactions)")
        indexes = cur.fetchall()
        
        print("\n📇 Индексы:")
        for idx in indexes:
            print(f"  - {idx[1]}")
        
        conn.close()
        print("\n✅ Схема базы данных обновлена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка обновления схемы: {e}")
        return False
    
    return True

def main():
    print("🚀 ОБНОВЛЕНИЕ СХЕМЫ БАЗЫ ДАННЫХ")
    print("=" * 50)
    
    success = update_database_schema()
    
    if success:
        print("\n🎉 Готово! Теперь можно связывать UUID с blockchain ID")
    else:
        print("\n💥 Обновление не удалось")

if __name__ == "__main__":
    main()