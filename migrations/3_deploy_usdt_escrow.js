const TronEscrowUSDT = artifacts.require("TronEscrowUSDT");

module.exports = function(deployer, network, accounts) {
    // USDT contract addresses for different networks
    const usdtAddresses = {
        mainnet: "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",  // USDT on mainnet
        shasta: "TKZDdu947FtxWHLRKUXnhNZ6bar9RrZ7Wv",   // Example testnet USDT (you may need to find the actual one)
        nile: "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"      // Example Nile testnet USDT
    };
    
    // Global arbitrator addresses for different networks
    // You can change these to your preferred arbitrator addresses
    const arbitratorAddresses = {
        mainnet: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2",  // Your mainnet arbitrator
        shasta: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2",   // Your testnet arbitrator 
        nile: "TBohEWSnePeDFd7k3wn3gKdcP8eTv1vzv2"      // Your nile arbitrator
    };
    
    // Get USDT address and arbitrator for current network
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
        // Default to Shasta testnet address
        usdtAddress = usdtAddresses.shasta;
        arbitratorAddress = arbitratorAddresses.shasta;
    }
    
    console.log(`Deploying TronEscrowUSDT to ${network}`);
    console.log(`USDT address: ${usdtAddress}`);
    console.log(`Arbitrator address: ${arbitratorAddress}`);
    
    deployer.deploy(TronEscrowUSDT, usdtAddress, arbitratorAddress);
};