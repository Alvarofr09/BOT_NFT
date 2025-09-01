#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NFT Price Sync Bot (Drip.Trade -> LiquidLoot) A

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
    # Drip.Trade
    drip_base_url: str
    drip_api_key: Optional[str]
    # LiquidLoot
    ll_base_url: str
    ll_api_key: Optional[str]
    ll_wallet_address: Optional[str]

def load_config() -> Config:
    collections = [s.strip() for s in os.getenv("COLLECTION_SLUGS", "").split(",") if s.strip()]
    if not collections:
        raise SystemExit("Debes definir COLLECTION_SLUGS en el .env (lista separada por comas de slugs/ids de colección).")

    interval_sec = int(os.getenv("INTERVAL_SEC", "30"))
    margin_pct = float(os.getenv("MARGIN_PCT", "0.02"))
    strategy = os.getenv("STRATEGY", "undercut_floor")  # o 'above_top_bid'
    dry_run = os.getenv("DRY_RUN", "true").lower() in ("1", "true", "yes")

    drip_base_url = os.getenv("DRIP_BASE_URL", "").rstrip("/")
    drip_api_key = os.getenv("DRIP_API_KEY")  # opcional

    ll_base_url = os.getenv("LL_BASE_URL", "").rstrip("/")
    ll_api_key = os.getenv("LL_API_KEY")
    ll_wallet_address = os.getenv("LL_WALLET_ADDRESS")

    if not drip_base_url:
        raise SystemExit("Debes configurar DRIP_BASE_URL (endpoint público para stats por colección).")
    if not ll_base_url:
        raise SystemExit("Debes configurar LL_BASE_URL (endpoint REST para listar/actualizar listados en LiquidLoot).")

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

# ---------- Clientes de API (ajusta endpoints según docs de cada sitio) ----------

class DripClient:
    """
    Cliente para Drip.Trade
    Endpoint esperado (ejemplo): GET {DRIP_BASE_URL}/collections/{slug}/stats
    Debe devolver algo con 'floor' y 'topBid' en la misma divisa (p.ej. HYPE).
    """

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

        # buscar la colección por slug
        collection = next((c for c in data if c["slug"] == slug), None)
        if not collection:
            raise ValueError(f"No se encontró la colección '{slug}' en Drip API")

        # función para convertir el $bigint
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

    def get_floor_price(self, slug: str) -> Optional[float]:
        url = f"{self.base_url}/listings"
        resp = http_request("GET", url, headers=self._headers(), timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"LiquidLoot API {url} devolvió {resp.status_code}: {resp.text}")
        data = resp.json()

        listings = data.get("data", {}).get("listings", [])
        if not listings:
            return None

        prices = []
        for l in listings:
            for item in l.get("listing_consideration_items", []):
                if item.get("token_address") == "0x2fe0f0404431023d0ea86259e3fb6fadd8d78102de6e2f5aaac47be519184e1b":
                    price_wei = int(item["end_amount"])
                    price = price_wei / 1e18
                    prices.append(price)

        return min(prices) if prices else None


# ---------- Lógica de precios ----------

def compute_target_price(floor: float, top_bid: float, current_price: float, margin_pct: float, strategy: str) -> float:
    """
    Devuelve el precio objetivo para el listado en LiquidLoot.
    - 'undercut_floor': listar a (floor * (1 - margin)), pero nunca por debajo de (top_bid * (1 + 0.001)) para no vender por debajo del mejor bid + 0.1%
    - 'above_top_bid': listar a (top_bid * (1 + margin)); si eso queda por encima del floor actual de Drip, no pasa nada (es una estrategia conservadora).
    """
    if strategy == "above_top_bid":
        target = top_bid * (1.0 + margin_pct)
    else:
        target = floor * (1.0 - margin_pct)
        min_guard = top_bid * 1.001  # 0.1% por encima del top bid
        if target < min_guard:
            target = min_guard
    # Evita cambios minúsculos (<0.1%) para reducir churn
    if abs(target - current_price) / max(current_price, 1e-9) < 0.001:
        return current_price
    return round(target, 6)  # 6 decimales por seguridad

# ---------- Bot principal ----------

class PriceSyncBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.drip = DripClient(cfg.drip_base_url, cfg.drip_api_key)
        self.ll = LiquidLootClient(cfg.ll_base_url, cfg.ll_api_key, cfg.ll_wallet_address)

    def sync_collection(self, slug: str):
        drip_floor, drip_top_bid = self.drip.get_collection_stats(slug)
        loot_floor = self.ll.get_floor_price(slug)

        logger.info(f"[{slug}] DripTrade -> floor={drip_floor:.4f}, topBid={drip_top_bid:.4f}")
        logger.info(f"[{slug}] LiquidLoot -> floor={loot_floor:.4f}" if loot_floor else f"[{slug}] LiquidLoot -> sin datos")

        # Si solo quieres comparar, paramos aquí 👇
        return


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
                # Catch-all para evitar caídas del bot
                logger.error(f"Excepción no controlada en el loop principal:\n{traceback.format_exc()}")
                time.sleep(self.cfg.interval_sec)

if __name__ == "__main__":
    cfg = load_config()
    bot = PriceSyncBot(cfg)
    bot.run_forever()
