import json
import logging
import re
import time
from urllib.parse import urlparse, parse_qs

import requests

LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)

log = logging.getLogger("vinted_bot.vinted")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class VintedClient:
    def __init__(self, search_url: str):
        parsed = urlparse(search_url)
        self.domain = f"{parsed.scheme}://{parsed.netloc}"
        self.query_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.query_params.setdefault("order", "newest_first")

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
            }
        )
        self._warmed_up = False

    def _warm_up(self):
        if self._warmed_up:
            return
        resp = self.session.get(self.domain + "/", timeout=15)
        resp.raise_for_status()
        self._warmed_up = True

    PER_PAGE = 96

    def _fetch_page(self, page: int, per_page: int) -> list[dict]:
        params = dict(self.query_params)
        params["per_page"] = str(per_page)
        params["page"] = str(page)

        resp = self.session.get(
            self.domain + "/api/v2/catalog/items",
            params=params,
            headers={"Referer": self.domain + "/catalog"},
            timeout=15,
        )
        if resp.status_code in (401, 403):
            log.warning("Vinted zwrocil %s, ponawiam warm-up sesji", resp.status_code)
            self._warmed_up = False
            self._warm_up()
            resp = self.session.get(
                self.domain + "/api/v2/catalog/items",
                params=params,
                headers={"Referer": self.domain + "/catalog"},
                timeout=15,
            )
        resp.raise_for_status()
        return resp.json().get("items", [])

    def fetch_newest_listings(self, limit: int) -> list[dict]:
        self._warm_up()

        items = []
        page = 1
        while len(items) < limit:
            per_page = min(self.PER_PAGE, limit - len(items))
            page_items = self._fetch_page(page, per_page)
            if not page_items:
                break
            items.extend(page_items)
            page += 1
            if len(items) < limit:
                time.sleep(0.5)

        listings = []
        for item in items[:limit]:
            price = item.get("price") or item.get("total_item_price") or {}
            listings.append(
                {
                    "id": str(item.get("id")),
                    "title": item.get("title") or "",
                    "price_amount": float(price.get("amount", 0) or 0),
                    "price_currency": price.get("currency_code", "PLN"),
                    "url": item.get("url"),
                    "photo_url": (item.get("photo") or {}).get("url"),
                }
            )
        return listings

    DESCRIPTION_FETCH_DELAY = 0.6

    def fetch_description(self, item_url: str) -> str:
        """Pobiera opis ogloszenia ze strony produktu (embedded JSON-LD). Zwraca '' przy niepowodzeniu."""
        time.sleep(self.DESCRIPTION_FETCH_DELAY)
        for attempt in range(2):
            try:
                resp = self.session.get(item_url, timeout=15)
                if resp.status_code == 429:
                    log.warning("Vinted zwrocil 429 dla %s, czekam i ponawiam", item_url)
                    time.sleep(3)
                    continue
                resp.raise_for_status()
                match = LD_JSON_RE.search(resp.text)
                if not match:
                    return ""
                data = json.loads(match.group(1))
                return data.get("description") or ""
            except (requests.RequestException, json.JSONDecodeError) as exc:
                log.warning("Nie udalo sie pobrac opisu dla %s: %s", item_url, exc)
                return ""
        return ""
