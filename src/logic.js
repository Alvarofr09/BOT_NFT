/** 
 * undercutBps: p.ej. 200 -> 2%
 * floor/topBid: strings o numeros (en unidades de ETH / SOL, no wei)
*/

export function computeTargetPrice({floor, topBid, undercutBps= 200, minTick = null}) {
	const f = floor ? Number(floor) : Number.POSITIVE_INFINITY;
	const b = topBid ? Number(topBid) : Number.POSITIVE_INFINITY;
	const ref = Math.min(f, b);
	if (!isFinite(ref)) return null;
	let target = ref * (1 - undercutBps / 10000);
	if (minTick && minTick > 0) {
		target = Math.floor(target / minTick) * minTick;
	}
	// Evita negativos
	if (target <= 0) return null;
	return Number(target);
}

export function shouldUpdatePrice(currentPrice, targetPrice, epsilon = 1e-12) {
	if (targetPrice == null) return false;
	if (currentPrice == null) return false;
	return Number(currentPrice) - Number(targetPrice) > epsilon;
}