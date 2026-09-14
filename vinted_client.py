import html
import json
import logging
import re
import time
from urllib.parse import urlparse, parse_qs, urlencode

import requests

LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)

# Vinted przestal wystawiac publiczne /api/v2/catalog/items (zwraca 404 "not_found" od
# 2026-09-14 - najprawdopodobniej przez przebudowe frontendu na Next.js/RSC, nowa domena
# marketplace-web-assets.vinted.com). Wyniki wyszukiwania sa teraz renderowane bezposrednio
# w HTML strony /catalog, wiec scrapujemy je stamtad zamiast wolac API.
CONTAINER_RE = re.compile(r'data-testid="product-item-id-(\d+)"')
IMG_SRC_RE = re.compile(r'<img src="([^"]+)"')
LINK_TITLE_RE = re.compile(r'href="(/items/[^"]+)"[^>]*title="([^"]+)"')
TITLE_PRICE_RE = re.compile(r'^(.*?)(?:,\s*Marka:\s*[^,]+)?,\s*Stan:\s*[^,]+,\s*([\d.,]+)\s*zł,')

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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

    # Vinted potrafi miec przejsciowe awarie (5xx/polaczenie) - retry z backoffem zamiast
    # wywalania calego przebiegu na pierwszym blednym zapytaniu. Bledy 404 NIE sa tu ponawiane
    # (patrz _fetch_search_html) - to trwaly stan (np. zmiana struktury strony), nie przejsciowy.
    FETCH_RETRIES = 3
    RETRY_BACKOFF_SECONDS = (3, 8, 20)

    def _fetch_search_html(self, page: int) -> str:
        params = dict(self.query_params)
        if page > 1:
            params["page"] = str(page)
        url = self.domain + "/catalog?" + urlencode(params)

        last_exc = None
        for attempt in range(self.FETCH_RETRIES):
            try:
                resp = self.session.get(url, timeout=20)
                if resp.status_code in (401, 403):
                    log.warning("Vinted zwrocil %s, ponawiam warm-up sesji", resp.status_code)
                    self._warmed_up = False
                    self._warm_up()
                    resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                is_404 = isinstance(exc, requests.HTTPError) and exc.response is not None \
                    and exc.response.status_code == 404
                if is_404:
                    # trwaly stan (np. zmiana struktury strony przez Vinted), nie przejsciowy -
                    # ponawianie nic tu nie da, tylko marnuje czas.
                    raise
                last_exc = exc
                if attempt < self.FETCH_RETRIES - 1:
                    delay = self.RETRY_BACKOFF_SECONDS[attempt]
                    log.warning(
                        "Blad zapytania do Vinted (proba %d/%d): %s - ponawiam za %ds",
                        attempt + 1, self.FETCH_RETRIES, exc, delay,
                    )
                    time.sleep(delay)
        raise last_exc

    def _parse_search_html(self, page_html: str) -> list[dict]:
        starts = [(m.group(1), m.start()) for m in CONTAINER_RE.finditer(page_html)]
        listings = []
        for i, (item_id, pos) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else pos + 3000
            chunk = page_html[pos:end]

            link_match = LINK_TITLE_RE.search(chunk)
            if not link_match:
                continue
            href, title_attr = link_match.groups()
            title_attr = html.unescape(title_attr)

            price_match = TITLE_PRICE_RE.match(title_attr)
            title = price_match.group(1).strip() if price_match else title_attr
            price_amount = float(price_match.group(2).replace(",", ".")) if price_match else 0.0

            img_match = IMG_SRC_RE.search(chunk)

            listings.append(
                {
                    "id": item_id,
                    "title": title,
                    "price_amount": price_amount,
                    "price_currency": "PLN",
                    "url": self.domain + href.split("?")[0],
                    "photo_url": img_match.group(1) if img_match else None,
                }
            )
        return listings

    def fetch_newest_listings(self, limit: int) -> list[dict]:
        self._warm_up()

        listings = []
        page = 1
        while len(listings) < limit:
            page_html = self._fetch_search_html(page)
            page_listings = self._parse_search_html(page_html)
            if not page_listings:
                break
            listings.extend(page_listings)
            page += 1
            if len(listings) < limit:
                time.sleep(0.5)

        return listings[:limit]

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
