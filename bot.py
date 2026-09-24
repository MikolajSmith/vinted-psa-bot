import logging
from datetime import datetime, timezone

import activity_log
import config
import fx
import matcher
import state
from notifier import send_deal_alert
from price_client import PriceClient
from vinted_client import VintedClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("vinted_bot")

# Etykieta serii do powiadomienia (np. "Vintage Holo Jungle"), na podstawie tego ktore
# wyszukiwanie Vinted znalazlo dane ogloszenie. "1st ed", "gold star" i "banned" celowo nie
# maja etykiety serii - to nie nazwy setow, tylko oznaczenie edycji/rzadkosci.
SERIES_LABELS = {
    "jungle": "Jungle",
    "fossil": "Fossil",
    "neo": "Neo",
    "skyridge": "Skyridge",
    "aquapolis": "Aquapolis",
}


def _series_label_from_url(search_url: str) -> str | None:
    lowered = search_url.lower()
    for keyword, label in SERIES_LABELS.items():
        if keyword in lowered:
            return label
    return None


def _log_activity(listing, decision, parsed=None, reference=None, discount_percent=None):
    activity_log.log_row(
        config.ACTIVITY_LOG_FILE,
        {
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "listing_id": listing["id"],
            "title": listing["title"],
            "url": listing["url"],
            "listing_price": listing["price_amount"],
            "listing_currency": listing["price_currency"],
            "grade": f"{parsed['company']} {parsed['grade_raw']}" if parsed else "",
            "reference_price_usd": f"{reference['median_price_usd']:.2f}" if reference else "",
            "sample_count": reference["sample_count"] if reference else "",
            "discount_percent": f"{discount_percent:.1f}" if discount_percent is not None else "",
            "match_score": f"{reference['match_score']:.2f}" if reference else "",
            "decision": decision,
        },
    )


def _process_listing(listing, vinted, price_client, counters, series_label):
    # Bot informuje o KAZDYM ogloszeniu z wykrytym gradingiem (PSA/BGS/CGC/SGC) - cena
    # referencyjna to tylko dodatkowa informacja w powiadomieniu, nie warunek wysylki.
    description = None
    parsed = matcher.parse_listing(listing["title"])
    if not parsed:
        if counters["description_fetches_left"] <= 0:
            counters["new_ids"].append(listing["id"])
            _log_activity(listing, "brak_gradingu_w_tytule_limit_opisow")
            return
        counters["description_fetches_left"] -= 1
        description = vinted.fetch_description(listing["url"])
        parsed = matcher.parse_listing(f"{listing['title']} {description}")
        if not parsed:
            counters["new_ids"].append(listing["id"])
            _log_activity(listing, "brak_gradingu_w_tytule_ani_opisie")
            return

    # Vinted zwraca wyniki na podstawie luznego dopasowania - wyszukiwanie "fossil" potrafi
    # zwrocic wspolczesna karte, ktora w ogole nie wspomina o Fossil. Wymagamy wiec, zeby
    # tytul/opis faktycznie potwierdzal docelowa serie/kategorie, nie tylko to ktore
    # wyszukiwanie ja znalazlo.
    if not parsed["mentions_target_set"]:
        if description is None and counters["description_fetches_left"] > 0:
            counters["description_fetches_left"] -= 1
            description = vinted.fetch_description(listing["url"])
            parsed = matcher.parse_listing(f"{listing['title']} {description}")
        if not parsed or not parsed["mentions_target_set"]:
            counters["new_ids"].append(listing["id"])
            _log_activity(listing, "brak_potwierdzenia_serii_vintage", parsed=parsed)
            return

    counters["new_ids"].append(listing["id"])

    reference = None
    if not price_client.quota_exhausted:
        reference = price_client.get_reference_price(
            parsed["search_query"], parsed["grade_key"], parsed["search_tokens"], parsed["narrow_query"]
        )

    listing_price_usd = None
    discount_percent = None
    if reference and reference["median_price_usd"] > 0:
        try:
            rate = fx.get_rate(listing["price_currency"], "USD")
            listing_price_usd = listing["price_amount"] * rate
            discount_percent = (
                (reference["median_price_usd"] - listing_price_usd) / reference["median_price_usd"] * 100
            )
        except Exception as exc:  # noqa: BLE001 - brak kursu walut nie blokuje powiadomienia
            log.warning("Nie udalo sie pobrac kursu walut: %s", exc)

    vintage_tag = None
    if parsed["is_holo"]:
        vintage_tag = f"Vintage Holo {series_label}" if series_label else "Vintage Holo"

    deal = {
        "listing_id": listing["id"],
        "title": listing["title"],
        "vintage_tag": vintage_tag,
        "url": listing["url"],
        "photo_url": listing["photo_url"],
        "listing_price": listing["price_amount"],
        "listing_currency": listing["price_currency"],
        "listing_price_usd": listing_price_usd,
        "grade_raw": f"{parsed['company']} {parsed['grade_raw']}",
        "reference_price_usd": reference["median_price_usd"] if reference else None,
        "pricing_method": reference["pricing_method"] if reference else None,
        "matched_card_name": reference["card_name"] if reference else None,
        "matched_set_name": reference["set_name"] if reference else None,
        "sample_count": reference["sample_count"] if reference else None,
        "discount_percent": discount_percent,
        "confident": reference["confident"] if reference else None,
        "is_good_deal": (
            reference is not None
            and discount_percent is not None
            and config.MIN_DISCOUNT_PERCENT <= discount_percent <= config.MAX_DISCOUNT_PERCENT
        ),
    }
    try:
        send_deal_alert(config.DISCORD_WEBHOOK_URL, deal)
        counters["deals_found"] += 1
        _log_activity(
            listing, "wyslano_na_discord" if reference else "wyslano_na_discord_bez_ceny",
            parsed=parsed, reference=reference, discount_percent=discount_percent,
        )
    except Exception as exc:  # noqa: BLE001 - nie przerywamy runu na jednym bledzie webhooka
        log.error("Nie udalo sie wyslac powiadomienia Discord: %s", exc)
        _log_activity(
            listing, "blad_wysylki_discord", parsed=parsed, reference=reference,
            discount_percent=discount_percent,
        )


def run():
    seen_ids = state.load_seen_ids(config.STATE_FILE)
    seen_ids_set = set(seen_ids)

    price_client = PriceClient(config.POKEMONPRICETRACKER_API_KEY)
    counters = {"new_ids": [], "deals_found": 0, "description_fetches_left": config.MAX_DESCRIPTION_FETCHES_PER_RUN}

    for search_url in config.VINTED_SEARCH_URLS:
        vinted = VintedClient(search_url)
        listings = vinted.fetch_newest_listings(config.MAX_LISTINGS_PER_RUN)
        log.info("Pobrano %d ofert z Vinted (%s)", len(listings), search_url)
        series_label = _series_label_from_url(search_url)

        for listing in listings:
            if listing["id"] in seen_ids_set:
                # feed jest posortowany od najnowszych - dalsze pozycje sa starsze i tez juz sprawdzone
                log.info("Trafiono na juz sprawdzona oferte %s, przerywam to wyszukiwanie", listing["id"])
                break
            _process_listing(listing, vinted, price_client, counters, series_label)
            # kazda przetworzona oferta jest od razu oznaczana jako "seen" (blokuje ponowne
            # wysylanie w drugim wyszukiwaniu w tym samym przebiegu) - cena jest tylko
            # dodatkiem, wiec nie ma juz powodu odkladac ofert "na potem" z powodu limitu API
            seen_ids_set.add(listing["id"])

    seen_ids.extend(counters["new_ids"])
    state.save_seen_ids(config.STATE_FILE, seen_ids)
    log.info(
        "Koniec przebiegu: %d nowych ofert, %d wyslanych okazji",
        len(counters["new_ids"]),
        counters["deals_found"],
    )


if __name__ == "__main__":
    run()
