const OptimizedTronEscrow = artifacts.require("OptimizedTronEscrow");

module.exports = function(deployer, network, accounts) {
  // USDT контракты для разных сетей
  const usdtContracts = {
    shasta: "TKZDdu947FtxWHLRKUXnhNZ6bar9RrZ7Wv", // USDT на Shasta testnet
    mainnet: "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", // USDT на TRON mainnet
    nile: "TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf" // USDT на Nile testnet
  };

  const usdtAddress = usdtContracts[network] || usdtContracts.shasta;

  console.log(`Deploying OptimizedTronEscrow on ${network} network:`);
  console.log(`USDT Contract: ${usdtAddress}`);
  console.log(`Platform Owner (also Arbitrator): будет установлен при деплое`);
  
  return deployer.deploy(
    OptimizedTronEscrow,
    usdtAddress,
    {
      // Убираем проблемные параметры gas и gasPrice
      feeLimit: 1000000000 // 1000 TRX в sun
    }
  ).then((instance) => {
    console.log(`✅ OptimizedTronEscrow deployed successfully!`);
    console.log(`Contract address: ${instance.address}`);
    return instance;
  });
};