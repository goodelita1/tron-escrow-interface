#!/usr/bin/env python3
"""
Скрипт для проверки всех транзакций в смарт-контракте
"""

import json
import os
from tronapi import Tron
from tronapi.providers.http import HttpProvider
import sys

# Добавляем путь к корневой папке проекта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_config():
    """Загрузка конфигурации"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

def check_all_transactions():
    """Проверка всех транзакций в контракте"""
    config = load_config()
    
    # Настройки сети
    network = config.get('settings', {}).get('default_network', 'shasta')
    network_config = config.get('networks', {}).get(network, {})
    
    contract_address = network_config.get('escrow_contract')
    print(f"🔍 Проверяем контракт: {contract_address}")
    print(f"🌐 Сеть: {network}")
    
    # Настройка провайдера
    if network == 'mainnet':
        provider_url = "https://api.trongrid.io"
    elif network == 'shasta':
        provider_url = "https://api.shasta.trongrid.io"
    elif network == 'nile':
        provider_url = "https://nile.trongrid.io"
    else:
        raise ValueError(f"Неизвестная сеть: {network}")
    
    # Инициализация Tron API
    tron = Tron()
    tron.set_http_provider(provider_url)
    
    try:
        # Получаем количество транзакций
        result = tron.trx.trigger_smart_contract(
            contract_address,
            "transactionCount()",
            "",
            "",
            ""
        )
        
        if not result.get('result', {}).get('result'):
            print("❌ Ошибка вызова transactionCount")
            return
            
        # Декодируем результат (hex -> int)
        count_hex = result['constant_result'][0]
        count = int(count_hex, 16) if count_hex else 0
        
        print(f"📊 Всего транзакций в контракте: {count}")
        
        if count == 0:
            print("ℹ️  Транзакций нет")
            return
            
        # Получаем информацию о каждой транзакции
        for tx_id in range(count):
            print(f"\n🔍 Транзакция {tx_id}:")
            
            # Вызываем getTransaction
            result = tron.trx.trigger_smart_contract(
                contract_address,
                "getTransaction(uint256)",
                f"{tx_id:064x}",  # Преобразуем в hex с нулями слева
                "",
                ""
            )
            
            if not result.get('result', {}).get('result'):
                print(f"  ❌ Ошибка получения транзакции {tx_id}")
                continue
                
            # Декодируем результат
            constant_result = result['constant_result'][0]
            
            if not constant_result or len(constant_result) < 64*8:  # 8 параметров по 64 символа
                print(f"  ❌ Некорректный результат для транзакции {tx_id}")
                continue
                
            # Парсим результат (8 параметров)
            sender = "T" + tron.toBase58Check("41" + constant_result[24:64])  # address sender
            recipient = "T" + tron.toBase58Check("41" + constant_result[88:128])  # address recipient
            amount = int(constant_result[128:192], 16)  # uint256 amount
            state = int(constant_result[192:256], 16)  # State state
            created_at = int(constant_result[256:320], 16)  # uint256 createdAt
            deadline = int(constant_result[320:384], 16)  # uint256 deadline
            sender_approved = bool(int(constant_result[384:448], 16))  # bool senderApproved
            recipient_approved = bool(int(constant_result[448:512], 16))  # bool recipientApproved
            
            # Названия состояний
            state_names = {
                0: "AWAITING_PAYMENT",
                1: "AWAITING_DELIVERY", 
                2: "COMPLETE",
                3: "DISPUTED",
                4: "REFUNDED"
            }
            
            print(f"  👤 Отправитель: {sender}")
            print(f"  📨 Получатель: {recipient}")
            print(f"  💰 Сумма: {amount / 1000000:.6f} USDT")
            print(f"  📊 Состояние: {state_names.get(state, f'Неизвестно ({state})')}")
            print(f"  ⏰ Создано: {created_at} (timestamp)")
            print(f"  ⏳ Дедлайн: {deadline} (timestamp)")
            print(f"  ✅ Отправитель подтвердил: {sender_approved}")
            print(f"  ✅ Получатель подтвердил: {recipient_approved}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_all_transactions()