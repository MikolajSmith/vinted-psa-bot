import logging
import re

import requests

log = logging.getLogger("vinted_bot.price")

API_BASE = "https://www.pokemonpricetracker.com/api/v2"


def _tokenize(text: str) -> set[str]:
    """Dzieli tekst na tokeny, normalizujac cyfrowe (np. '079' -> '79'), zeby numery kart
    z zerami wiodacymi (typowe w PriceTracker) dopasowywaly sie do numerow z tytulu Vinted."""
    raw = re.sub(r"[^\w]", " ", text, flags=re.UNICODE).lower().split()
    tokens = set()
    for t in raw:
        tokens.add(t.lstrip("0") if t.isdigit() and t.lstrip("0") else t)
    return tokens


class PriceClient:
    # includeEbay=true kosztuje 2 kredyty za kazda zwrocona karte (1 base + 1 ebay).
    SEARCH_LIMIT = 6
    # Minimalna liczba WSPOLNYCH slow (nie procent!) miedzy tytulem a nazwa/setem dopasowanej
    # karty, zeby uznac dopasowanie za pewne. Przy zapytaniu 1-slownym (np. samo "charizard")
    # kazdy kandydat z tym slowem w nazwie dostawal kiedys 100% pokrycia mimo bycia zupelnie
    # inna karta - stad wymog liczby bezwzglednej, nie tylko stosunku.
    MIN_CONFIDENT_OVERLAP = 2

    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self.quota_exhausted = False

    def _best_match(self, candidates: list[dict], search_tokens: set[str]):
        best, best_overlap, best_ratio = None, 0, 0.0
        for card in candidates:
            text = f"{card.get('name', '')} {card.get('setName', '')} {card.get('cardNumber', '')}"
            card_tokens = _tokenize(text)
            if not card_tokens:
                continue
            overlap = len(search_tokens & card_tokens)
            ratio = overlap / max(len(search_tokens), 1)
            if overlap == 0:
                continue
            if (overlap, ratio) > (best_overlap, best_ratio):
                best, best_overlap, best_ratio = card, overlap, ratio
        return best, best_overlap, best_ratio

    @staticmethod
    def _reference_price(grade_data: dict) -> tuple[float, str] | tuple[None, None]:
        """Preferuje zwykla mediane (ta sama liczba widoczna recznie na pokemonpricetracker.com -
        latwo zweryfikowac), smartMarketPrice tylko jako fallback gdy mediany brak."""
        if grade_data.get("medianPrice"):
            return float(grade_data["medianPrice"]), "mediana"
        smart = grade_data.get("smartMarketPrice") or {}
        if smart.get("price"):
            return float(smart["price"]), f"smartMarketPrice ({smart.get('confidence', '?')})"
        return None, None

    def _search(self, query: str, grade_key: str, search_tokens: set[str]) -> dict | None:
        try:
            resp = self.session.get(
                f"{API_BASE}/cards",
                params={"search": query, "includeEbay": "true", "limit": self.SEARCH_LIMIT},
                timeout=15,
            )
            if resp.status_code == 429:
                self.quota_exhausted = True
                log.warning("Dzienny limit kredytow pokemonpricetracker wyczerpany, pomijam reszte przebiegu")
                return None
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Blad zapytania do pokemonpricetracker dla %r: %s", query, exc)
            return None

        data = resp.json().get("data", [])
        if not data:
            return None

        card, overlap, ratio = self._best_match(data, search_tokens)
        if card is None:
            return None

        sales_by_grade = ((card.get("ebay") or {}).get("salesByGrade") or {})
        grade_data = sales_by_grade.get(grade_key)
        if not grade_data:
            return None
        reference_price, pricing_method = self._reference_price(grade_data)
        if not reference_price:
            return None

        return {
            "card_name": card.get("name"),
            "set_name": card.get("setName"),
            "match_score": ratio,
            "match_overlap": overlap,
            "confident": overlap >= self.MIN_CONFIDENT_OVERLAP,
            "median_price_usd": reference_price,
            "pricing_method": pricing_method,
            "sample_count": int(grade_data.get("count", 0)),
            "last_sale_date": grade_data.get("lastSaleDate"),
        }

    def get_reference_price(
        self, search_query: str, grade_key: str, search_tokens: set[str], narrow_query: str = ""
    ) -> dict | None:
        """Najpierw szerokie zapytanie samym tekstem. Jesli nie da pewnego dopasowania (albo
        nic nie zwroci), druga proba z krotszym zapytaniem "nazwa + numer" - dluzsze zapytania
        z doklejonym numerem czesto zwracaja 0 wynikow w tym API, ale krotkie kombinacje zwykle
        dzialaja i potrafia trafic dokladnie w konkretny wariant karty."""
        if self.quota_exhausted:
            return None

        result = self._search(search_query, grade_key, search_tokens) if search_query else None
        if result and result["confident"]:
            return result

        if narrow_query and narrow_query != search_query and not self.quota_exhausted:
            narrow_result = self._search(narrow_query, grade_key, search_tokens)
            if narrow_result and (not result or narrow_result["match_overlap"] > result["match_overlap"]):
                return narrow_result

        return result
