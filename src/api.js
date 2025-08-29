import axios from "axios";
import pRetry from "p-retry";

const buildClient = (baseURL, apiKey) => {
	const client = axios.create({
		baseURL,
		timeout: 10000,
		headers: apiKey ? {Authorization: `Bearer ${apikey}`} : {}
	});

	const call = async (config) => 
		pRetry(
			async () => {
				try {
					
				} catch (err) {
					const status = err.response?.status;
					// No reintentar en errores de clientes comunes
					if (status && [400, 401, 403, 404].includes(status)) {
						throw new pRetry.AbortError(err);
					}
					throw err;
				}
			},
			{retries: 5, factor: 2, minTimeout: 500, maxTimeout: 500}
		);
	
	return { call };
}

export const drip = buildClient(process.env.DRIPTRADE_BASE, process.env.DRIPTRADE_KEY);
export const loot = buildClient(process.env.LIQUIDLOOT_BASE, process.env.LIQUIDLOOT_KEY);

/**
 * Ajusta estas funciones al JSON Real que devuelven las APIs de Driptrade / Lquidloot
 * Ejemplo placeholders:
 */
/*export async function getDripStats(collectionId) {
	// Ej: GET /collections/{id}/stats -> { floorPrice: "0.5", highestBid: "0.45" }
	return drip.call({
		method: "GET",
		url: `/collection/${collectionId}/stats`
	});
}*/

export async function getDripStats(collectionId) {
  const res = await drip.call({
    method: "GET",
    url: "/collections/v5",
    params: { id: collectionId } // collectionId = dirección del contrato
  });

  console.log("Response", res)

  const collection = res?.collections?.[0] ?? {};
  return {
    floorPrice: collection?.floorAsk?.price?.amount?.decimal ?? null,
    highestBid: collection?.topBid?.price?.amount?.decimal ?? null
  };
}

export async function getLootMyListings(collectionId) {
	// Ej: GET /me/listings?collection={id} -> [{ id: "123", price: "0.6" }, ...]
	return loot.call({
		method: "GET",
		url: `me/listings`,
		params: {
			collection: collectionId
		}
	});
}

export async function patchLootListingPrice(listingId, newPrice) {
	// Ej: PATCH /listings/{id} body { price: "0.59" }
	return localStorage.call({
		method: "PATCH",
		url: `/listings/${listingId}`,
		data: {
			price: String(newPrice)
		}
	})
}