import json
import time
from tronpy import Tron
from tronpy.keys import PrivateKey
from typing import Optional, Dict, Any, Tuple
import os

# USDT TRC-20 ABI
USDT_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "transferFrom",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function"
    }
]

class TronEscrowUSDTClient:
    """
    Клиент для взаимодействия с USDT ESCROW смарт-контрактом на TRON
    """
    
    def __init__(self, 
                 private_key: str = None, 
                 contract_address: str = None,
                 usdt_contract_address: str = None,
                 network: str = None,
                 config_file: str = "../config.json"):
        """
        Инициализация клиента
        
        Args:
            private_key: Приватный ключ кошелька (если None, берется из config.json)
            contract_address: Адрес развернутого USDT escrow контракта (если None, берется из config.json)
            usdt_contract_address: Адрес USDT токена (если None, берется из config.json)
            network: Сеть (если None, берется из config.json)
            config_file: Путь к файлу конфигурации
        """
        
        # Загрузка конфигурации
        config = self.load_config(config_file)
        
        # Определение сети
        self.network = network or config.get('settings', {}).get('default_network', 'shasta')
        network_config = config.get('networks', {}).get(self.network, {})
        
        # Получение параметров из конфига или аргументов
        self.private_key_str = private_key or network_config.get('private_key')
        self.contract_address = contract_address or network_config.get('escrow_contract')
        self.usdt_address = usdt_contract_address or network_config.get('usdt_contract')
        
        if not all([self.private_key_str, self.contract_address, self.usdt_address]):
            raise ValueError("Не указаны необходимые параметры. Проверьте config.json или передайте параметры напрямую.")
        # Настройка сети
        if self.network == "mainnet":
            self.tron = Tron()
        elif self.network == "nile":
            self.tron = Tron(network='nile')
        elif self.network == "shasta":
            self.tron = Tron(network='shasta')
        else:
            raise ValueError("Поддерживаемые сети: mainnet, nile, shasta")
        
        # Настройка ключа
        self.private_key = PrivateKey(bytes.fromhex(self.private_key_str))
        self.address = self.private_key.public_key.to_base58check_address()
        
        # Получение контрактов
        self.escrow_contract = self.tron.get_contract(self.contract_address)
        
        # USDT контракт с ABI
        try:
            self.usdt_contract = self.tron.get_contract(self.usdt_address)
            # Если ABI не загружен автоматически, устанавливаем вручную
            if not hasattr(self.usdt_contract, 'abi') or not self.usdt_contract.abi:
                self.usdt_contract.abi = USDT_ABI
        except Exception as e:
            print(f"Предупреждение: Не удалось загрузить USDT контракт: {e}")
            print("Создаем контракт с ABI вручную...")
            from tronpy.contract import Contract
            self.usdt_contract = Contract(
                address=self.usdt_address,
                abi=USDT_ABI,
                tron=self.tron,
                owner_address=self.address
            )
        
        print(f"Клиент инициализирован для адреса: {self.address}")
        print(f"Escrow контракт: {self.contract_address}")
        print(f"USDT контракт: {self.usdt_address}")
        print(f"Сеть: {self.network}")
    
    def load_config(self, config_file: str) -> dict:
        """
        Загрузка конфигурации из JSON файла
        """
        try:
            config_path = os.path.join(os.path.dirname(__file__), config_file)
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка загрузки конфигурации: {e}")
            return {}
    
    def usdt_to_units(self, usdt_amount: float) -> int:
        """
        Конвертация USDT в единицы контракта (6 знаков после запятой)
        """
        return int(usdt_amount * 1_000_000)
    
    def units_to_usdt(self, units: int) -> float:
        """
        Конвертация единиц контракта в USDT
        """
        return units / 1_000_000
    
    def get_usdt_balance(self, address: str = None) -> float:
        """
        Получение баланса USDT для указанного адреса
        """
        try:
            target_address = address or self.address
            
            # Проверяем, что контракт доступен
            if not self.usdt_contract:
                print("Ошибка: USDT контракт не инициализирован")
                return 0.0
                
            # Вызов баланса
            balance_units = self.usdt_contract.functions.balanceOf(target_address)
            return self.units_to_usdt(balance_units)
            
        except Exception as e:
            print(f"Ошибка получения USDT баланса: {e}")
            print(f"Проверьте USDT контракт: {self.usdt_address}")
            return 0.0
    
    def get_usdt_allowance(self, spender_address: str) -> float:
        """
        Получение разрешенной суммы USDT для трат
        """
        try:
            # Проверяем, что контракт доступен
            if not self.usdt_contract:
                print("Ошибка: USDT контракт не инициализирован")
                return 0.0
                
            allowance_units = self.usdt_contract.functions.allowance(self.address, spender_address)
            return self.units_to_usdt(allowance_units)
            
        except Exception as e:
            print(f"Ошибка получения allowance: {e}")
            print(f"Проверьте USDT контракт: {self.usdt_address}")
            return 0.0
    
    def approve_usdt(self, spender_address: str, amount_usdt: float) -> str:
        """
        Одобрение траты USDT для указанного адреса
        
        Args:
            spender_address: Адрес, которому разрешается тратить USDT
            amount_usdt: Сумма в USDT
            
        Returns:
            Transaction ID (hex)
        """
        try:
            amount_units = self.usdt_to_units(amount_usdt)
            
            txn = (
                self.usdt_contract.functions.approve(spender_address, amount_units)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"USDT approve транзакция: {txn['txid']}")
            print(f"Одобрено: {amount_usdt} USDT для {spender_address}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка approve USDT: {e}")
            return None
    
    def create_transaction(self, 
                          recipient_address: str, 
                          amount_usdt: float, 
                          deadline_hours: int) -> str:
        """
        Создание новой USDT ESCROW транзакции
        
        Args:
            recipient_address: Адрес получателя
            amount_usdt: Сумма в USDT
            deadline_hours: Дедлайн в часах от текущего времени
            
        Returns:
            Transaction ID (hex)
        """
        try:
            amount_units = self.usdt_to_units(amount_usdt)
            
            # Проверяем минимальную сумму (должна быть больше 5 USDT комиссии)
            if amount_usdt <= 5.0:
                print(f"Сумма слишком мала. Минимальная сумма: 5.01 USDT (с учетом комиссии 5 USDT)")
                return None
            
            # Проверка баланса USDT
            balance = self.get_usdt_balance()
            if balance < amount_usdt:
                print(f"Недостаточно USDT. Баланс: {balance}, требуется: {amount_usdt}")
                return None
            
            # Проверка allowance
            allowance = self.get_usdt_allowance(self.escrow_contract.contract_address)
            if allowance < amount_usdt:
                print(f"Недостаточно allowance. Текущий: {allowance}, требуется: {amount_usdt}")
                print("Сначала выполните approve_usdt()")
                return None
            
            # Дедлайн в timestamp
            deadline = int(time.time()) + (deadline_hours * 3600)
            
            # Вызов функции контракта
            txn = (
                self.escrow_contract.functions.createTransaction(
                    recipient_address,
                    amount_units,  # Количество USDT
                    deadline
                )
                .with_owner(self.address)
                .fee_limit(100_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"USDT Escrow транзакция создана: {txn['txid']}")
            print(f"Общая сумма: {amount_usdt} USDT")
            print(f"К получателю после комиссии: {amount_usdt - 5.0} USDT")
            print(f"Комиссия платформы: 5.0 USDT")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка создания транзакции: {e}")
            return None
    
    def create_transaction_with_auto_approve(self,
                                           recipient_address: str, 
                                           amount_usdt: float, 
                                           deadline_hours: int) -> Tuple[str, str]:
        """
        Создание транзакции с автоматическим approve
        
        Returns:
            Tuple[approve_txid, create_txid]
        """
        try:
            # Сначала approve
            approve_txid = self.approve_usdt(self.escrow_contract.contract_address, amount_usdt)
            if not approve_txid:
                return None, None
            
            # Ждем подтверждения approve
            print("Ждем подтверждения approve...")
            if not self.wait_for_transaction(approve_txid, timeout=30):
                print("Approve не подтвердился")
                return approve_txid, None
            
            # Создаем транзакцию
            create_txid = self.create_transaction(
                recipient_address, 
                amount_usdt, deadline_hours
            )
            
            return approve_txid, create_txid
            
        except Exception as e:
            print(f"Ошибка создания транзакции с approve: {e}")
            return None, None
    
    def confirm_delivery(self, transaction_id: int) -> str:
        """
        Подтверждение получения товара/услуги (только получатель)
        """
        try:
            txn = (
                self.escrow_contract.functions.confirmDelivery(transaction_id)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"Доставка подтверждена: {txn['txid']}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка подтверждения доставки: {e}")
            return None
    
    def approve_funds_release(self, transaction_id: int) -> str:
        """
        Одобрение освобождения средств (только отправитель)
        """
        try:
            txn = (
                self.escrow_contract.functions.approveFundsRelease(transaction_id)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"Освобождение средств одобрено: {txn['txid']}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка одобрения: {e}")
            return None
    
    def raise_dispute(self, transaction_id: int) -> str:
        """
        Поднятие спора (любая из сторон)
        """
        try:
            txn = (
                self.escrow_contract.functions.raiseDispute(transaction_id)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"Спор поднят: {txn['txid']}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка поднятия спора: {e}")
            return None
    
    def resolve_dispute(self, transaction_id: int, release_to_recipient: bool) -> str:
        """
        Разрешение спора (только арбитр)
        
        Args:
            transaction_id: ID транзакции
            release_to_recipient: True - отдать получателю, False - вернуть отправителю
        """
        try:
            txn = (
                self.escrow_contract.functions.resolveDispute(transaction_id, release_to_recipient)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            action = "получателю" if release_to_recipient else "отправителю"
            print(f"Спор разрешен в пользу {action}: {txn['txid']}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка разрешения спора: {e}")
            return None
    
    def claim_refund_after_deadline(self, transaction_id: int) -> str:
        """
        Возврат средств после истечения дедлайна (только отправитель)
        """
        try:
            txn = (
                self.escrow_contract.functions.claimRefundAfterDeadline(transaction_id)
                .with_owner(self.address)
                .fee_limit(50_000_000)
                .build()
                .sign(self.private_key)
                .broadcast()
            )
            
            print(f"Возврат после дедлайна выполнен: {txn['txid']}")
            return txn['txid']
            
        except Exception as e:
            print(f"Ошибка возврата: {e}")
            return None
    
    def get_transaction(self, transaction_id: int) -> Dict[str, Any]:
        """
        Получение информации о транзакции
        """
        try:
            result = self.escrow_contract.functions.getTransaction(transaction_id)
            
            # Состояния транзакций
            states = {
                0: "AWAITING_PAYMENT",
                1: "AWAITING_DELIVERY", 
                2: "COMPLETE",
                3: "DISPUTED",
                4: "REFUNDED"
            }
            
            transaction_info = {
                "sender": result[0],
                "recipient": result[1],
                "amount_units": result[2],
                "amount_usdt": self.units_to_usdt(result[2]),
                "state": states.get(result[3], "UNKNOWN"),
                "created_at": result[4],
                "deadline": result[5],
                "sender_approved": result[6],
                "recipient_approved": result[7],
                "created_at_formatted": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result[4])),
                "deadline_formatted": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(result[5]))
            }
            
            return transaction_info
            
        except Exception as e:
            print(f"Ошибка получения информации о транзакции: {e}")
            return None
    
    def get_contract_usdt_balance(self) -> float:
        """
        Получение баланса USDT контракта
        """
        try:
            balance_units = self.escrow_contract.functions.getContractUSDTBalance()
            return self.units_to_usdt(balance_units)
        except Exception as e:
            print(f"Ошибка получения USDT баланса контракта: {e}")
            return None
    
    def get_usdt_token_address(self) -> str:
        """
        Получение адреса USDT токена из контракта
        """
        try:
            return self.escrow_contract.functions.getUSDTTokenAddress()
        except Exception as e:
            print(f"Ошибка получения адреса USDT токена: {e}")
            return None
    
    def get_platform_fee_in_usdt(self) -> float:
        """
        Получение текущей фиксированной комиссии в USDT
        """
        try:
            fee_usdt = self.escrow_contract.functions.getPlatformFeeInUSDT()
            return float(fee_usdt)
        except Exception as e:
            print(f"Ошибка получения комиссии: {e}")
            return 5.0  # По умолчанию
    
    def get_my_trx_balance(self) -> float:
        """
        Получение баланса TRX текущего кошелька (для оплаты gas)
        """
        try:
            account = self.tron.get_account(self.address)
            balance_sun = account.get('balance', 0)
            return balance_sun / 1_000_000
        except Exception as e:
            print(f"Ошибка получения TRX баланса кошелька: {e}")
            return None
    
    def wait_for_transaction(self, txid: str, timeout: int = 30) -> bool:
        """
        Ожидание подтверждения транзакции
        """
        for i in range(timeout):
            try:
                tx_info = self.tron.get_transaction(txid)
                if tx_info.get('ret'):
                    return True
                time.sleep(1)
            except:
                time.sleep(1)
        return False
    
    def get_transaction_count(self) -> int:
        """
        Получение общего количества транзакций в контракте
        """
        try:
            return self.escrow_contract.functions.transactionCount()
        except Exception as e:
            print(f"Ошибка получения количества транзакций: {e}")
            return None


def main():
    """
    Пример использования клиента для USDT escrow
    """
    try:
        # Создание клиента из config.json
        client = TronEscrowUSDTClient()
        
        # Проверка балансов
        usdt_balance = client.get_usdt_balance()
        trx_balance = client.get_my_trx_balance()
        print(f"USDT баланс: {usdt_balance}")
        print(f"TRX баланс: {trx_balance} (для gas)")
        
        contract_usdt_balance = client.get_contract_usdt_balance()
        print(f"USDT баланс контракта: {contract_usdt_balance}")
        
        # Проверка количества транзакций
        tx_count = client.get_transaction_count()
        print(f"Всего транзакций в контракте: {tx_count}")
        
        # Пример создания транзакции с автоматическим approve
        recipient = "TJtq3AVtNTngU23HFinp22rh6Ufcy78Ce4"
        
        print("\n=== Создание USDT Escrow транзакции ===")
        approve_txid, create_txid = client.create_transaction_with_auto_approve(
            recipient_address=recipient,
            amount_usdt=10.5,  # 10.5 USDT
            deadline_hours=24  # 24 часа
        )
        
        if create_txid and client.wait_for_transaction(create_txid):
            print("Escrow транзакция подтверждена!")
            
            # Получение информации о последней созданной транзакции
            latest_tx_id = client.get_transaction_count() - 1
            info = client.get_transaction(latest_tx_id)
            if info:
                print(f"\nИнформация о транзакции #{latest_tx_id}:")
                for key, value in info.items():
                    print(f"  {key}: {value}")
                
                # Обновленный баланс контракта
                new_balance = client.get_contract_usdt_balance()
                print(f"\nНовый USDT баланс контракта: {new_balance}")
        
    except Exception as e:
        print(f"Ошибка: {e}")


if __name__ == "__main__":
    main()