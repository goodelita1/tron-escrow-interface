// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19; // Используем последнюю стабильную версию

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract OptimizedTronEscrow {
    // Упаковываем enum в uint8 для экономии газа
    uint8 constant AWAITING_DELIVERY = 0;
    uint8 constant COMPLETE = 1;
    uint8 constant DISPUTED = 2;
    uint8 constant REFUNDED = 3;
    
    // Упаковываем структуру для минимизации storage slots
    struct EscrowTransaction {
        address sender;           // 20 bytes
        address recipient;        // 20 bytes  
        uint96 amount;           // 12 bytes - достаточно для USDT сумм
        uint32 createdAt;        // 4 bytes - timestamp создания
        uint8 state;             // 1 byte
        uint8 flags;             // 1 byte для битовых флагов
        // Общий размер: 64 bytes = 2 storage slots
    }
    
    // Битовые маски для flags
    uint8 constant SENDER_APPROVED = 1;
    uint8 constant RECIPIENT_APPROVED = 2;
    uint8 constant ARBITRATOR_VOTED = 4;
    uint8 constant ARBITRATOR_DECISION = 8;
    
    mapping(uint256 => EscrowTransaction) public transactions;
    uint256 public transactionCount;
    
    // Используем immutable для переменных, которые устанавливаются только в конструкторе
    uint96 public immutable PLATFORM_FEE = 5_000_000; // 5 USDT
    uint32 public immutable DEADLINE_HOURS = 24 hours; // Фиксированный дедлайн 24 часа
    address public immutable PLATFORM_OWNER; // Также является арбитром
    IERC20 public immutable USDT_TOKEN;
    
    address public globalArbitrator;
    
    // Оптимизированные события (индексируем только то, что нужно для поиска)
    event TransactionCreated(uint256 indexed transactionId, address indexed sender, uint256 amount);
    event FundsReleased(uint256 indexed transactionId, address indexed to);
    event DisputeRaised(uint256 indexed transactionId);
    event DisputeResolved(uint256 indexed transactionId, bool releaseToRecipient);
    
    error Unauthorized();
    error InvalidState();
    error InvalidAmount();
    error InvalidAddress();
    error DeadlineNotPassed();
    error TransferFailed();
    
    constructor(address _usdtTokenAddress) {
        PLATFORM_OWNER = msg.sender; // Владелец также является арбитром
        USDT_TOKEN = IERC20(_usdtTokenAddress);
    }
    
    // Создание транзакции с минимальными проверками
    function createTransaction(
        address _recipient,
        uint96 _amount
    ) external returns (uint256) {
        // Группируем проверки для экономии газа
        if (_amount <= PLATFORM_FEE || _recipient == address(0) || _recipient == msg.sender) {
            revert InvalidAmount();
        }
        
        // Переводим USDT одной операцией
        if (!USDT_TOKEN.transferFrom(msg.sender, address(this), _amount)) {
            revert TransferFailed();
        }
        
        uint256 transactionId = transactionCount++;
        
        // Записываем в storage одной операцией
        transactions[transactionId] = EscrowTransaction({
            sender: msg.sender,
            recipient: _recipient,
            amount: _amount,
            createdAt: uint32(block.timestamp),
            state: AWAITING_DELIVERY,
            flags: 0
        });
        
        emit TransactionCreated(transactionId, msg.sender, _amount);
        
        return transactionId;
    }
    
    // Оптимизированное подтверждение доставки
    function confirmDelivery(uint256 _transactionId) external {
        EscrowTransaction storage txn = transactions[_transactionId];
        
        if (msg.sender != txn.recipient || txn.state != AWAITING_DELIVERY) {
            revert Unauthorized();
        }
        
        // Устанавливаем флаг и сразу освобождаем средства
        txn.flags |= RECIPIENT_APPROVED;
        _releaseFunds(_transactionId, txn);
    }
    
    // Подтверждение отправителем
    function approveFundsRelease(uint256 _transactionId) external {
        EscrowTransaction storage txn = transactions[_transactionId];
        
        if (msg.sender != txn.sender || txn.state != AWAITING_DELIVERY) {
            revert Unauthorized();
        }
        
        txn.flags |= SENDER_APPROVED;
        
        // Если получатель тоже подтвердил, освобождаем средства
        if (txn.flags & RECIPIENT_APPROVED != 0) {
            _releaseFunds(_transactionId, txn);
        }
    }
    
    // Поднятие спора
    function raiseDispute(uint256 _transactionId) external {
        EscrowTransaction storage txn = transactions[_transactionId];
        
        if ((msg.sender != txn.sender && msg.sender != txn.recipient) 
            || txn.state != AWAITING_DELIVERY) {
            revert Unauthorized();
        }
        
        txn.state = DISPUTED;
        emit DisputeRaised(_transactionId);
    }
    
    // Решение арбитра (владелец платформы)
    function resolveDispute(uint256 _transactionId, bool _releaseToRecipient) external {
        EscrowTransaction storage txn = transactions[_transactionId];
        
        if (msg.sender != PLATFORM_OWNER || txn.state != DISPUTED) {
            revert Unauthorized();
        }
        
        txn.flags |= ARBITRATOR_VOTED;
        if (_releaseToRecipient) {
            txn.flags |= ARBITRATOR_DECISION;
        }
        
        emit DisputeResolved(_transactionId, _releaseToRecipient);
        
        if (_releaseToRecipient) {
            _releaseFunds(_transactionId, txn);
        } else {
            _refundSender(_transactionId, txn);
        }
    }
    
    // Возврат после дедлайна (24 часа)
    function claimRefundAfterDeadline(uint256 _transactionId) external {
        EscrowTransaction storage txn = transactions[_transactionId];
        
        if (msg.sender != txn.sender || txn.state != AWAITING_DELIVERY || 
            block.timestamp <= txn.createdAt + DEADLINE_HOURS) {
            revert DeadlineNotPassed();
        }
        
        _refundSender(_transactionId, txn);
    }
    
    // Оптимизированное освобождение средств
    function _releaseFunds(uint256 _transactionId, EscrowTransaction storage txn) internal {
        txn.state = COMPLETE;
        
        uint96 recipientAmount = txn.amount - PLATFORM_FEE;
        
        // Batch transfers для экономии газа
        if (!USDT_TOKEN.transfer(PLATFORM_OWNER, PLATFORM_FEE) || 
            !USDT_TOKEN.transfer(txn.recipient, recipientAmount)) {
            revert TransferFailed();
        }
        
        emit FundsReleased(_transactionId, txn.recipient);
    }
    
    // Оптимизированный возврат средств
    function _refundSender(uint256 _transactionId, EscrowTransaction storage txn) internal {
        txn.state = REFUNDED;
        
        uint96 refundAmount = txn.amount - PLATFORM_FEE;
        
        if (!USDT_TOKEN.transfer(PLATFORM_OWNER, PLATFORM_FEE) || 
            !USDT_TOKEN.transfer(txn.sender, refundAmount)) {
            revert TransferFailed();
        }
        
        emit FundsReleased(_transactionId, txn.sender);
    }
    
    // View функции с минимальной обработкой
    function getTransaction(uint256 _transactionId) external view returns (
        address sender,
        address recipient,
        uint96 amount,
        uint8 state,
        uint32 createdAt,
        uint8 flags
    ) {
        EscrowTransaction storage txn = transactions[_transactionId];
        return (txn.sender, txn.recipient, txn.amount, txn.state, txn.createdAt, txn.flags);
    }
    
    // Проверка, истек ли дедлайн для транзакции
    function isDeadlinePassed(uint256 _transactionId) external view returns (bool) {
        return block.timestamp > transactions[_transactionId].createdAt + DEADLINE_HOURS;
    }
}