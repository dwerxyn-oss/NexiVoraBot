"""Клиент Crypto Pay (@CryptoBot / @send): https://pay.crypt.bot/api/"""

import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger("novamarket.cryptopay")


class CryptoPayError(Exception):
    pass


class CryptoPayClient:
    def __init__(self, api_token: str, *, testnet: bool = False) -> None:
        self._token = api_token.strip()
        host = "testnet-pay.crypt.bot" if testnet else "pay.crypt.bot"
        self._base = f"https://{host}/api"

    async def _call(self, method: str, *, json_body: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        if not self._token:
            raise CryptoPayError("Пустой CRYPTO_PAY_API_TOKEN")
        url = f"{self._base}/{method}"
        headers = {"Crypto-Pay-API-Token": self._token}
        async with httpx.AsyncClient(timeout=45.0) as client:
            if json_body is not None:
                r = await client.post(url, headers=headers, json=json_body)
            else:
                r = await client.get(url, headers=headers, params=params or {})
        try:
            data = r.json()
        except Exception as e:
            raise CryptoPayError(f"Некорректный ответ HTTP {r.status_code}: {r.text[:200]}") from e
        if not data.get("ok"):
            err = data.get("error") or data
            raise CryptoPayError(str(err))
        return data.get("result")

    async def get_me(self) -> dict:
        return await self._call("getMe")

    async def create_invoice(
        self,
        *,
        asset: str,
        amount: str,
        description: str,
        payload: str,
        expires_in: int = 3600,
    ) -> dict:
        body = {
            "asset": asset,
            "amount": amount,
            "description": description[:1024],
            "payload": payload[:2048],
            "expires_in": expires_in,
        }
        return await self._call("createInvoice", json_body=body)

    async def get_invoices(self, *, invoice_ids: List[int]) -> List[dict]:
        if not invoice_ids:
            return []
        ids = ",".join(str(i) for i in invoice_ids)
        result = await self._call("getInvoices", params={"invoice_ids": ids, "count": 100})
        if result is None:
            return []
        if isinstance(result, dict):
            if "items" in result:
                return list(result["items"])
            if "invoices" in result:
                return list(result["invoices"])
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []
