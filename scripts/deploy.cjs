const hre = require("hardhat");

async function main() {
	const Relay = await hre.ethers.getContactFactory("DripLiquidPriceRelay");
	const relay = await Relay.deploy();
	await relay.deployed();
	console.log("Relay deplyed to:", relay.address);
}

main().catch((err) => {
	console.error(err);
	process.exitCode = 1;
});