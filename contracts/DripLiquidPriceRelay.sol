// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract DripLiquidPriceRelay {
	address public owner;
	bool public paused;

	struct Snapshot {
		uint256 timestamp;
		uint256 floorWei;
		uint256 topBidWei;
		uint256 targetWei;
	}

	mapping(bytes32 => Snapshot) public lastSnapshot;

	event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);
	event Paused(bool paused);
	event SnapshotPushed(
		bytes32 indexed collectionId,
		uint256 floorWei,
		uint256 topBidWei,
		uint256 targetWei,
		uint256 timestamp
	);

	modifier onlyOwner() {
		require(msg.sender == owner, "You are not the owner");
		_;
	}

	constructor () {
		owner = msg.sender;
	}

	function transferOwnership(address newOwner) external onlyOwner {
		require(newOwner != address(0), "Zero address");
		emit OwnershipTransferred(owner, newOwner);
		owner = newOwner;
	}

	function setState(bool _paused) external onlyOwner {
		paused = _paused;
		emit Paused(_paused);
	}

	function pushSnapshot(
		bytes32 _collectionId,
		uint256 _floorWei,
		uint256 _topBidWei,
		uint256 _targetWei
	) external onlyOwner {
		require(!paused, "The bot is paused");
		lastSnapshot[_collectionId] = Snapshot({
			timestamp: block.timestamp,
			floorWei: _floorWei,
			topBidWei: _topBidWei,
			targetWei: _targetWei
		});

		emit SnapshotPushed(_collectionId, _floorWei, _topBidWei, _targetWei, block.timestamp);
	}
}