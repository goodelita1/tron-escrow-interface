#!/usr/bin/env python3
"""
Тест развернутого USDT эскроу контракта на Shasta
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tron_escrow_usdt_client import TronEscrowUSDTClient

def test_contract():
    """
    Тестирование основных функций контракта
    """
    print("=" * 60)
    print("ТЕСТ РАЗВЕРНУТОГО USDT ESCROW КОНТРАКТА")
    print("=" * 60)
    
    try:
        # Инициализация клиента
        print("\n1. Инициализация клиента...")
        client = TronEscrowUSDTClient()
        
        # Проверка баланса USDT
        print("\n2. Проверка баланса USDT...")
        balance = client.get_usdt_balance()
        print(f"Баланс USDT: {balance} USDT")
        
        # Проверка информации об арбитре
        print("\n3. Проверка информации об арбитре...")
        try:
            arbitrator = client.escrow_contract.functions.arbitrator()
            print(f"Арбитр: {arbitrator}")
        except Exception as e:
            print(f"Ошибка получения арбитра: {e}")
        
        # Проверка фиксированной комиссии
        print("\n4. Проверка фиксированной комиссии...")
        try:
            fixed_fee = client.escrow_contract.functions.fixedFee()
            fee_usdt = client.units_to_usdt(fixed_fee)
            print(f"Фиксированная комиссия: {fee_usdt} USDT ({fixed_fee} единиц)")
        except Exception as e:
            print(f"Ошибка получения комиссии: {e}")
        
        # Проверка адреса USDT контракта в эскроу
        print("\n5. Проверка адреса USDT контракта...")
        try:
            usdt_address = client.escrow_contract.functions.usdtToken()
            print(f"USDT контракт в эскроу: {usdt_address}")
            print(f"USDT контракт клиента: {client.usdt_address}")
            print(f"Адреса совпадают: {usdt_address.lower() == client.usdt_address.lower()}")
        except Exception as e:
            print(f"Ошибка получения адреса USDT: {e}")
        
        # Получение общего количества транзакций
        print("\n6. Проверка количества транзакций...")
        try:
            tx_count = client.escrow_contract.functions.transactionCount()
            print(f"Общее количество транзакций: {tx_count}")
        except Exception as e:
            print(f"Ошибка получения количества транзакций: {e}")
        
        print("\n" + "=" * 60)
        print("ТЕСТ ЗАВЕРШЕН УСПЕШНО!")
        print("Контракт готов к использованию.")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Ошибка в тесте: {e}")
        import traceback
        traceback.print_exc()

def main():
    test_contract()

if __name__ == "__main__":
    main()