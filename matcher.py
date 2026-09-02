import re

GRADE_RE = re.compile(r"\b(PSA|BGS|CGC|SGC)\s*-?\s*(10|[1-9](?:[.,]5)?)\b", re.IGNORECASE)
CARD_NUMBER_RE = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")

# Frazy sugerujace, ze "PSA N"/"BGS N" to subiektywna ocena sprzedajacego dla NIEGRADOWANEJ karty
# (np. "condition is estimated as PSA 7", "na oko psa 8/9"), a nie prawdziwy certyfikat.
# Dopasowanie jest na podstawie podciagu w oknie tekstu (nie pojedynczych tokenow), zeby dzialaly
# tez frazy wielowyrazowe.
HEDGE_WORDS = {
    "estimated", "estimate", "estimation", "guestimate", "guess", "would",
    "raw", "ungraded", "unslabbed", "uncertified", "self-graded", "selfgraded",
    "condition", "roughly", "approximately", "approx", "maybe", "possibly",
    "szacuje", "szacunkowo", "szacunek", "szacowana", "ocenie", "ocena",
    "prawdopodobnie", "mniej wiecej", "niegradowana", "niegradowany", "bez certyfikatu",
    "na oko", "moim zdaniem", "wg mnie", "według mnie",
}
HEDGE_WINDOW = 40

NOISE_WORDS = {
    "psa", "bgs", "cgc", "sgc", "beckett", "grading", "graded", "gradingu",
    "slab", "card", "cards", "karta", "karty", "pokemon", "pokemony", "sealed",
    "nowa", "nowy", "nowe", "unikat", "okazja", "okazja!", "unikatowa", "rzadka",
    "rzadki", "mint", "unikatowy", "wysylka", "cert", "certyfikat", "holo",
    "reverse", "shiny", "full", "art", "the", "and", "with", "for", "sale",
    "sprzedam", "sprzedaz",
}


def grade_key(company: str, grade_str: str) -> str:
    """('PSA', '10') -> 'psa10', ('BGS', '9.5') -> 'bgs9_5'"""
    normalized = grade_str.replace(",", ".")
    company_key = company.lower()
    if "." in normalized:
        whole, frac = normalized.split(".")
        return f"{company_key}{whole}_{frac}"
    return f"{company_key}{normalized}"


def _is_hedged(text: str, match: re.Match) -> bool:
    window = text[max(0, match.start() - HEDGE_WINDOW): match.end() + HEDGE_WINDOW].lower()
    # Podciag, nie zbior tokenow - inaczej frazy wielowyrazowe (np. "na oko") nigdy by nie trafily.
    return any(phrase in window for phrase in HEDGE_WORDS)


def parse_listing(title: str) -> dict | None:
    grade_match = None
    for candidate in GRADE_RE.finditer(title):
        if not _is_hedged(title, candidate):
            grade_match = candidate
            break
    if not grade_match:
        return None
    company = grade_match.group(1).upper()
    grade_raw = grade_match.group(2)

    number_match = CARD_NUMBER_RE.search(title)
    card_number = f"{number_match.group(1)}/{number_match.group(2)}" if number_match else None

    cleaned = title
    cleaned = GRADE_RE.sub(" ", cleaned)
    if number_match:
        cleaned = cleaned.replace(number_match.group(0), " ")
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)

    # Nie odrzucamy krotkich tokenow (V, GX, EX) - to czesto jedyne, co odroznia dwie wyceniane
    # zupelnie inaczej karty (np. "Charizard V" vs "Charizard VMAX").
    all_tokens = [t for t in cleaned.lower().split() if t not in NOISE_WORDS]

    # UWAGA: samo dopisanie gologo numeru do zapytania tekstowego wysylanego do
    # pokemonpricetracker.com potrafi zwrocic 0 wynikow (API nie radzi sobie z liczbami w
    # wyszukiwaniu pelnotekstowym) - dlatego search_query (do zapytania HTTP) jest BEZ cyfr,
    # a search_tokens (do lokalnej oceny trafnosci dopasowania) MA cyfry, wlacznie z numerem
    # karty w formacie X/Y.
    text_tokens = [t for t in all_tokens if not t.isdigit()]
    search_query = " ".join(text_tokens).strip()

    numeric_tokens = {t for t in all_tokens if t.isdigit()}
    if number_match:
        numeric_tokens.add(number_match.group(1).lstrip("0") or "0")
        numeric_tokens.add(number_match.group(2).lstrip("0") or "0")
    search_tokens = set(text_tokens) | numeric_tokens

    # Zapytanie zapasowe: krotkie "nazwa + numer" (np. "charizard 79" albo "charizard 4 102").
    # Dluzsze zapytania tekstowe z doklejonym numerem czesto zwracaja 0 wynikow w ich API,
    # ale krotkie kombinacje (1-2 slowa + numer) zazwyczaj dzialaja - uzywane jako druga proba,
    # gdy szerokie zapytanie samym tekstem nie da pewnego dopasowania.
    narrow_query = " ".join(text_tokens[:2] + sorted(numeric_tokens)).strip() if numeric_tokens else ""

    return {
        "company": company,
        "grade_raw": grade_raw,
        "grade_key": grade_key(company, grade_raw),
        "card_number": card_number,
        "search_query": search_query,
        "narrow_query": narrow_query,
        "search_tokens": search_tokens,
    }
