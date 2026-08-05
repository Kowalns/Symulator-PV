"""
Serwis doboru magazynu energii (battery sizing).

Algorytm doboru:
1. Oblicza nadwyzke dzienna w kazdym miesiacu (energia PV niewykorzystana w ciagu dnia)
2. Oblicza niedobor wieczorny/nocny (energia potrzebna gdy slonce nie swieci)
3. Dobiera pojemnosc magazynu tak, aby pokryc wieczorny szczyt BEZ przewymiarowania
4. Proponuje konkretny model z bazy batteries_database.json
5. Uwzglednia sprawnosc roundtrip magazynu (85-95%)
6. Opcja: sprzedaz niezuzytej energii z magazynu latem w wybranej godzinie

WAZNE: Magazyn nie powinien byc przewymiarowany!
Celem jest pokrycie wieczornego szczytu zuzycia, a nie magazynowanie
calej nadwyzki letniej.
"""

import json
import math
import calendar
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field


# Sciezka do bazy baterii
BATTERIES_DB_PATH = Path(__file__).parent.parent / "data" / "batteries_database.json"

# Godziny dzienne (produkcja PV) i wieczorne (zuzycie bez PV)
GODZINY_DZIENNE = list(range(6, 18))    # 6:00 - 17:59
GODZINY_WIECZORNE = list(range(18, 24)) + list(range(0, 6))  # 18:00 - 5:59

# Profil solarny - udzial godzin w dziennej produkcji (normalizowany)
PROFIL_SOLARNY = [
    0.0, 0.0, 0.0, 0.0, 0.0, 0.01, 0.03, 0.06, 0.09, 0.12,
    0.14, 0.15, 0.15, 0.14, 0.12, 0.09, 0.06, 0.03, 0.01, 0.0,
    0.0, 0.0, 0.0, 0.0,
]

# Profil zuzycia domowego (udzial godzin w dziennym zuzyciu)
PROFIL_ZUZYCIA = [
    0.025, 0.020, 0.020, 0.020, 0.025, 0.030, 0.045, 0.055,
    0.060, 0.055, 0.045, 0.040, 0.040, 0.040, 0.040, 0.045,
    0.055, 0.065, 0.070, 0.065, 0.060, 0.050, 0.040, 0.030,
]


@dataclass
class WynikDoboruMagazynu:
    """
    Wynik algorytmu doboru magazynu energii.

    Atrybuty:
        rekomendowana_pojemnosc_kwh: rekomendowana pojemnosc [kWh]
        proponowany_model: dane modelu z bazy baterii
        nadwyzka_dzienna_kwh: srednia nadwyzka dzienna po miesiacach [kWh]
        niedobor_wieczorny_kwh: sredni niedobor wieczorny po miesiacach [kWh]
        pokrycie_wieczornego_szczytu_procent: jak dobrze magazyn pokrywa szczyt [%]
        uzasadnienie: tekstowe uzasadnienie doboru
    """
    rekomendowana_pojemnosc_kwh: float = 0.0
    proponowany_model: Optional[Dict] = None
    nadwyzka_dzienna_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    niedobor_wieczorny_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    pokrycie_wieczornego_szczytu_procent: float = 0.0
    uzasadnienie: str = ""


def wczytaj_baze_baterii() -> List[Dict]:
    """
    Wczytuje baze dostepnych magazynow energii.

    Zwraca:
        Lista slownikow z parametrami baterii
    """
    with open(BATTERIES_DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def oblicz_nadwyzke_i_niedobor_dzienny(
        produkcja_miesieczna_kwh: List[float],
        zuzycie_miesieczne_kwh: List[float],
        rok: int = 2025) -> Tuple[List[float], List[float]]:
    """
    Oblicza srednia nadwyzke dzienna i niedobor wieczorny w kazdym miesiacu.

    Nadwyzka dzienna: energia PV wyprodukowana w godzinach 6-18,
    ktora przekracza zuzycie w tych godzinach.

    Niedobor wieczorny: energia potrzebna w godzinach 18-6,
    ktora nie jest pokrywana przez PV (bo slonce nie swieci).

    Parametry:
        produkcja_miesieczna_kwh: produkcja miesieczna [kWh] (12 wartosci)
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        rok: rok do obliczen

    Zwraca:
        Tuple (nadwyzki_dzienne [12], niedobory_wieczorne [12]) w kWh/dzien
    """
    nadwyzki = []
    niedobory = []

    # Normalizacja profilu solarnego
    suma_solar = sum(PROFIL_SOLARNY)
    if suma_solar <= 0:
        suma_solar = 1.0

    # Normalizacja profilu zuzycia
    suma_zuzycia = sum(PROFIL_ZUZYCIA)
    if suma_zuzycia <= 0:
        suma_zuzycia = 1.0

    for miesiac in range(12):
        dni = calendar.monthrange(rok, miesiac + 1)[1]

        # Dzienna produkcja i zuzycie
        produkcja_dzienna_kwh = produkcja_miesieczna_kwh[miesiac] / dni
        zuzycie_dzienne_kwh = zuzycie_miesieczne_kwh[miesiac] / dni

        # Nadwyzka w godzinach dziennych
        nadwyzka_dzienna = 0.0
        for g in GODZINY_DZIENNE:
            prod_g = produkcja_dzienna_kwh * PROFIL_SOLARNY[g] / suma_solar
            zuz_g = zuzycie_dzienne_kwh * PROFIL_ZUZYCIA[g] / suma_zuzycia
            if prod_g > zuz_g:
                nadwyzka_dzienna += (prod_g - zuz_g)

        # Niedobor w godzinach wieczornych/nocnych
        niedobor_wieczorny = 0.0
        for g in GODZINY_WIECZORNE:
            prod_g = produkcja_dzienna_kwh * PROFIL_SOLARNY[g] / suma_solar
            zuz_g = zuzycie_dzienne_kwh * PROFIL_ZUZYCIA[g] / suma_zuzycia
            if zuz_g > prod_g:
                niedobor_wieczorny += (zuz_g - prod_g)

        nadwyzki.append(round(nadwyzka_dzienna, 3))
        niedobory.append(round(niedobor_wieczorny, 3))

    return nadwyzki, niedobory


def dobierz_pojemnosc_magazynu(
        nadwyzki_dzienne_kwh: List[float],
        niedobory_wieczorne_kwh: List[float],
        sprawnosc_procent: float = 95.0) -> float:
    """
    Dobiera optymalna pojemnosc magazynu.

    Strategia: magazyn pokrywa wieczorny szczyt w miesiacach przejsciowych
    (wrzesien-kwiecien), ale NIE jest wymiarowany na pelne pokrycie
    letnich nadwyzek (to byloby przewymiarowanie).

    Parametry:
        nadwyzki_dzienne_kwh: srednie nadwyzki dzienne [kWh/dzien] (12 wartosci)
        niedobory_wieczorne_kwh: srednie niedobory wieczorne [kWh/dzien] (12 wartosci)
        sprawnosc_procent: sprawnosc roundtrip [%]

    Zwraca:
        Rekomendowana pojemnosc magazynu [kWh]
    """
    sprawnosc = sprawnosc_procent / 100.0

    # Strategia: pokryj typowy wieczorny niedobor w miesiacach przejsciowych
    # Nie bierz letniej nadwyzki (przewymiarowanie!)
    # Nie bierz zimowego niedoboru (i tak nie starczy nadwyzki PV)

    # Miesiace przejsciowe: marzec-kwiecien, wrzesien-pazdziernik (ind. 2,3,8,9)
    miesiace_docelowe = [2, 3, 8, 9]

    # Oblicz efektywna pojemnosc potrzebna
    niedobory_docelowe = []
    nadwyzki_docelowe = []
    for m in miesiace_docelowe:
        niedobory_docelowe.append(niedobory_wieczorne_kwh[m])
        nadwyzki_docelowe.append(nadwyzki_dzienne_kwh[m])

    if not niedobory_docelowe:
        return 0.0

    # Pojemnosc = mediana niedoborow wieczornych w miesiacach docelowych
    # z korrekta na sprawnosc
    # Nie przekraczamy dostepnej nadwyzki dziennej (bo z czego ladownac?)
    niedobory_sorted = sorted(niedobory_docelowe)
    mediana_niedoboru = niedobory_sorted[len(niedobory_sorted) // 2]

    # Koryguj o sprawnosc - potrzebujemy wiecej pojemnosci bo tracimy na ladowaniu
    pojemnosc_potrzebna = mediana_niedoboru / sprawnosc

    # Ograniczenie: nie wiecej niz mediana nadwyzki (bo nie mamy czym ladowac)
    nadwyzki_sorted = sorted(nadwyzki_docelowe)
    mediana_nadwyzki = nadwyzki_sorted[len(nadwyzki_sorted) // 2]

    pojemnosc = min(pojemnosc_potrzebna, mediana_nadwyzki)

    # Zaokraglenie w gore do 0.5 kWh
    pojemnosc = math.ceil(pojemnosc * 2) / 2.0

    # Minimum 2 kWh (ponizej nie ma sensu ekonomicznie)
    if pojemnosc < 2.0 and pojemnosc > 0.5:
        pojemnosc = 2.0

    return round(pojemnosc, 1)


def znajdz_model_baterii(pojemnosc_kwh: float,
                          baterie: Optional[List[Dict]] = None) -> Optional[Dict]:
    """
    Znajduje najlepiej dopasowany model baterii z bazy.

    Wybiera model o pojemnosci >= wymaganej, ale najblizszej
    (nie przewymiarowany).

    Parametry:
        pojemnosc_kwh: wymagana pojemnosc [kWh]
        baterie: opcjonalna lista baterii (jesli None, wczyta z pliku)

    Zwraca:
        Slownik z danymi baterii lub None jesli brak odpowiedniego modelu
    """
    if baterie is None:
        baterie = wczytaj_baze_baterii()

    if pojemnosc_kwh <= 0:
        return None

    # Sortuj po pojemnosci rosnaco
    posortowane = sorted(baterie, key=lambda b: b["pojemnosc_kwh"])

    # Znajdz pierwszy model >= wymaganej pojemnosci
    for bat in posortowane:
        if bat["pojemnosc_kwh"] >= pojemnosc_kwh:
            return bat

    # Jesli zadna nie jest wystarczajaco duza, zwroc najwieksza
    if posortowane:
        return posortowane[-1]

    return None


def oblicz_oszczednosc_z_magazynu(
        niedobory_wieczorne_kwh: List[float],
        pojemnosc_kwh: float,
        sprawnosc_procent: float = 95.0,
        cena_kupna_kwh: float = 0.62) -> Dict:
    """
    Oblicza roczna oszczednosc z zastosowania magazynu energii.

    Oszczednosc = energia z magazynu * cena kupna z sieci
    (bo nie kupujemy z sieci tego co pokrywa magazyn)

    Parametry:
        niedobory_wieczorne_kwh: srednie niedobory wieczorne [kWh/dzien] (12)
        pojemnosc_kwh: pojemnosc magazynu [kWh]
        sprawnosc_procent: sprawnosc roundtrip [%]
        cena_kupna_kwh: srednia cena kupna energii [PLN/kWh]

    Zwraca:
        Slownik z oszczednosciami
    """
    sprawnosc = sprawnosc_procent / 100.0
    oszczednosc_roczna = 0.0

    for miesiac in range(12):
        dni = calendar.monthrange(2025, miesiac + 1)[1]
        niedobor = niedobory_wieczorne_kwh[miesiac]

        # Magazyn pokrywa tyle ile moze (ograniczony pojemnoscia i sprawnoscia)
        pokrycie = min(niedobor, pojemnosc_kwh * sprawnosc)
        oszczednosc_mc = pokrycie * dni * cena_kupna_kwh
        oszczednosc_roczna += oszczednosc_mc

    return {
        "oszczednosc_roczna_zl": round(oszczednosc_roczna, 2),
        "oszczednosc_miesieczna_zl": round(oszczednosc_roczna / 12, 2),
    }


def dobierz_magazyn(
        produkcja_miesieczna_kwh: List[float],
        zuzycie_miesieczne_kwh: List[float],
        godzina_sprzedazy: int = 18,
        rok: int = 2025) -> Dict:
    """
    Glowna funkcja doboru magazynu energii.

    Algorytm:
    1. Oblicza nadwyzke dzienna i niedobor wieczorny
    2. Dobiera optymalna pojemnosc (nie przewymiarowana!)
    3. Znajduje model z bazy baterii
    4. Oblicza oszczednosc roczna

    Parametry:
        produkcja_miesieczna_kwh: produkcja miesieczna [kWh] (12 wartosci)
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        godzina_sprzedazy: preferowana godzina sprzedazy nadwyzki (0-23)
        rok: rok do obliczen

    Zwraca:
        Slownik z wynikiem doboru magazynu
    """
    # 1. Oblicz nadwyzke i niedobor
    nadwyzki, niedobory = oblicz_nadwyzke_i_niedobor_dzienny(
        produkcja_miesieczna_kwh, zuzycie_miesieczne_kwh, rok
    )

    # 2. Wczytaj baze baterii
    baterie = wczytaj_baze_baterii()

    # Jesli baza jest pusta lub brak niedoboru, zwroc informacje
    if not baterie:
        return {
            "rekomendacja": "brak_danych",
            "opis": "Baza baterii jest pusta - brak modeli do porownania.",
            "nadwyzki_dzienne_kwh": nadwyzki,
            "niedobory_wieczorne_kwh": niedobory,
        }

    # Sprawdz czy w ogole potrzebny magazyn
    suma_niedoborow = sum(niedobory)
    if suma_niedoborow < 0.5:
        return {
            "rekomendacja": "nie_potrzebny",
            "opis": "Niedobor wieczorny jest znikomy - magazyn energii nie jest ekonomicznie uzasadniony.",
            "nadwyzki_dzienne_kwh": nadwyzki,
            "niedobory_wieczorne_kwh": niedobory,
        }

    # 3. Dobierz pojemnosc
    # Uzyj sredniej sprawnosci z bazy
    srednia_sprawnosc = sum(b["sprawnosc_roundtrip_procent"] for b in baterie) / len(baterie)
    pojemnosc = dobierz_pojemnosc_magazynu(nadwyzki, niedobory, srednia_sprawnosc)

    if pojemnosc <= 0:
        return {
            "rekomendacja": "nie_potrzebny",
            "opis": "Nadwyzka dzienna jest zbyt mala aby ekonomicznie uzasadnic magazyn.",
            "nadwyzki_dzienne_kwh": nadwyzki,
            "niedobory_wieczorne_kwh": niedobory,
        }

    # 4. Znajdz model
    model = znajdz_model_baterii(pojemnosc, baterie)

    # 5. Oblicz pokrycie wieczornego szczytu
    sprawnosc_modelu = model["sprawnosc_roundtrip_procent"] if model else srednia_sprawnosc
    pokrycie_procent = 0.0
    if model:
        # Srednie pokrycie niedoboru wieczornego w miesiacach przejsciowych
        miesiace_przejsciowe = [2, 3, 8, 9]
        pokrycia = []
        for m in miesiace_przejsciowe:
            if niedobory[m] > 0:
                efektywna_poj = model["pojemnosc_kwh"] * (sprawnosc_modelu / 100.0)
                p = min(1.0, efektywna_poj / niedobory[m]) * 100.0
                pokrycia.append(p)
        if pokrycia:
            pokrycie_procent = sum(pokrycia) / len(pokrycia)

    # 6. Oblicz oszczednosc
    oszczednosc = oblicz_oszczednosc_z_magazynu(
        niedobory,
        model["pojemnosc_kwh"] if model else pojemnosc,
        sprawnosc_modelu,
    )

    # 7. Uzasadnienie
    uzasadnienie = (
        f"Rekomendowana pojemnosc magazynu: {pojemnosc} kWh. "
        f"Pokrywa {round(pokrycie_procent, 0):.0f}% wieczornego szczytu "
        f"w miesiacach przejsciowych (marzec-kwiecien, wrzesien-pazdziernik). "
        f"Nie jest przewymiarowany - dobrany pod typowy niedobor wieczorny."
    )

    return {
        "rekomendacja": "zainstaluj",
        "rekomendowana_pojemnosc_kwh": pojemnosc,
        "proponowany_model": model,
        "nadwyzki_dzienne_kwh": nadwyzki,
        "niedobory_wieczorne_kwh": niedobory,
        "pokrycie_wieczornego_szczytu_procent": round(pokrycie_procent, 1),
        "oszczednosc": oszczednosc,
        "godzina_sprzedazy": godzina_sprzedazy,
        "uzasadnienie": uzasadnienie,
        "opcja_sprzedaz_latem": {
            "opis": (
                f"W miesiacach letnich (maj-sierpien) nadwyzka jest duza. "
                f"Mozna sprzedac energie z magazynu o godzinie {godzina_sprzedazy} "
                f"gdy ceny RCE sa wyzsze."
            ),
            "godzina_sprzedazy": godzina_sprzedazy,
        },
    }
