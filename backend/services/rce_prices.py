"""
Serwis cen RCE (Rynkowa Cena Energii) z danych PSE (Polskie Sieci Elektroenergetyczne).

Pobiera realne historyczne dane cenowe RCE z API PSE:
https://api.raporty.pse.pl/api/rce-pln

Dane dostepne od 2024-06-14, 96 rekordow na dzien (15-minutowe interwaly).
Agregowane do srednich godzinowych (4 periody na godzine).

Kluczowe obserwacje z realnych danych:
- Latem w godzinach 10-15 ceny sa najnizsze (duzo produkcji PV w systemie)
- Wieczorem 17-21 ceny sa najwyzsze (szczyt zapotrzebowania)
- Zima ceny ogolnie wyzsze (mniejsza produkcja PV, wieksze zuzycie)
- Ceny MOGA BYC UJEMNE (np. 2025-01-01 mial -282 PLN/MWh o godzinie 10)

Ceny w PLN/MWh z PSE - przeliczane na PLN/kWh przy uzyciu.
"""

import json
import ssl
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path


# Sciezka do pliku cache z danymi RCE
CACHE_PATH = Path(__file__).parent.parent / "data" / "rce_cache.json"

# URL API PSE
PSE_API_URL = "https://api.raporty.pse.pl/api/rce-pln"

# Data poczatkowa dostepnosci danych w PSE
DATA_POCZATKOWA_PSE = "2024-06-14"


# Fallback - srednie godzinowe ceny RCE [PLN/MWh] dla kazdego miesiaca
# Uzywane gdy cache nie jest dostepny (np. brak dostepu do internetu)
# Dane reprezentatywne na podstawie historycznych notowan 2023-2024
CENY_RCE_GODZINOWE_PLN_MWH = [
    # Styczen - wysokie ceny, brak efektu PV
    [380, 350, 330, 320, 340, 380, 450, 520, 550, 530, 500, 480,
     470, 460, 470, 490, 530, 580, 600, 560, 500, 450, 420, 390],
    # Luty - podobnie do stycznia
    [360, 330, 310, 300, 320, 360, 430, 500, 530, 510, 480, 460,
     450, 440, 450, 470, 510, 560, 580, 540, 480, 430, 400, 370],
    # Marzec - poczatek efektu PV w poludnie
    [320, 290, 270, 260, 280, 320, 390, 450, 470, 440, 400, 370,
     350, 340, 350, 380, 430, 490, 520, 480, 420, 380, 350, 330],
    # Kwiecien - wyrazny efekt PV
    [280, 250, 230, 220, 240, 270, 340, 390, 380, 340, 290, 260,
     240, 230, 250, 290, 370, 430, 460, 420, 370, 330, 300, 280],
    # Maj - silny efekt PV, niskie ceny w poludnie
    [250, 220, 200, 190, 210, 240, 300, 340, 310, 260, 210, 180,
     160, 150, 170, 220, 310, 380, 410, 380, 330, 290, 270, 250],
    # Czerwiec - najsilniejszy efekt PV, najnizsze ceny poludniowe
    [230, 200, 180, 170, 190, 220, 270, 310, 270, 220, 170, 140,
     120, 110, 130, 180, 280, 360, 390, 360, 310, 270, 250, 230],
    # Lipiec - bardzo silny efekt PV
    [240, 210, 190, 180, 200, 230, 280, 320, 280, 230, 180, 150,
     130, 120, 140, 190, 290, 370, 400, 370, 320, 280, 260, 240],
    # Sierpien - silny efekt PV ale krotsze dni
    [260, 230, 210, 200, 220, 250, 310, 350, 320, 270, 220, 190,
     170, 160, 180, 230, 320, 390, 420, 380, 340, 300, 280, 260],
    # Wrzesien - malejacy efekt PV
    [300, 270, 250, 240, 260, 290, 360, 410, 400, 360, 320, 290,
     270, 260, 280, 320, 390, 450, 480, 440, 390, 350, 320, 300],
    # Pazdziernik - slaby efekt PV
    [340, 310, 290, 280, 300, 340, 410, 470, 480, 460, 430, 410,
     400, 390, 400, 430, 480, 540, 560, 520, 460, 410, 380, 350],
    # Listopad - minimalny efekt PV
    [370, 340, 320, 310, 330, 370, 440, 510, 540, 520, 490, 470,
     460, 450, 460, 480, 520, 570, 590, 550, 490, 440, 410, 380],
    # Grudzien - brak efektu PV, wysokie ceny
    [390, 360, 340, 330, 350, 390, 460, 530, 560, 540, 510, 490,
     480, 470, 480, 500, 540, 590, 610, 570, 510, 460, 430, 400],
]


# Globalny cache zaladowany z pliku (lazy loading)
_cache_dane: Optional[Dict] = None


def _utworz_ssl_context() -> ssl.SSLContext:
    """
    Tworzy kontekst SSL bez weryfikacji certyfikatu.

    UWAGA: Weryfikacja SSL jest celowo wylaczona dla API PSE (api.raporty.pse.pl).
    Powod: serwer PSE ma niepelny lancuch certyfikatow (brakujace certyfikaty posrednie),
    co powoduje bledy weryfikacji SSL w wielu srodowiskach (w tym na serwerze CI/CD
    oraz na czesci maszyn deweloperskich). Proba podpiecia certyfikatu CA lub bundla
    nie rozwiazuje problemu, poniewaz blad jest po stronie konfiguracji serwera PSE.

    Ryzyko: potencjalnie mozliwy atak MITM na sciezce do api.raporty.pse.pl.
    Akceptowalne poniewaz: (1) cache jest budowany jednorazowo i commitowany do repo,
    (2) dane RCE sa publiczne i weryfikowalne w innych zrodlach,
    (3) nie przesylamy danych wrażliwych.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def pobierz_dane_rce_z_pse(data_od: str, data_do: str, liczba_prob: int = 2) -> Dict[str, List[float]]:
    """
    Pobiera realne dane RCE z API PSE dzien po dniu.

    Parametry:
        data_od: data poczatkowa w formacie 'YYYY-MM-DD'
        data_do: data koncowa w formacie 'YYYY-MM-DD'
        liczba_prob: ile razy ponowic probe pobrania w razie bledu (domyslnie 2)

    Zwraca:
        Slownik {data: [24 srednich godzinowych w PLN/MWh]}
        Kazdy dzien ma liste 24 wartosci (srednia z 4 kwadransow na godzine).
    """
    import time

    ctx = _utworz_ssl_context()
    dane = {}
    pominiete_dni: List[str] = []

    dzien = datetime.strptime(data_od, "%Y-%m-%d")
    koniec = datetime.strptime(data_do, "%Y-%m-%d")

    while dzien <= koniec:
        data_str = dzien.strftime("%Y-%m-%d")
        pobrano = False

        # Ponawianie proby pobrania (domyslnie 2 proby z 1s opoznieniem)
        for proba in range(liczba_prob):
            try:
                rekordy = _pobierz_dzien_z_pse(data_str, ctx)
                if rekordy:
                    godzinowe = _agreguj_do_godzin(rekordy)
                    if len(godzinowe) == 24:
                        dane[data_str] = godzinowe
                        pobrano = True
                        break
                # Brak rekordow - nie ponawiamy (dzien jeszcze niedostepny)
                break
            except Exception:
                # Jesli to nie ostatnia proba, czekamy 1s przed ponowieniem
                if proba < liczba_prob - 1:
                    time.sleep(1.0)

        if not pobrano and data_str not in dane:
            pominiete_dni.append(data_str)

        dzien += timedelta(days=1)

    # Wypisz podsumowanie pominiietych dni (jesli sa)
    if pominiete_dni:
        print(f"[RCE] Pominieto {len(pominiete_dni)} dni bez danych: "
              f"{pominiete_dni[0]} ... {pominiete_dni[-1]}")
        if len(pominiete_dni) <= 10:
            print(f"[RCE] Pominiete daty: {', '.join(pominiete_dni)}")

    return dane


def _pobierz_dzien_z_pse(data: str, ctx: ssl.SSLContext) -> List[Dict]:
    """
    Pobiera dane RCE dla jednego dnia z API PSE.

    Parametry:
        data: data w formacie 'YYYY-MM-DD'
        ctx: kontekst SSL

    Zwraca:
        Lista rekordow z API (do 96 na dzien)
    """
    filter_str = f"business_date eq '{data}'"
    params = urllib.parse.urlencode({'$filter': filter_str})
    url = f"{PSE_API_URL}?{params}"

    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    resp = urllib.request.urlopen(req, context=ctx, timeout=15)
    raw = resp.read().decode('utf-8')
    data_json = json.loads(raw)

    return data_json.get('value', [])


def _agreguj_do_godzin(rekordy: List[Dict]) -> List[float]:
    """
    Agreguje 96 rekordow 15-minutowych do 24 srednich godzinowych.

    Kazda godzina to srednia z 4 kwadransow (np. 00:00-00:15, 00:15-00:30, ...).
    Ceny moga byc ujemne!

    Parametry:
        rekordy: lista rekordow z PSE (pole rce_pln w PLN/MWh)

    Zwraca:
        Lista 24 srednich godzinowych w PLN/MWh
    """
    # Pogrupuj rekordy wg godziny (na podstawie pola period "HH:MM - HH:MM")
    godziny: Dict[int, List[float]] = {h: [] for h in range(24)}

    for rekord in rekordy:
        cena = rekord.get('rce_pln')
        period = rekord.get('udtczas_obow', '') or rekord.get('period', '')

        if cena is None:
            continue

        # Wyodrebnij godzine z pola period (format "HH:MM - HH:MM")
        # Bierzemy poczatek interwalu
        try:
            if ' - ' in period:
                start_time = period.split(' - ')[0].strip()
                godzina = int(start_time.split(':')[0])
            elif ':' in period:
                godzina = int(period.split(':')[0])
            else:
                # Probujemy jako numer periodu (1-96)
                nr = int(period) if period.isdigit() else 0
                if 1 <= nr <= 96:
                    godzina = (nr - 1) // 4
                else:
                    continue
        except (ValueError, IndexError):
            continue

        if 0 <= godzina <= 23:
            godziny[godzina].append(float(cena))

    # Oblicz srednia dla kazdej godziny
    wynik = []
    for h in range(24):
        wartosci = godziny[h]
        if wartosci:
            wynik.append(sum(wartosci) / len(wartosci))
        else:
            wynik.append(0.0)

    return wynik


def zapisz_cache_rce(dane: Dict[str, List[float]], sciezka: Optional[Path] = None) -> None:
    """
    Zapisuje pobrane dane RCE do pliku cache JSON.

    Format cache:
    {
        "meta": {
            "data_pobrania": "YYYY-MM-DD HH:MM:SS",
            "zakres_od": "YYYY-MM-DD",
            "zakres_do": "YYYY-MM-DD"
        },
        "dane": {
            "2024-06-14": [h0, h1, ..., h23],
            ...
        }
    }

    Parametry:
        dane: slownik {data: [24 srednich godzinowych w PLN/MWh]}
        sciezka: sciezka do pliku (domyslnie CACHE_PATH)
    """
    if sciezka is None:
        sciezka = CACHE_PATH

    if not dane:
        return

    daty = sorted(dane.keys())
    cache = {
        "meta": {
            "data_pobrania": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "zakres_od": daty[0],
            "zakres_do": daty[-1],
        },
        "dane": dane,
    }

    sciezka.parent.mkdir(parents=True, exist_ok=True)
    with open(sciezka, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=None, separators=(',', ':'))


def wczytaj_cache_rce(sciezka: Optional[Path] = None) -> Optional[Dict[str, List[float]]]:
    """
    Wczytuje dane RCE z pliku cache.

    Parametry:
        sciezka: sciezka do pliku (domyslnie CACHE_PATH)

    Zwraca:
        Slownik {data: [24 srednich godzinowych w PLN/MWh]} lub None jesli brak cache
    """
    if sciezka is None:
        sciezka = CACHE_PATH

    if not sciezka.exists():
        return None

    try:
        with open(sciezka, "r", encoding="utf-8") as f:
            cache = json.load(f)
        return cache.get("dane", None)
    except (json.JSONDecodeError, IOError):
        return None


def _zaladuj_cache() -> Optional[Dict[str, List[float]]]:
    """
    Lazy loading cache - wczytuje z pliku przy pierwszym uzyciu.
    """
    global _cache_dane
    if _cache_dane is None:
        _cache_dane = wczytaj_cache_rce()
    return _cache_dane


def aktualizuj_cache_rce(data_od: Optional[str] = None, data_do: Optional[str] = None) -> int:
    """
    Aktualizuje cache RCE pobierajac dane z PSE.

    Parametry:
        data_od: data poczatkowa (domyslnie: DATA_POCZATKOWA_PSE)
        data_do: data koncowa (domyslnie: wczoraj)

    Zwraca:
        Liczba pobranych dni
    """
    global _cache_dane

    if data_od is None:
        data_od = DATA_POCZATKOWA_PSE
    if data_do is None:
        # Wczoraj - dzisiaj moze nie miec jeszcze pelnych danych
        data_do = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    dane = pobierz_dane_rce_z_pse(data_od, data_do)
    if dane:
        zapisz_cache_rce(dane)
        _cache_dane = dane

    return len(dane)


def _pobierz_srednia_godzinowa_z_cache(miesiac: int, godzina: int) -> Optional[float]:
    """
    Oblicza srednia cene RCE dla danego miesiaca i godziny z cache.

    Agreguje dane ze wszystkich dostepnych dni w danym miesiacu.
    Ceny moga byc ujemne!

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Srednia cena w PLN/MWh lub None jesli brak danych
    """
    dane = _zaladuj_cache()
    if dane is None:
        return None

    wartosci = []
    miesiac_str = f"-{miesiac:02d}-"

    for data_str, godziny in dane.items():
        # Sprawdz czy data nalezy do szukanego miesiaca
        if miesiac_str in data_str:
            if isinstance(godziny, list) and len(godziny) > godzina:
                wartosci.append(godziny[godzina])

    if not wartosci:
        return None

    return sum(wartosci) / len(wartosci)


def pobierz_cene_rce(miesiac: int, godzina: int) -> float:
    """
    Zwraca srednia cene RCE dla danego miesiaca i godziny.

    Uzywa realnych danych z cache PSE. Jesli cache niedostepny,
    korzysta z fallbackowych danych syntetycznych.

    Ceny MOGA BYC UJEMNE (nie sa clampowane do 0).

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Cena w PLN/kWh (brutto z VAT 23%)
    """
    # Probuj pobrac z realnego cache
    cena_mwh = _pobierz_srednia_godzinowa_z_cache(miesiac, godzina)

    # Fallback na dane syntetyczne
    if cena_mwh is None:
        cena_mwh = CENY_RCE_GODZINOWE_PLN_MWH[miesiac - 1][godzina]

    # Przeliczenie PLN/MWh na PLN/kWh + VAT 23%
    cena_kwh_netto = cena_mwh / 1000.0
    cena_kwh_brutto = cena_kwh_netto * 1.23
    return round(cena_kwh_brutto, 4)


def pobierz_ceny_rce_miesiac(miesiac: int) -> List[float]:
    """
    Zwraca 24 ceny RCE (jedna na godzine) dla danego miesiaca.

    Parametry:
        miesiac: numer miesiaca (1-12)

    Zwraca:
        Lista 24 cen w PLN/kWh (brutto)
    """
    return [pobierz_cene_rce(miesiac, g) for g in range(24)]


def pobierz_srednia_rce_miesiac(miesiac: int) -> float:
    """
    Zwraca srednia cene RCE dla calego miesiaca (srednia z 24h).

    Parametry:
        miesiac: numer miesiaca (1-12)

    Zwraca:
        Srednia cena w PLN/kWh (brutto)
    """
    ceny = pobierz_ceny_rce_miesiac(miesiac)
    return round(sum(ceny) / len(ceny), 4)


def pobierz_cene_rce_sprzedaz(miesiac: int, godzina: int) -> float:
    """
    Zwraca cene sprzedazy nadwyzki energii z PV po cenie RCE.

    Sprzedaz odbywa sie po cenie gieldowej RCE z danej godziny.
    To jest cena ktora prosumer otrzymuje za energie oddana do sieci.
    Cena MOZE BYC UJEMNA (prosumer placi za oddanie energii).

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Cena sprzedazy w PLN/kWh (netto - bez VAT, bo prosumer sprzedaje)
    """
    # Probuj pobrac z realnego cache
    cena_mwh = _pobierz_srednia_godzinowa_z_cache(miesiac, godzina)

    # Fallback na dane syntetyczne
    if cena_mwh is None:
        cena_mwh = CENY_RCE_GODZINOWE_PLN_MWH[miesiac - 1][godzina]

    # Prosumer sprzedaje po cenie netto (bez VAT)
    cena_kwh_netto = cena_mwh / 1000.0
    return round(cena_kwh_netto, 4)


def pobierz_statystyki_rce() -> Dict:
    """
    Zwraca statystyki cen RCE - srednie, min, max dla kazdego miesiaca.

    Przydatne do prezentacji uzytkownikowi oczekiwanych cen.

    Zwraca:
        Slownik ze statystykami cen RCE
    """
    statystyki = []

    for miesiac in range(1, 13):
        ceny = pobierz_ceny_rce_miesiac(miesiac)
        ceny_sprzedaz = [pobierz_cene_rce_sprzedaz(miesiac, g) for g in range(24)]

        statystyki.append({
            "miesiac": miesiac,
            "srednia_kupno_zl_kwh": round(sum(ceny) / len(ceny), 4),
            "min_kupno_zl_kwh": round(min(ceny), 4),
            "max_kupno_zl_kwh": round(max(ceny), 4),
            "srednia_sprzedaz_zl_kwh": round(sum(ceny_sprzedaz) / len(ceny_sprzedaz), 4),
            "min_sprzedaz_zl_kwh": round(min(ceny_sprzedaz), 4),
            "max_sprzedaz_zl_kwh": round(max(ceny_sprzedaz), 4),
            "godzina_najtanszej": ceny.index(min(ceny)),
            "godzina_najdrozszej": ceny.index(max(ceny)),
        })

    return {"miesiace": statystyki}
