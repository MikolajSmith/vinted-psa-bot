import logging

import requests

log = logging.getLogger("vinted_bot.fx")

_cache: dict[str, float] = {}


def get_rate(from_currency: str, to_currency: str = "USD") -> float:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    if from_currency == to_currency:
        return 1.0

    key = f"{from_currency}->{to_currency}"
    if key in _cache:
        return _cache[key]

    resp = requests.get(
        "https://api.frankfurter.app/latest",
        params={"from": from_currency, "to": to_currency},
        timeout=10,
    )
    resp.raise_for_status()
    rate = float(resp.json()["rates"][to_currency])
    _cache[key] = rate
    return rate
