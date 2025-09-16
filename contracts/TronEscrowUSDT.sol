// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

// Interface для USDT TRC-20 токена
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

contract TronEscrowUSDT {
    enum State { AWAITING_PAYMENT, AWAITING_DELIVERY, COMPLETE, DISPUTED, REFUNDED }
    
    struct EscrowTransaction {
        address payable sender;
        address payable recipient;
        uint256 amount;
        State state;
        uint256 createdAt;
        uint256 deadline;
        bool senderApproved;
        bool recipientApproved;
        bool arbitratorDecision; // true = release to recipient, false = refund to sender
        bool arbitratorVoted;
    }
    
    mapping(uint256 => EscrowTransaction) public transactions;
    uint256 public transactionCount;
    
    // Фиксированная комиссия платформы - 5 USDT (в микроединицах)
    uint256 public platformFeeFixed = 5_000_000; // 5 USDT (6 знаков после запятой)
    
    address payable public platformOwner;
    address public globalArbitrator;
    
    // USDT контракт на TRON (mainnet: TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t)
    // Для testnet используйте другой адрес
    IERC20 public usdtToken;
    
    event TransactionCreated(uint256 indexed transactionId, address indexed sender, address indexed recipient, uint256 amount);
    event PaymentDeposited(uint256 indexed transactionId, uint256 amount);
    event DeliveryConfirmed(uint256 indexed transactionId);
    event DisputeRaised(uint256 indexed transactionId, address indexed raisedBy);
    event DisputeResolved(uint256 indexed transactionId, bool releaseToRecipient);
    event FundsReleased(uint256 indexed transactionId, address indexed to, uint256 amount);
    event TransactionRefunded(uint256 indexed transactionId, uint256 amount);
    
    modifier onlyParties(uint256 _transactionId) {
        EscrowTransaction storage txn = transactions[_transactionId];
        require(
            msg.sender == txn.sender || 
            msg.sender == txn.recipient || 
            msg.sender == globalArbitrator,
            "Only transaction parties allowed"
        );
        _;
    }
    
    modifier onlyArbitrator(uint256 _transactionId) {
        require(msg.sender == globalArbitrator, "Only arbitrator allowed");
        _;
    }
    
    modifier onlySender(uint256 _transactionId) {
        require(msg.sender == transactions[_transactionId].sender, "Only sender allowed");
        _;
    }
    
    modifier onlyRecipient(uint256 _transactionId) {
        require(msg.sender == transactions[_transactionId].recipient, "Only recipient allowed");
        _;
    }
    
    modifier inState(uint256 _transactionId, State _state) {
        require(transactions[_transactionId].state == _state, "Invalid state");
        _;
    }
    
    constructor(address _usdtTokenAddress, address _globalArbitrator) {
        platformOwner = payable(msg.sender);
        globalArbitrator = _globalArbitrator;
        usdtToken = IERC20(_usdtTokenAddress);
    }
    
    // Создание новой транзакции ESCROW с USDT
    function createTransaction(
        address payable _recipient,
        uint256 _amount, // Количество USDT (в микроединицах - 6 знаков после запятой)
        uint256 _deadline // timestamp когда истекает срок
    ) external returns (uint256) {
        require(_amount > platformFeeFixed, "Amount must be greater than platform fee (5 USDT)");
        require(_recipient != address(0), "Invalid recipient address");
        require(_recipient != msg.sender, "Sender and recipient cannot be the same");
        require(_deadline > block.timestamp, "Deadline must be in the future");
        
        // Проверяем, что у отправителя достаточно USDT и он дал разрешение
        require(usdtToken.balanceOf(msg.sender) >= _amount, "Insufficient USDT balance");
        require(usdtToken.allowance(msg.sender, address(this)) >= _amount, "Insufficient USDT allowance");
        
        // Переводим USDT на контракт
        require(usdtToken.transferFrom(msg.sender, address(this), _amount), "USDT transfer failed");
        
        uint256 transactionId = transactionCount++;
        
        transactions[transactionId] = EscrowTransaction({
            sender: payable(msg.sender),
            recipient: _recipient,
            amount: _amount,
            state: State.AWAITING_DELIVERY,
            createdAt: block.timestamp,
            deadline: _deadline,
            senderApproved: false,
            recipientApproved: false,
            arbitratorDecision: false,
            arbitratorVoted: false
        });
        
        emit TransactionCreated(transactionId, msg.sender, _recipient, _amount);
        emit PaymentDeposited(transactionId, _amount);
        
        return transactionId;
    }
    
    // Подтверждение получения товара/услуги получателем
    function confirmDelivery(uint256 _transactionId) 
        external 
        onlyRecipient(_transactionId) 
        inState(_transactionId, State.AWAITING_DELIVERY) 
    {
        transactions[_transactionId].recipientApproved = true;
        emit DeliveryConfirmed(_transactionId);
        
        // Автоматически освобождаем средства если получатель подтвердил
        _releaseFunds(_transactionId);
    }
    
    // Подтверждение отправителем что можно освободить средства
    function approveFundsRelease(uint256 _transactionId) 
        external 
        onlySender(_transactionId) 
        inState(_transactionId, State.AWAITING_DELIVERY) 
    {
        transactions[_transactionId].senderApproved = true;
        
        // Если обе стороны согласны, освобождаем средства
        if (transactions[_transactionId].recipientApproved) {
            _releaseFunds(_transactionId);
        }
    }
    
    // Поднятие спора любой из сторон
    function raiseDispute(uint256 _transactionId) 
        external 
        onlyParties(_transactionId) 
        inState(_transactionId, State.AWAITING_DELIVERY) 
    {
        transactions[_transactionId].state = State.DISPUTED;
        emit DisputeRaised(_transactionId, msg.sender);
    }
    
    // Решение арбитра по спору
    function resolveDispute(uint256 _transactionId, bool _releaseToRecipient) 
        external 
        onlyArbitrator(_transactionId) 
        inState(_transactionId, State.DISPUTED) 
    {
        EscrowTransaction storage txn = transactions[_transactionId];
        txn.arbitratorDecision = _releaseToRecipient;
        txn.arbitratorVoted = true;
        
        emit DisputeResolved(_transactionId, _releaseToRecipient);
        
        if (_releaseToRecipient) {
            _releaseFunds(_transactionId);
        } else {
            _refundSender(_transactionId);
        }
    }
    
    // Автоматический возврат средств после истечения дедлайна
    function claimRefundAfterDeadline(uint256 _transactionId) 
        external 
        onlySender(_transactionId) 
        inState(_transactionId, State.AWAITING_DELIVERY) 
    {
        require(block.timestamp > transactions[_transactionId].deadline, "Deadline not passed");
        _refundSender(_transactionId);
    }
    
    // Внутренняя функция освобождения средств получателю
    function _releaseFunds(uint256 _transactionId) internal {
        EscrowTransaction storage txn = transactions[_transactionId];
        txn.state = State.COMPLETE;
        
        uint256 totalAmount = txn.amount;
        
        // Фиксированная платформенная комиссия - 5 USDT
        require(usdtToken.transfer(platformOwner, platformFeeFixed), "Platform fee transfer failed");
        
        // Остаток получателю (сумма минус 5 USDT комиссия)
        uint256 recipientAmount = totalAmount - platformFeeFixed;
        require(usdtToken.transfer(txn.recipient, recipientAmount), "Recipient transfer failed");
        
        emit FundsReleased(_transactionId, txn.recipient, recipientAmount);
    }
    
    // Внутренняя функция возврата средств отправителю
    function _refundSender(uint256 _transactionId) internal {
        EscrowTransaction storage txn = transactions[_transactionId];
        txn.state = State.REFUNDED;
        
        uint256 totalAmount = txn.amount;
        
        // При возврате комиссию все равно берем (за обработку сделки)
        require(usdtToken.transfer(platformOwner, platformFeeFixed), "Platform fee transfer failed");
        
        // Остаток отправителю (сумма минус 5 USDT комиссия)
        uint256 refundAmount = totalAmount - platformFeeFixed;
        require(usdtToken.transfer(txn.sender, refundAmount), "Refund transfer failed");
        
        emit TransactionRefunded(_transactionId, refundAmount);
    }
    
    // Получение информации о транзакции
    function getTransaction(uint256 _transactionId) 
        external 
        view 
        returns (
            address sender,
            address recipient,
            uint256 amount,
            State state,
            uint256 createdAt,
            uint256 deadline,
            bool senderApproved,
            bool recipientApproved
        ) 
    {
        EscrowTransaction storage txn = transactions[_transactionId];
        return (
            txn.sender,
            txn.recipient,
            txn.amount,
            txn.state,
            txn.createdAt,
            txn.deadline,
            txn.senderApproved,
            txn.recipientApproved
        );
    }
    
    // Получение баланса USDT контракта
    function getContractUSDTBalance() external view returns (uint256) {
        return usdtToken.balanceOf(address(this));
    }
    
    // Получение адреса USDT токена
    function getUSDTTokenAddress() external view returns (address) {
        return address(usdtToken);
    }
    
    // Функции для владельца платформы
    function updatePlatformFeeFixed(uint256 _newFeeFixed) external {
        require(msg.sender == platformOwner, "Only platform owner");
        require(_newFeeFixed <= 50_000_000, "Fee too high"); // максимум 50 USDT
        require(_newFeeFixed >= 1_000_000, "Fee too low"); // минимум 1 USDT
        platformFeeFixed = _newFeeFixed;
    }
    
    // Обновление адреса USDT токена (на случай миграции)
    function updateUSDTTokenAddress(address _newUSDTAddress) external {
        require(msg.sender == platformOwner, "Only platform owner");
        usdtToken = IERC20(_newUSDTAddress);
    }
    
    // Обновление глобального арбитра
    function updateGlobalArbitrator(address _newArbitrator) external {
        require(msg.sender == platformOwner, "Only platform owner");
        require(_newArbitrator != address(0), "Invalid arbitrator address");
        globalArbitrator = _newArbitrator;
    }
    
    // Получить текущую фиксированную комиссию в USDT
    function getPlatformFeeInUSDT() external view returns (uint256) {
        return platformFeeFixed / 1_000_000; // Переводим из микроединиц в USDT
    }
    
    // Аварийная функция для вывода средств (только владелец)
    function emergencyWithdraw(uint256 _transactionId) external {
        require(msg.sender == platformOwner, "Only platform owner");
        EscrowTransaction storage txn = transactions[_transactionId];
        require(
            block.timestamp > txn.deadline + 30 days, 
            "Emergency withdrawal too early"
        );
        
        txn.state = State.REFUNDED;
        // При аварийном выводе возвращаем полную сумму без комиссии
        require(usdtToken.transfer(txn.sender, txn.amount), "Emergency refund failed");
    }
    
    // Аварийная функция для вывода всех USDT с контракта (только владелец)
    function emergencyWithdrawAll() external {
        require(msg.sender == platformOwner, "Only platform owner");
        uint256 balance = usdtToken.balanceOf(address(this));
        require(usdtToken.transfer(platformOwner, balance), "Emergency withdrawal failed");
    }
}