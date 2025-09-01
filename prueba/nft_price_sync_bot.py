#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NFT Price Sync Bot (Drip.Trade -> LiquidLoot)

Objetivo:
- Leer floor price y top bid de colecciones en Drip.Trade
- Comparar con tus listados en LiquidLoot
- Actualizar automáticamente los precios en LiquidLoot para ser 2% más competitivos
- Ejecutar comprobaciones cada 30 segundos
- Manejo de errores robusto (reintentos, timeouts, logs) para evitar caídas

⚠️ Nota importante:
Las APIs públicas para Drip.Trade y LiquidLoot pueden cambiar y/o requerir autenticación o firmas on‑chain.
Este script incluye endpoints configurables y una política de precios editable.
Rellena las URLs/headers concretos según la documentación/soporte de cada marketplace.

Requisitos (pip):
  pip install python-dotenv requests

Uso:
  1) Copia .env.example a .env y rellena valores.
  2) python nft_price_sync_bot.py
"""

import os
import time
import json
import logging
import traceback
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from dotenv import load_dotenv
import requests

# ---------- Config & Logging ----------

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("nft-sync-bot")

@dataclass
class Config:
    collections: List[str]
    interval_sec: int
    margin_pct: float
    strategy: str  # 'undercut_floor' o 'above_top_bid'
    dry_run: bool
    drip_base_url: str
    drip_api_key: Optional[str]
    ll_base_url: str
    ll_api_key: Optional[str]
    ll_wallet_address: Optional[str]

def load_config() -> Config:
    collections = [s.strip() for s in os.getenv("COLLECTION_SLUGS", "").split(",") if s.strip()]
    if not collections:
        raise SystemExit("Debes definir COLLECTION_SLUGS en el .env (lista separada por comas de slugs/ids de colección).")

    interval_sec = int(os.getenv("INTERVAL_SEC", "30"))
    margin_pct = float(os.getenv("MARGIN_PCT", "0.02"))
    strategy = os.getenv("STRATEGY", "undercut_floor")
    dry_run = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

    drip_base_url = os.getenv("DRIP_BASE_URL", "").rstrip("/")
    drip_api_key = os.getenv("DRIP_API_KEY")

    ll_base_url = os.getenv("LL_BASE_URL", "").rstrip("/")
    ll_api_key = os.getenv("LL_API_KEY")
    ll_wallet_address = os.getenv("LL_WALLET_ADDRESS")

    if not drip_base_url or not ll_base_url:
        raise SystemExit("Debes configurar DRIP_BASE_URL y LL_BASE_URL en el .env")

    return Config(
        collections=collections,
        interval_sec=interval_sec,
        margin_pct=margin_pct,
        strategy=strategy,
        dry_run=dry_run,
        drip_base_url=drip_base_url,
        drip_api_key=drip_api_key,
        ll_base_url=ll_base_url,
        ll_api_key=ll_api_key,
        ll_wallet_address=ll_wallet_address,
    )

# ---------- HTTP util con reintentos simples ----------

def http_request(method: str, url: str, *, headers: Dict[str, str] = None, params=None, json_body=None, timeout=10, retries=3, backoff=1.5):
    headers = headers or {}
    for attempt in range(1, retries + 1):
        try:
            resp = requests.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error", response=resp)
            return resp
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            if attempt == retries:
                raise
            sleep_s = backoff ** attempt
            logger.warning(f"HTTP fallo ({e}); reintentando en {sleep_s:.1f}s ({attempt}/{retries})...")
            time.sleep(sleep_s)

# ---------- Clientes de API ----------

class DripClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def get_collection_stats(self, slug: str) -> Tuple[float, float]:
        url = f"{self.base_url}/collections"
        resp = http_request("GET", url, headers=self._headers(), timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Drip API {url} devolvió {resp.status_code}: {resp.text}")
        data = resp.json()["collections"]

        collection = next((c for c in data if c["slug"] == slug), None)
        if not collection:
            raise ValueError(f"No se encontró la colección '{slug}' en Drip API")

        def parse_bigint(val: str) -> float:
            return int(val.replace("$bigint", "")) / 1e18

        floor = parse_bigint(collection["floorPrice"])
        top_bid = parse_bigint(collection["topBid"])
        return floor, top_bid

class LiquidLootClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, wallet: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.wallet = wallet

    def _headers(self) -> Dict[str, str]:
        return {"Accept": "application/json"}

    def get_my_listings(self, slug: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/listings"
        params = {}
        if self.wallet:
            params["offerer_address"] = self.wallet

        resp = http_request("GET", url, headers=self._headers(), params=params, timeout=10)
        data = resp.json()
        listings = data.get("data", {}).get("listings", [])

        if listings:
            return listings

        all_listings = data.get("data", {}).get("listings", [])
        if not all_listings:
            return []
        example = all_listings[0]
        print(f"⚠️ No hay listings en tu wallet. Usando ejemplo: {example['id']}")
        return [example]

    def get_floor_and_topbid(self, slug: str) -> Tuple[Optional[float], Optional[float]]:
        listings = self.get_my_listings(slug)
        if not listings:
            return None, None

        prices = []
        for l in listings:
            for item in l.get("listing_consideration_items", []):
                if item.get("token_address") == "0x0000000000000000000000000000000000000000":
                    price_wei = int(item["end_amount"])
                    prices.append(price_wei / 1e18)

        if not prices:
            return None, None

        floor = min(prices)
        top_bid = max(prices)
        return floor, top_bid

# ---------- Lógica de precios ----------

def compute_target_price(floor: float, top_bid: float, current_price: float, margin_pct: float, strategy: str) -> float:
    if strategy == "above_top_bid":
        target = top_bid * (1.0 + margin_pct)
    else:
        target = floor * (1.0 - margin_pct)
        min_guard = top_bid * 1.001
        if target < min_guard:
            target = min_guard
    if abs(target - current_price) / max(current_price, 1e-9) < 0.001:
        return current_price
    return round(target, 6)

# ---------- Bot principal ----------

class PriceSyncBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.drip = DripClient(cfg.drip_base_url, cfg.drip_api_key)
        self.ll = LiquidLootClient(cfg.ll_base_url, cfg.ll_api_key, cfg.ll_wallet_address)

    def sync_collection(self, slug: str):
        drip_floor, drip_top_bid = self.drip.get_collection_stats(slug)
        logger.info(f"[{slug}] DripTrade -> floor={drip_floor:.4f}, topBid={drip_top_bid:.4f}")

        loot_floor, loot_top_bid = self.ll.get_floor_and_topbid(slug)
        if loot_floor is None:
            logger.info(f"[{slug}] LiquidLoot -> sin datos (no hay listings activos)")
        else:
            logger.info(f"[{slug}] LiquidLoot -> floor={loot_floor:.4f}, topBid={loot_top_bid:.4f}")
            diff_floor = loot_floor - drip_floor
            diff_topbid = loot_top_bid - drip_top_bid
            logger.info(f"[{slug}] Diferencia floor: {diff_floor:.4f}, Diferencia topBid: {diff_topbid:.4f}")

        if self.cfg.dry_run:
            logger.info(f"[{slug}] Dry-run: no se actualizan listings")

    def run_forever(self):
        logger.info("Iniciando PriceSyncBot... (Ctrl+C para salir)")
        while True:
            start = time.time()
            try:
                for slug in self.cfg.collections:
                    try:
                        self.sync_collection(slug)
                    except Exception:
                        logger.error(f"Error en colección '{slug}':\n{traceback.format_exc()}")
                elapsed = time.time() - start
                sleep_s = max(0, self.cfg.interval_sec - elapsed)
                time.sleep(sleep_s)
            except KeyboardInterrupt:
                logger.info("Interrumpido por el usuario. Saliendo.")
                break
            except Exception:
                logger.error(f"Excepción no controlada en el loop principal:\n{traceback.format_exc()}")
                time.sleep(self.cfg.interval_sec)

# ---------- Entry point ----------

if __name__ == "__main__":
    cfg = load_config()
    bot = PriceSyncBot(cfg)
    bot.run_forever()
