# TRON Escrow Web Interface

This folder contains the web interface files for the TRON Escrow System, designed to be deployed on GitHub Pages.

## Files

- **`index.html`** - Main landing page with system overview and links
- **`tronlink_interface.html`** - TronLink wallet integration interface for signing transactions
- **`README.md`** - This documentation file

## GitHub Pages Setup

These files are automatically served via GitHub Pages from the `docs/` folder.

**URL:** `https://goodelita1.github.io/tron-escrow-interface/docs/`

## Interface Features

### TronLink Integration Interface (`tronlink_interface.html`)

- ✅ **Enhanced Debugging**: Detailed console logs for troubleshooting transaction data
- ✅ **Fixed Method Display**: Properly shows contract method based on transaction type
- ✅ **Transaction Parsing**: Decodes base64 JSON data from URL parameters
- ✅ **Smart Contract Calls**: Supports `createTransaction` and `confirmDelivery` methods
- ✅ **Error Handling**: Comprehensive error messages and timeout protection

### Debug Features

The interface includes detailed logging to help diagnose issues:

- 🔍 **URL Parameter Parsing**: Logs raw and decoded transaction data
- 🔍 **Transaction Details**: Logs recipient, amount, deadline parameters
- 🔍 **Contract Call Parameters**: Logs all parameters before smart contract execution
- 🔍 **Type Validation**: Checks parameter types and validates recipient addresses

### Transaction Data Format

The interface expects transaction data in URL parameter `data` as base64-encoded JSON:

```javascript
{
    "type": "escrow_create",
    "contract": "CONTRACT_ADDRESS",
    "parameters": {
        "recipient": "RECIPIENT_TRON_ADDRESS",
        "amount": 1000000,  // Amount in USDT micro-units (6 decimals)
        "deadline": 1734567890  // Unix timestamp
    },
    "usdt_contract": "USDT_CONTRACT_ADDRESS",
    "usdt_amount": 1000000,
    "network": "shasta"
}
```

## Usage Flow

1. **Telegram Bot** generates transaction data and creates TronLink URL
2. **User clicks link** → opens `tronlink_interface.html` with encoded data
3. **Interface parses data** → displays transaction details
4. **User connects TronLink** → wallet connection established
5. **User confirms** → executes smart contract transaction

## Development

To test locally:

```bash
# Serve files locally
python -m http.server 8000
# Access: http://localhost:8000/tronlink_interface.html
```

## Browser Console

Open browser developer tools (F12) to view detailed debug logs when testing transactions.