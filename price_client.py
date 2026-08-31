import logging

import requests

log = logging.getLogger("vinted_bot.price")

API_BASE = "https://www.pokemonpricetracker.com/api/v2"


class PriceClient:
    # includeEbay=true kosztuje 2 kredyty za kazda zwrocona karte (1 base + 1 ebay).
    # Darmowy tier ma 100 kredytow/dzien, wiec limit=3 pozwala na ok. 16 sprawdzen dziennie.
    SEARCH_LIMIT = 3

    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self.quota_exhausted = False

    def _best_match(self, candidates: list[dict], search_tokens: set[str]):
        best, best_score = None, 0.0
        for card in candidates:
            text = f"{card.get('name', '')} {card.get('setName', '')}".lower()
            card_tokens = set(text.split())
            if not card_tokens:
                continue
            overlap = len(search_tokens & card_tokens)
            score = overlap / max(len(search_tokens), 1)
            if score > best_score:
                best, best_score = card, score
        return best, best_score

    @staticmethod
    def _reference_price(grade_data: dict) -> float | None:
        smart = grade_data.get("smartMarketPrice") or {}
        if smart.get("price") and smart.get("confidence") in ("medium", "high"):
            return float(smart["price"])
        if grade_data.get("medianPrice"):
            return float(grade_data["medianPrice"])
        return None

    def get_reference_price(self, search_query: str, grade_key: str, search_tokens: set[str]) -> dict | None:
        if not search_query or self.quota_exhausted:
            return None
        try:
            resp = self.session.get(
                f"{API_BASE}/cards",
                params={"search": search_query, "includeEbay": "true", "limit": self.SEARCH_LIMIT},
                timeout=15,
            )
            if resp.status_code == 429:
                self.quota_exhausted = True
                log.warning("Dzienny limit kredytow pokemonpricetracker wyczerpany, pomijam reszte przebiegu")
                return None
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Blad zapytania do pokemonpricetracker dla %r: %s", search_query, exc)
            return None

        data = resp.json().get("data", [])
        if not data:
            return None

        card, match_score = self._best_match(data, search_tokens)
        if card is None:
            return None

        sales_by_grade = ((card.get("ebay") or {}).get("salesByGrade") or {})
        grade_data = sales_by_grade.get(grade_key)
        if not grade_data:
            return None
        reference_price = self._reference_price(grade_data)
        if not reference_price:
            return None

        return {
            "card_name": card.get("name"),
            "set_name": card.get("setName"),
            "match_score": match_score,
            "median_price_usd": reference_price,
            "sample_count": int(grade_data.get("count", 0)),
            "last_sale_date": grade_data.get("lastSaleDate"),
        }
