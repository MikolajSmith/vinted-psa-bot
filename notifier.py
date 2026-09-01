import logging

import requests

log = logging.getLogger("vinted_bot.notifier")


def send_deal_alert(webhook_url: str, deal: dict):
    confidence_note = "" if deal["confident"] else "\n⚠️ **Niepewne dopasowanie karty — zweryfikuj ręcznie**"
    description = (
        f"**{deal['title']}**\n"
        f"Dopasowana karta: **{deal.get('matched_card_name', '?')}** ({deal.get('matched_set_name', '?')})\n"
        f"Cena Vinted: **{deal['listing_price']:.2f} {deal['listing_currency']}** "
        f"(~{deal['listing_price_usd']:.2f} USD)\n"
        f"Cena referencyjna ({deal['grade_raw']}, {deal['sample_count']} sprzedaży, "
        f"metoda: {deal.get('pricing_method', '?')}): **{deal['reference_price_usd']:.2f} USD**\n"
        f"Rabat: **{deal['discount_percent']:.1f}%**"
        f"{confidence_note}"
    )
    payload = {
        "embeds": [
            {
                "title": "🔥 Okazja PSA na Vinted",
                "url": deal["url"],
                "description": description,
                "color": 3066993 if deal["confident"] else 15105570,
                "image": {"url": deal["photo_url"]} if deal.get("photo_url") else None,
            }
        ]
    }
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    log.info("Wyslano powiadomienie Discord dla oferty %s", deal["listing_id"])
