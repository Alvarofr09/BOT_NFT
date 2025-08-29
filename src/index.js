import "dotenv/config";
import {ethers} from "ethers";
import PQueue from "p-queue";
import {
	getDripStats, 
	getLootMyListings, 
	patchLootListingPrice
} from "./api.js";
import { computeTargetPrice, shouldUpdatePrice } from "./logic.js";

const {
	RPC_URL,
	PRIVATE_KEY,
	RELAY_CONTRACT,
	COLLECTION_IDS,
	UNDERCUT_BPS = "200",
	POLL_MS = "30000",
	DRY_RUN
} = process.env;

if (!COLLECTION_IDS) {
  console.error("⚠️  Define COLLECTION_IDS en .env (coma-separated).");
  process.exit(1);
}

const collections = COLLECTION_IDS.split(",").map(s => s.trim()).filter(Boolean);
/*const provider = RPC_URL ? new ethers.JsonRpcProvider(RCP_URL) : null;
const wallet = (PRIVATE_KEY && provider) ? new ethers.wallet(PRIVATE_KEY, provider) : null;
*/
const RELAY_ABI = [
  "function pushSnapshot(bytes32 collectionId,uint256 floorWei,uint256 topBidWei,uint256 targetWei) external",
  "function paused() view returns (bool)"
];

//const relay = (RELAY_CONTRACT && wallet) ? new ethers.Contract(RELAY_CONTRACT, RELAY_ABI, wallet) : null;


// Control de concurrencia
const queue = new PQueue({concurrency: 3});

/*
async function processCollection(collectionId) {
	try {
		// 1) Leer Driptrade
		const stats = await getDripStats(collectionId);
		// Ajusta segun la respuest reañ: se esperan strings como "0.5"
		const floor = stats?.floorPrice ? String(stats.floorPrice) : null;
		const topBid = stats?.highestBid ? String(stats.highestBid) : null;

		console.log("floor", floor);
		console.log("Top Bid", topBid);

		// 2) Leer mis listinngs en LiquidLoot
		const myListings = await getLootMyListings(collectionId);
		console.log("Mi listings: ", myListings)
		if(!Array.isArray(myListings)) {
			console.warn("[WARN] response de listings no es array:", myListings);
		}

		// 3) Calcular target
		const target = computeTargetPrice({floor, topBid, undercutBps: Number(UNDERCUT_BPS) });

		// 4) aCTUALIZAR LISTINGS SEGUN NECESIDAD
		if (Array.isArray(myListings)) {
			for (const listing of myListings) {
				const listingId = listing.id ?? listing.listingId ?? listing.listing_id;
				const currentPrice = listing.price ?? listing.priceEth ?? null;
				if (!listingId) continue;

				if (shouldUpdatePrice(currentPrice, target)) {
					console.log(`[ACTION] &{collectionId} listing ${listingId}: ${currentPrice} -> ${target}`);
					if(!DRY_RUN) {
						await patchLootListingPrice(listingId, target);
					} else {
						console.log("[DRY_RUN No se envió PATCH].");
					}
				} else {
					console.log(`[SKIP] ${collectionId} listing ${listingId} se mantiene en ${currentPrice}`);
				}
			}
		}

		// 5) Push al contrato relay
		if (relay) {
			const paused = await relay.paused();
			if (!paused) {
				// convertimos a bytes32 y a wei
				const collectionKey = ethers.if(collectionId) //  Bytes32
				const floorWei = floor ? ethers.parseEther(String(floor)) : 0n;
				const topBidWei = topBid ? ethers.parseEther(String(topBid)) : 0n;
				const targetWei = target ? ethers.parseEther(String(target)) : 0n;
				
				if (!DRY_RUN) {
					const tx = await relay.pushSnapshot(collectionId, floorWei, topBidWei, targetWei);
					await tx.wait();
					console.log(`[RELAY] Snapshot enviado para ${collectionId}`);
				} else {
					console.log(`[DRY_RUN] No se envio snapshot al contrato`);
				}
			} else {
				console.log(`[RELAY] Relay pausado, no se envia snapshot.`)
			}
		}
	} catch (error) {
		console.error(`[ERR] ${collectionId}:`, err?.response?.data ?? err.message ?? err);
	}
}
*/

async function processCollectionTest(collectionId) {
  try {
    // 1) Leer Reservoir
    const stats = await getDripStats(collectionId);
    const floor = stats?.floorPrice ? String(stats.floorPrice) : null;
    const topBid = stats?.highestBid ? String(stats.highestBid) : null;

	console.log("Stats", stats);
    console.log(`Collection: ${collectionId}`);
    console.log("Floor price:", floor);
    console.log("Top Bid:", topBid);

    // 2) Leer mis listings en LiquidLoot
    const myListings = await getLootMyListings(collectionId);
    console.log("My listings:", myListings);

    // 3) Calcular target
    const target = computeTargetPrice({ floor, topBid, undercutBps: Number(UNDERCUT_BPS) });
    console.log("Target price:", target);

    // 4) Ignorar actualizaciones para pruebas
    console.log("[TEST MODE] No se actualizan listings ni se envía relay.");

  } catch (err) {
    console.error(`[ERR] ${collectionId}:`, err?.response?.data ?? err.message ?? err);
  }
}
async function mainLoop() {
	console.log("Bot iniciado. Colecciones:", collections.join(", "), "Intervalo:", POLL_MS, "ms");
	// Primer paso
	for (const col of collections) queue.add(() => processCollectionTest(col));

	setInterval(() => {
		for (const col of collections) queue.add(() => processCollectionTest(col));
	}, Number(POLL_MS));

	// Graceful shutdown
	process.on("SIGINT", () => {
		console.log("Cierre recibido (SIGINT). Esperando cola...");
		queue.onEmpty().then(() => process.exit(0));
	});
}

mainLoop().catch((e) => {
	console.error("Fallo fatal:", e);
	process.exit(1);
})