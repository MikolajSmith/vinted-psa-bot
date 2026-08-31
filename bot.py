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


def _process_listing(listing, vinted, price_client, counters):
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

    if price_client.quota_exhausted:
        # nie oznaczamy jako "seen" - sprobujemy ponownie w kolejnym przebiegu, po resecie limitu
        _log_activity(listing, "limit_api_wyczerpany_retry_pozniej", parsed=parsed)
        return

    reference = price_client.get_reference_price(
        parsed["search_query"], parsed["grade_key"], parsed["search_tokens"]
    )
    if price_client.quota_exhausted:
        _log_activity(listing, "limit_api_wyczerpany_retry_pozniej", parsed=parsed)
        return
    counters["new_ids"].append(listing["id"])

    if not reference:
        _log_activity(listing, "brak_ceny_referencyjnej", parsed=parsed)
        return
    if reference["sample_count"] < config.MIN_SALES_SAMPLE:
        _log_activity(listing, "za_mala_probka_sprzedazy", parsed=parsed, reference=reference)
        return

    try:
        rate = fx.get_rate(listing["price_currency"], "USD")
    except Exception as exc:  # noqa: BLE001 - kurs walut nie moze wywalic calego runu
        log.warning("Nie udalo sie pobrac kursu walut: %s", exc)
        _log_activity(listing, "blad_kursu_walut", parsed=parsed, reference=reference)
        return
    listing_price_usd = listing["price_amount"] * rate

    reference_usd = reference["median_price_usd"]
    if reference_usd <= 0:
        _log_activity(listing, "nieprawidlowa_cena_referencyjna", parsed=parsed, reference=reference)
        return
    discount_percent = (reference_usd - listing_price_usd) / reference_usd * 100

    if not (config.MIN_DISCOUNT_PERCENT <= discount_percent <= config.MAX_DISCOUNT_PERCENT):
        _log_activity(
            listing, "poza_zakresem_rabatu", parsed=parsed, reference=reference,
            discount_percent=discount_percent,
        )
        return

    confident = reference["match_score"] >= 0.5
    deal = {
        "listing_id": listing["id"],
        "title": listing["title"],
        "url": listing["url"],
        "photo_url": listing["photo_url"],
        "listing_price": listing["price_amount"],
        "listing_currency": listing["price_currency"],
        "listing_price_usd": listing_price_usd,
        "grade_raw": f"{parsed['company']} {parsed['grade_raw']}",
        "reference_price_usd": reference_usd,
        "sample_count": reference["sample_count"],
        "discount_percent": discount_percent,
        "confident": confident,
    }
    try:
        send_deal_alert(config.DISCORD_WEBHOOK_URL, deal)
        counters["deals_found"] += 1
        _log_activity(
            listing, "wyslano_na_discord", parsed=parsed, reference=reference,
            discount_percent=discount_percent,
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

        for listing in listings:
            if listing["id"] in seen_ids_set:
                # feed jest posortowany od najnowszych - dalsze pozycje sa starsze i tez juz sprawdzone
                log.info("Trafiono na juz sprawdzona oferte %s, przerywam to wyszukiwanie", listing["id"])
                break
            ids_before = len(counters["new_ids"])
            _process_listing(listing, vinted, price_client, counters)
            if len(counters["new_ids"]) > ids_before:
                # dopiero teraz naprawde "przetworzone" - blokuje ponowne wysylanie w drugim
                # wyszukiwaniu w tym samym przebiegu; oferty pominiete przez limit API NIE sa
                # dodawane, zeby kolejne wyszukiwanie mialo szanse je jeszcze sprawdzic
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
