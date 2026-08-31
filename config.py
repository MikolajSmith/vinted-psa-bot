import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Brak wymaganej zmiennej srodowiskowej: {name}. Uzupelnij plik .env")
    return value


_DEFAULT_SEARCH_URLS = (
    "https://www.vinted.pl/catalog?search_text=pokemon%20psa&order=newest_first,"
    "https://www.vinted.pl/catalog?search_text=pokemon%20bgs&order=newest_first"
)
# Lista linkow wyszukiwania Vinted rozdzielonych przecinkiem - bot sprawdza kazdy z osobna,
# ale ogloszenia sa deduplikowane globalnie (jedno id = sprawdzone raz, niezaleznie z ktorego wyszukiwania).
VINTED_SEARCH_URLS = [
    url.strip()
    for url in os.environ.get("VINTED_SEARCH_URLS", _DEFAULT_SEARCH_URLS).split(",")
    if url.strip()
]
POKEMONPRICETRACKER_API_KEY = _require("POKEMONPRICETRACKER_API_KEY")
DISCORD_WEBHOOK_URL = _require("DISCORD_WEBHOOK_URL")
# Zakres rabatu wzgledem ceny referencyjnej: dodatnie wartosci = tansze, ujemne = drozsze.
# Domyslnie: od 2% drozej do 40% taniej (powyzej 40% taniej to zwykle bledne dopasowanie karty).
MIN_DISCOUNT_PERCENT = float(os.environ.get("MIN_DISCOUNT_PERCENT", "-2"))
MAX_DISCOUNT_PERCENT = float(os.environ.get("MAX_DISCOUNT_PERCENT", "40"))
MIN_SALES_SAMPLE = int(os.environ.get("MIN_SALES_SAMPLE", "3"))
MAX_LISTINGS_PER_RUN = int(os.environ.get("MAX_LISTINGS_PER_RUN", "200"))
# Ile ogloszen bez PSA w tytule sprawdzic dodatkowo przez pobranie opisu (dociazenie Vinted per przebieg).
MAX_DESCRIPTION_FETCHES_PER_RUN = int(os.environ.get("MAX_DESCRIPTION_FETCHES_PER_RUN", "50"))

STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "bot.log"
ACTIVITY_LOG_FILE = BASE_DIR / "activity_log.csv"
