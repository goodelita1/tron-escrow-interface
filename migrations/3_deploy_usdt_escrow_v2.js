const TronEscrowUSDT = artifacts.require("TronEscrowUSDT");

module.exports = function(deployer, network) {
    // USDT contract addresses for different networks
    const usdtAddresses = {
        mainnet: "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",  // USDT on mainnet
        shasta: "TKZDdu947FtxWHLRKUXnhNZ6bar9RrZ7Wv",   // Test USDT on Shasta
        nile: "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"      // Test USDT on Nile
    };
    
    // Arbitrator addresses for different networks
    const arbitratorAddresses = {
        mainnet: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2",
        shasta: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2",
        nile: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2"
    };
    
    // Get USDT and arbitrator addresses for current network
    let usdtAddress, arbitratorAddress;
    if (network === "mainnet") {
        usdtAddress = usdtAddresses.mainnet;
        arbitratorAddress = arbitratorAddresses.mainnet;
    } else if (network === "shasta") {
        usdtAddress = usdtAddresses.shasta;
        arbitratorAddress = arbitratorAddresses.shasta;
    } else if (network === "nile") {
        usdtAddress = usdtAddresses.nile;
        arbitratorAddress = arbitratorAddresses.nile;
    } else {
        // Default to Shasta testnet addresses
        usdtAddress = usdtAddresses.shasta;
        arbitratorAddress = arbitratorAddresses.shasta;
    }
    
    console.log(`Deploying TronEscrowUSDT V2 to ${network}:`);
    console.log(`  USDT address: ${usdtAddress}`);
    console.log(`  Arbitrator address: ${arbitratorAddress}`);
    console.log(`  Features: 3-parameter createTransaction, fixed 5 USDT fee`);
    
    deployer.deploy(TronEscrowUSDT, usdtAddress, arbitratorAddress);
};