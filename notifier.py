import logging

import requests

log = logging.getLogger("vinted_bot.notifier")

COLOR_GOOD_DEAL = 3066923
COLOR_HAS_PRICE = 3900151
COLOR_NO_PRICE = 9807270
COLOR_UNCERTAIN_MATCH = 15105570


def _price_block(deal: dict) -> str:
    if deal.get("reference_price_usd") is None:
        return "Cena referencyjna: **niedostępna** (brak dopasowania w bazie albo wyczerpany limit API)"

    sample_note = (
        f"\n📉 **Cena oparta tylko na {deal['sample_count']} sprzedaży — potraktuj jako orientacyjną**"
        if deal["sample_count"] <= 2 else ""
    )
    discount_line = (
        f"\nRabat: **{deal['discount_percent']:.1f}%**" if deal.get("discount_percent") is not None else ""
    )
    return (
        f"Dopasowana karta: **{deal.get('matched_card_name', '?')}** ({deal.get('matched_set_name', '?')})\n"
        f"Cena referencyjna ({deal['grade_raw']}, {deal['sample_count']} sprzedaży, "
        f"metoda: {deal.get('pricing_method', '?')}): **{deal['reference_price_usd']:.2f} USD**"
        f"{discount_line}"
        f"{sample_note}"
    )


def send_deal_alert(webhook_url: str, deal: dict):
    confidence_note = (
        "\n⚠️ **Niepewne dopasowanie karty — zweryfikuj ręcznie**" if deal["confident"] is False else ""
    )
    vinted_price_line = f"Cena Vinted: **{deal['listing_price']:.2f} {deal['listing_currency']}**"
    if deal.get("listing_price_usd") is not None:
        vinted_price_line += f" (~{deal['listing_price_usd']:.2f} USD)"

    description = (
        f"**{deal['title']}**\n"
        f"Grading: **{deal['grade_raw']}**\n"
        f"{vinted_price_line}\n"
        f"{_price_block(deal)}"
        f"{confidence_note}"
    )

    if deal["confident"] is False:
        color = COLOR_UNCERTAIN_MATCH
    elif deal.get("is_good_deal"):
        color = COLOR_GOOD_DEAL
    elif deal.get("reference_price_usd") is not None:
        color = COLOR_HAS_PRICE
    else:
        color = COLOR_NO_PRICE

    base_title = "🔥 Okazja + karta z gradingiem na Vinted" if deal.get("is_good_deal") else "🎴 Nowa karta z gradingiem na Vinted"
    title = f"[{deal['vintage_tag']}] {base_title}" if deal.get("vintage_tag") else base_title

    payload = {
        "embeds": [
            {
                "title": title,
                "url": deal["url"],
                "description": description,
                "color": color,
                "image": {"url": deal["photo_url"]} if deal.get("photo_url") else None,
            }
        ]
    }
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    log.info("Wyslano powiadomienie Discord dla oferty %s", deal["listing_id"])
