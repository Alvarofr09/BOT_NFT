const { solidity, network } = require("hardhat");

require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

module.exports = {
	solidity: "0.8.20",
	networks: {
		localhost : {
			url: "https://127.0.0.1_8545"
		},
		sepolia: {
			url: process.env.RCP_URL || "",
			accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : []
		}
	}
}