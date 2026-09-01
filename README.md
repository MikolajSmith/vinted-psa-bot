# vinted-psa-bot

Co 15 min sprawdza najnowsze oferty na Vinted (domyślnie dwa wyszukiwania: `pokemon psa` i
`pokemon bgs` — konfigurowalne w `VINTED_SEARCH_URLS`), dopasowuje kartę i grading (PSA, BGS,
CGC, SGC) do danych z [pokemonpricetracker.com](https://www.pokemonpricetracker.com), i jeśli
cena na Vinted mieści się w zakresie od `MIN_DISCOUNT_PERCENT` do `MAX_DISCOUNT_PERCENT`
względem ceny rynkowej dla tego gradingu (domyślnie: od 2% drożej do 40% taniej) — wysyła
powiadomienie na Discorda. Każde ogłoszenie jest wysyłane tylko raz, niezależnie z którego
wyszukiwania pochodzi (`state.json` pamięta przetworzone id, wspólne dla wszystkich wyszukiwań).

## Ważne ograniczenie

PriceCharting nie udostępnia publicznie ani przez API surowej listy "5 ostatnich sprzedaży".
Zamiast tego bot używa **medianowej ceny z danych eBay** dla danego gradingu (np. PSA 10) z
pokemonpricetracker.com — to wartość wyliczona z realnych sprzedaży, ale nie jest to dosłownie
"ostatnie 5 transakcji". W polu `sample_count` widać ile sprzedaży wchodziło w tę medianę;
oferty z mniejszą próbką niż `MIN_SALES_SAMPLE` są pomijane jako zbyt niepewne.

Dopasowanie karty z tytułu ogłoszenia Vinted do konkretnej karty w bazie jest heurystyczne
(regex na grading + numer karty, potem dopasowanie tekstowe). Oferty z niepewnym dopasowaniem
i tak trafiają na Discorda, ale oznaczone jako ⚠️ "niepewne dopasowanie".

Bot sprawdza tylko tytuł ogłoszenia (endpoint wyszukiwania Vinted nie zwraca opisu). Jeśli
tytuł nie ma gradingu, bot dodatkowo pobiera opis ogłoszenia (do `MAX_DESCRIPTION_FETCHES_PER_RUN`
sztuk na przebieg — dodatkowe zapytanie do Vinted per ogłoszenie) i sprawdza go też. Parser
odrzuca przypadki typu *"condition is estimated as PSA 7"* — to subiektywna ocena sprzedającego
dla niegradowanej karty, nie prawdziwy certyfikat, więc nie jest traktowane jako grading.

## Setup

```bash
cd "vinted-psa-bot"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Uzupełnij `.env`:

- `VINTED_SEARCH_URLS` — lista linków wyszukiwania Vinted rozdzielonych przecinkiem, domyślnie
  "pokemon psa" i "pokemon bgs" na vinted.pl, posortowane od najnowszych. Możesz dodać kolejne
  (np. "pokemon cgc"), usunąć któreś, albo podmienić na linki z dodatkowymi filtrami
  ceny/kategorii — bot przekaże wszystkie parametry z każdego linku dalej do ich API i
  sprawdzi każde wyszukiwanie osobno (deduplikacja ogłoszeń jest wspólna).
- `POKEMONPRICETRACKER_API_KEY` — załóż konto na pokemonpricetracker.com i weź klucz z panelu
  API. Darmowy tier: 100 kredytów/dzień, 60 zapytań/min. Bot pobiera po 3 kandydatów na
  ogłoszenie żeby dopasować właściwą kartę/set (2 kredyty za kartę z danymi eBay = 6 kredytów
  za sprawdzenie jednego ogłoszenia), czyli **ok. 16 nowych ogłoszeń z gradingiem dziennie**
  za darmo (limit dzielony między wszystkie wyszukiwania) — **niezależnie od tego jak często
  odpalasz bota** (deduplikacja liczy się per unikalne ogłoszenie, nie per przebieg; częstszy
  polling = szybsze wykrycie nowej oferty, a nie więcej sprawdzonych ofert dziennie). Jak bot
  trafi na dzienny limit, po prostu przestaje sprawdzać ceny do resetu limitu (widać to w
  `bot.log`) — nieprzetworzone ogłoszenia nie są oznaczane jako "seen" i zostaną sprawdzone w
  kolejnym przebiegu. Na płatnym planie (np. $9.99/mies. za 20 000 kredytów/dzień) ten limit
  praktycznie nie występuje.
- `DISCORD_WEBHOOK_URL` — zobacz sekcję niżej.

### Jak założyć webhook Discord

1. Otwórz Discorda, wejdź na serwer/kanał gdzie mają przychodzić powiadomienia.
2. Kliknij ⚙️ przy nazwie kanału → **Integracje** (Integrations).
3. **Webhooki** → **Nowy webhook** (New Webhook).
4. Nadaj nazwę (np. "Vinted PSA Bot"), wybierz kanał docelowy.
5. Kliknij **Kopiuj URL webhooka** (Copy Webhook URL) i wklej do `.env` jako `DISCORD_WEBHOOK_URL`.

### Test ręczny

```bash
source venv/bin/activate
python bot.py
```

Sprawdź `bot.log` — powinny pojawić się logi o liczbie pobranych ofert. Za pierwszym razem
bot przetworzy wszystkie pobrane oferty (bo `state.json` jest puste) — kolejne przebiegi
analizują tylko nowe ogłoszenia.

### Log aktywności

Każda sprawdzona oferta (nie tylko te wysłane na Discorda) trafia jako wiersz do
`activity_log.csv` w folderze projektu — możesz go otworzyć w Excelu/Numbers albo podejrzeć
w terminalu (`tail -f activity_log.csv`). Kolumny: `checked_at`, `listing_id`, `title`, `url`,
`listing_price`, `listing_currency`, `grade`, `reference_price_usd` (cena referencyjna z
pokemonpricetracker po weryfikacji), `sample_count`, `discount_percent`, `match_score`,
`decision` (np. `wyslano_na_discord`, `poza_zakresem_rabatu`, `brak_ceny_referencyjnej`,
`za_mala_probka_sprzedazy`, `limit_api_wyczerpany_retry_pozniej`,
`brak_gradingu_w_tytule_ani_opisie`).

## Uruchamianie 24/7 (GitHub Actions) — aktualny sposób produkcyjny

Repo: https://github.com/MikolajSmith/vinted-psa-bot (publiczne — kod jest jawny, ale sekrety
nie). Workflow `.github/workflows/bot.yml` odpala bota co 15 min (`cron: */15 * * * *`) na
maszynie GitHuba, niezależnie od tego czy Twój Mac jest włączony. Po każdym przebiegu bot
commituje zaktualizowany `state.json` i `activity_log.csv` z powrotem do repo (dlatego te pliki
NIE są w `.gitignore` — to jedyny sposób na trwały stan między przebiegami na efemerycznych
maszynach Actions).

Setup (już zrobiony, dla przypomnienia jak odtworzyć od zera):

```bash
gh auth login
gh auth refresh -h github.com -s workflow   # push pliku w .github/workflows wymaga tego scope
gh repo create vinted-psa-bot --public --source=. --remote=origin --push
gh secret set POKEMONPRICETRACKER_API_KEY --repo <user>/vinted-psa-bot
gh secret set DISCORD_WEBHOOK_URL --repo <user>/vinted-psa-bot
gh api -X PUT repos/<user>/vinted-psa-bot/actions/permissions/workflow -f default_workflow_permissions=write
```

Żeby zmienić kod/config: edytuj pliki lokalnie, `git add -A && git commit -m "..." && git push`
— następny zaplanowany przebieg (albo ręczne `gh workflow run bot.yml`) użyje nowej wersji.

Podgląd przebiegów: `gh run list --repo <user>/vinted-psa-bot` albo zakładka **Actions** na
GitHubie. Żeby zatrzymać: **Settings → Actions → Disable Actions** w repo, albo usuń plik
workflow.

**Limity darmowe**: repo jest publiczne, więc minuty GitHub Actions są nielimitowane. Gdyby
kiedyś repo zrobić prywatnym, darmowy limit to 2000 min/mies. — przy co 15 min to się może nie
zmieścić, trzeba by rzadziej odpytywać.

### Zewnętrzny "budzik" (cron-job.org) — omija throttling harmonogramu GitHuba

**Ważne odkrycie**: natywny `schedule: cron` w GitHub Actions to "best effort" — dla mało
aktywnych repo GitHub potrafi mocno opóźniać wyzwalanie (w praktyce zaobserwowane 3-5.5h zamiast
15 min). Rozwiązanie: darmowy serwis [cron-job.org](https://cron-job.org) co 15 min wywołuje
bezpośrednio GitHub REST API (`workflow_dispatch`), co omija throttling natywnego schedulera.

Setup (już zrobiony):

1. GitHub → fine-grained personal access token, scope tylko do repo `vinted-psa-bot`,
   uprawnienie **Actions: Read and write**, bez wygaśnięcia (Settings → Developer settings →
   Personal access tokens → Fine-grained tokens).
2. Konto na cron-job.org (mikolajsmith19@gmail.com), cronjob "vinted-psa-bot trigger":
   - URL: `https://api.github.com/repos/MikolajSmith/vinted-psa-bot/actions/workflows/bot.yml/dispatches`
   - Metoda: `POST`, co 15 minut
   - Nagłówki: `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`,
     `Authorization: Bearer <token z kroku 1>`, `Content-Type: application/json`
   - Body: `{"ref":"main"}`
   - Powiadomienie mailem włączone przy niepowodzeniu wykonania.

Natywny `schedule` w `bot.yml` zostaje jako zapasowy mechanizm (redundancja, nie szkodzi).
Podgląd/edycja: [console.cron-job.org](https://console.cron-job.org) → Cronjobs.

Jeśli token kiedyś wygaśnie/zostanie odwołany, cron-job.org zacznie dostawać błędy 401 —
wtedy trzeba wygenerować nowy fine-grained token i podmienić go w nagłówku `Authorization`
na cron-job.org (Cronjobs → edytuj → Advanced → Headers).

### Alternatywa: macOS launchd (lokalnie, tylko gdy Mac jest włączony)

Ten sposób jest **wyłączony** (odinstalowany z `launchctl`), bo kolidowałby ze stanem
zarządzanym teraz przez GitHub Actions (dwa niezależne `state.json` = podwójne powiadomienia).
Zostaw jako opcję awaryjną/do testów lokalnych — nie uruchamiaj równolegle z GitHub Actions.

Plik `com.mikolaj.vintedpsabot.plist` jest już skonfigurowany pod ścieżkę tego projektu.

```bash
cp com.mikolaj.vintedpsabot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mikolaj.vintedpsabot.plist
```

Bot uruchomi się od razu po załadowaniu, a potem co 900 sekund (15 min) — także po restarcie
komputera. Logi launchd (stdout/stderr procesu) lądują w `launchd.out.log` i `launchd.err.log`
w folderze projektu, a logi aplikacyjne w `bot.log`.

Żeby zatrzymać bota:

```bash
launchctl unload ~/Library/LaunchAgents/com.mikolaj.vintedpsabot.plist
```

Żeby zrestartować po zmianie kodu/configu:

```bash
launchctl unload ~/Library/LaunchAgents/com.mikolaj.vintedpsabot.plist
launchctl load ~/Library/LaunchAgents/com.mikolaj.vintedpsabot.plist
```

## Strojenie

Wszystko w `.env`:

- `MIN_DISCOUNT_PERCENT` / `MAX_DISCOUNT_PERCENT` — zakres rabatu, przy którym leci
  powiadomienie (domyślnie -2 do 40 — czyli od 2% drożej do 40% taniej niż cena referencyjna;
  powyżej ~40% taniej to zwykle błędne dopasowanie karty/setu, nie prawdziwa okazja).
- `MIN_SALES_SAMPLE` — minimalna liczba sprzedaży w danym gradingu, żeby cena referencyjna
  była uznana za wiarygodną (domyślnie 3).
- `MAX_LISTINGS_PER_RUN` — ile najnowszych ofert z Vinted sprawdzać w jednym przebiegu
  (domyślnie 200, pobierane stronicowo po 96).
- `MAX_DESCRIPTION_FETCHES_PER_RUN` — ile ofert bez gradingu w tytule dodatkowo sprawdzić przez
  pobranie pełnego opisu ogłoszenia (domyślnie 50, wspólny licznik dla wszystkich wyszukiwań
  w danym przebiegu). Każde takie sprawdzenie to dodatkowe zapytanie do Vinted (throttlowane
  co 0.6s), więc wyższa wartość = wolniejszy przebieg.
