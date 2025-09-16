#!/usr/bin/env python3
"""
Прямое тестирование создания транзакции с новым контрактом
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tron_escrow_usdt_client import TronEscrowUSDTClient
import time

def test_create_transaction():
    """
    Тестирование создания транзакции напрямую
    """
    print("=" * 60)
    print("ТЕСТ СОЗДАНИЯ ТРАНЗАКЦИИ С НОВЫМ КОНТРАКТОМ")
    print("=" * 60)
    
    try:
        # Инициализация клиента с нашими параметрами
        print("\n1. Инициализация клиента...")
        client = TronEscrowUSDTClient()
        
        # Проверяем баланс USDT
        print("\n2. Проверка баланса USDT...")
        balance = client.get_usdt_balance()
        print(f"Баланс USDT: {balance} USDT")
        
        if balance < 101:
            print("❌ Недостаточно USDT для теста")
            return
        
        # Параметры для тестовой транзакции
        recipient = "TJtq3AVtNTngU23HFinp22rh6Ufcy78Ce4"
        amount = 101.0  # 101 USDT
        deadline_hours = 48
        
        print(f"\n3. Создание транзакции...")
        print(f"   Получатель: {recipient}")
        print(f"   Сумма: {amount} USDT")
        print(f"   Дедлайн: {deadline_hours} часов")
        
        # Сначала approve USDT
        print(f"\n4. Approve USDT для контракта...")
        approve_txid = client.approve_usdt(client.escrow_contract.contract_address, amount)
        
        if not approve_txid:
            print("❌ Ошибка approve USDT")
            return
        
        print(f"✅ Approve выполнен: {approve_txid}")
        
        # Ждем подтверждения
        print("\n5. Ожидание подтверждения approve...")
        if client.wait_for_transaction(approve_txid, timeout=30):
            print("✅ Approve подтвержден")
        else:
            print("⚠️ Approve не подтвержден, но продолжаем...")
        
        # Создаем транзакцию
        print(f"\n6. Создание escrow транзакции...")
        create_txid = client.create_transaction(recipient, amount, deadline_hours)
        
        if create_txid:
            print(f"✅ Транзакция создана успешно!")
            print(f"   Transaction ID: {create_txid}")
            
            # Ждем подтверждения
            print("\n7. Ожидание подтверждения транзакции...")
            if client.wait_for_transaction(create_txid, timeout=60):
                print("✅ Транзакция подтверждена в блокчейне!")
                
                # Получаем информацию о транзакции
                print("\n8. Получение информации о транзакции...")
                time.sleep(5)  # Даем время на обработку
                
                # Получаем количество транзакций
                tx_count = client.escrow_contract.functions.transactionCount()
                print(f"   Общее количество транзакций: {tx_count}")
                
                if tx_count > 0:
                    # Проверяем последнюю транзакцию (ID = tx_count - 1)
                    last_tx_id = tx_count - 1
                    tx_info = client.get_transaction(last_tx_id)
                    
                    if tx_info:
                        print(f"   Информация о транзакции #{last_tx_id}:")
                        print(f"   - Отправитель: {tx_info.get('sender', 'N/A')}")
                        print(f"   - Получатель: {tx_info.get('recipient', 'N/A')}")
                        print(f"   - Сумма: {tx_info.get('amount_usdt', 0)} USDT")
                        print(f"   - Статус: {tx_info.get('state', 'N/A')}")
                        print(f"   - Дедлайн: {tx_info.get('deadline', 'N/A')}")
                        
                        print("\n🎉 ТЕСТ УСПЕШЕН!")
                        print(f"ID новой транзакции в контракте: {last_tx_id}")
                        return last_tx_id
                    else:
                        print("⚠️ Не удалось получить информацию о транзакции")
                else:
                    print("❌ Транзакция не найдена в контракте")
            else:
                print("⚠️ Транзакция не подтвердилась, но возможно выполнена")
        else:
            print("❌ Ошибка создания транзакции")
            
    except Exception as e:
        print(f"\n❌ Ошибка в тесте: {e}")
        import traceback
        traceback.print_exc()

def main():
    test_create_transaction()

if __name__ == "__main__":
    main()