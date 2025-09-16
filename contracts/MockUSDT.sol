// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
contract MockUSDT is ERC20 {
    constructor(uint256 initialSupply) ERC20("Tether USD", "USDT") {
        _mint(msg.sender, initialSupply);
    }

    // Override decimals to 6 (USDT uses 6 decimals)
    function decimals() public pure override returns (uint8) {
        return 6;
    }
}
