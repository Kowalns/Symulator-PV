"""
Serwis budowania profilu zuzycia energii elektrycznej.

Profil godzinowy zuzycia tworzony jest na podstawie:
1. Bazowe zuzycie (standby) - stale calodobowo (lodowka, router, czuwanie)
2. Dodatkowe zuzycie przypisane do godzin (gotowanie, pralka, zmywarka itp.)
3. Oddzielne profile dla dni roboczych i wolnych
4. Sezonowosc miesieczna (np. oswietlenie zima)
5. Ogrzewanie pompa ciepla (pazdziernik-kwiecien)
6. Podgrzewanie wody pompa ciepla (caly rok)

Wynik: 8760 wartosci (godzin w roku) zuzycia w Wh.
"""

import math
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import calendar


# Wspolczynniki sezonowosci - wyzsze zuzycie zima (oswietlenie, wentylacja)
# Indeks 0 = styczen, 11 = grudzien
SEZONOWOSC_MIESIECZNA = [1.15, 1.10, 1.05, 0.95, 0.90, 0.85,
                          0.85, 0.85, 0.95, 1.05, 1.10, 1.15]

# Miesiace grzewcze (pompa ciepla do ogrzewania)
MIESIACE_GRZEWCZE = [1, 2, 3, 4, 10, 11, 12]  # styczen-kwiecien, pazdziernik-grudzien

# Rozklad zuzycia pompy ciepla na ogrzewanie w poszczegolnych miesiacach
# (proporcjonalny do zapotrzebowania na cieplo)
ROZKLAD_OGRZEWANIA = {
    1: 0.20,   # styczen - duze zapotrzebowanie
    2: 0.18,   # luty
    3: 0.14,   # marzec
    4: 0.08,   # kwiecien - niewielkie
    10: 0.10,  # pazdziernik
    11: 0.14,  # listopad
    12: 0.16,  # grudzien
}

# Godziny typowej pracy pompy ciepla (ogrzewanie) - rozlozone w ciagu dnia
GODZINY_POMPY_OGRZEWANIE = list(range(0, 24))  # caly dzien, modulowane

# Rozklad godzinowy pracy pompy ciepla (wyzsze zuzycie rano i wieczorem)
# Profil jest znormalizowany - sumuje sie do 1.0
# Kazda wartosc = udzial danej godziny w dziennym zuzyciu na ogrzewanie
_PROFIL_CO_RAW = [
    0.04, 0.04, 0.04, 0.04, 0.05, 0.05, 0.06, 0.06,  # 0-7
    0.05, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03, 0.04,  # 8-15
    0.05, 0.05, 0.06, 0.06, 0.05, 0.05, 0.04, 0.04,  # 16-23
]
_SUMA_CO = sum(_PROFIL_CO_RAW)
PROFIL_GODZINOWY_POMPY_CO = [v / _SUMA_CO for v in _PROFIL_CO_RAW]

# Profil godzinowy podgrzewania CWU (glownie rano i wieczorem)
# Profil jest znormalizowany - sumuje sie do 1.0
_PROFIL_CWU_RAW = [
    0.02, 0.01, 0.01, 0.01, 0.02, 0.04, 0.08, 0.10,  # 0-7
    0.08, 0.06, 0.04, 0.03, 0.03, 0.03, 0.03, 0.04,  # 8-15
    0.05, 0.06, 0.08, 0.08, 0.07, 0.05, 0.04, 0.03,  # 16-23
]
_SUMA_CWU = sum(_PROFIL_CWU_RAW)
PROFIL_GODZINOWY_CWU = [v / _SUMA_CWU for v in _PROFIL_CWU_RAW]

# Wspolczynniki sezonowosci CWU - zima wiecej (woda na wejsciu zimniejsza)
# Indeks 0 = styczen, 11 = grudzien
# Znormalizowane tak aby srednia = 1.0 (suma = 12)
_SEZONOWOSC_CWU_RAW = [1.2, 1.15, 1.1, 1.0, 0.85, 0.85,
                        0.85, 0.85, 0.85, 1.0, 1.1, 1.2]
_SUMA_SEZONOWOSC_CWU = sum(_SEZONOWOSC_CWU_RAW)
SEZONOWOSC_CWU = [v * 12.0 / _SUMA_SEZONOWOSC_CWU for v in _SEZONOWOSC_CWU_RAW]


@dataclass
class ProfilZuzycia:
    """
    Konfiguracja profilu zuzycia energii.

    Atrybuty:
        zuzycie_bazowe_w: stale zuzycie domu (standby) [W]
        zuzycie_godzinowe_roboczy: dodatkowe zuzycie [Wh] w dniach roboczych (24 wartosci)
        zuzycie_godzinowe_wolny: dodatkowe zuzycie [Wh] w dniach wolnych (24 wartosci)
        pompa_ciepla_co: czy dom jest ogrzewany pompa ciepla
        zuzycie_co_roczne_kwh: roczne zuzycie energii na ogrzewanie [kWh]
        pompa_ciepla_cwu: czy woda podgrzewana pompa ciepla
        zuzycie_cwu_roczne_kwh: roczne zuzycie energii na CWU [kWh]
        moc_pompy_ciepla_kw: moc elektryczna pompy ciepla [kW] (do optymalizacji godzinowej)
        zuzycie_miesieczne_kwh: opcjonalne miesieczne zuzycie do kalibracji (12 wartosci)
    """
    zuzycie_bazowe_w: float = 200.0
    zuzycie_godzinowe_roboczy: List[float] = field(default_factory=lambda: [0.0] * 24)
    zuzycie_godzinowe_wolny: List[float] = field(default_factory=lambda: [0.0] * 24)
    pompa_ciepla_co: bool = False
    zuzycie_co_roczne_kwh: float = 0.0
    pompa_ciepla_cwu: bool = False
    zuzycie_cwu_roczne_kwh: float = 0.0
    moc_pompy_ciepla_kw: float = 0.0
    zuzycie_miesieczne_kwh: Optional[List[float]] = None


def czy_dzien_wolny(rok: int, miesiac: int, dzien: int) -> bool:
    """
    Sprawdza czy dany dzien jest dniem wolnym (sobota/niedziela).

    Parametry:
        rok: rok (np. 2025)
        miesiac: miesiac (1-12)
        dzien: dzien miesiaca (1-31)

    Zwraca:
        True jesli sobota lub niedziela
    """
    # weekday(): 0=poniedzialek, 5=sobota, 6=niedziela
    import datetime
    dzien_tygodnia = datetime.date(rok, miesiac, dzien).weekday()
    return dzien_tygodnia >= 5


def oblicz_profil_godzinowy(profil: ProfilZuzycia, rok: int = 2025, taryfa: Optional[str] = None) -> List[float]:
    """
    Oblicza godzinowe zuzycie energii dla calego roku (8760 wartosci).

    Algorytm:
    1. Dla kazdej godziny roku oblicza bazowe zuzycie (standby)
    2. Dodaje zuzycie z profilu godzinowego (roboczy/wolny)
    3. Aplikuje sezonowosc miesieczna
    4. Dodaje zuzycie pompy ciepla na ogrzewanie (jesli wlaczona)
    5. Dodaje zuzycie pompy ciepla na CWU (jesli wlaczona)

    Dla taryf dynamicznych (G11f_dynamiczna, G11_dynamiczna) i moc_pompy_ciepla_kw > 0:
    - Koncentruje pobor pompy ciepla w najtanszych godzinach RCE danego dnia
    - Liczba godzin pracy = ceil(dzienne_zapotrzebowanie / moc_pompy_kw / 1000)
    - Pobor jest rownomiernie rozlozony na te godziny

    Parametry:
        profil: konfiguracja profilu zuzycia
        rok: rok do obliczen (wplyw na kalendarz dni wolnych)
        taryfa: nazwa taryfy (None/'G11' = rownomierny rozklad,
                'G11f_dynamiczna'/'G11_dynamiczna' = optymalizacja cenowa)

    Zwraca:
        Lista 8760 wartosci zuzycia w Wh (watogodziny) dla kazdej godziny roku
    """
    from backend.services.rce_prices import pobierz_cene_rce

    # Sprawdz czy uzywamy optymalizacji cenowej dla pompy ciepla
    taryfy_dynamiczne = ("G11f_dynamiczna", "G11_dynamiczna")
    optymalizacja_cenowa = (
        taryfa in taryfy_dynamiczne
        and profil.moc_pompy_ciepla_kw > 0
        and (profil.pompa_ciepla_co or profil.pompa_ciepla_cwu)
    )

    wynik = []
    godzina_roku = 0

    for miesiac in range(1, 13):
        dni_w_miesiacu = calendar.monthrange(rok, miesiac)[1]
        sezonowosc = SEZONOWOSC_MIESIECZNA[miesiac - 1]

        # Zuzycie pompy ciepla CO w tym miesiacu
        zuzycie_co_miesiac_wh = 0.0
        if profil.pompa_ciepla_co and miesiac in MIESIACE_GRZEWCZE:
            udzial = ROZKLAD_OGRZEWANIA.get(miesiac, 0.0)
            zuzycie_co_miesiac_wh = profil.zuzycie_co_roczne_kwh * 1000.0 * udzial

        # Zuzycie CWU w tym miesiacu (z sezonowoscia - zima wiecej)
        zuzycie_cwu_miesiac_wh = 0.0
        if profil.pompa_ciepla_cwu:
            zuzycie_cwu_miesiac_wh = (profil.zuzycie_cwu_roczne_kwh * 1000.0 / 12.0
                                      * SEZONOWOSC_CWU[miesiac - 1])

        # Przygotuj optymalizacje cenowa dla tego miesiaca (jesli aktywna)
        godziny_pracy_co = None
        godziny_pracy_cwu = None
        zuzycie_co_na_godzine_wh = 0.0
        zuzycie_cwu_na_godzine_wh = 0.0

        if optymalizacja_cenowa:
            # Pobierz ceny RCE dla tego miesiaca i posortuj godziny wg ceny
            ceny_godzinowe = [(g, pobierz_cene_rce(miesiac, g)) for g in range(24)]
            ceny_posortowane = sorted(ceny_godzinowe, key=lambda x: x[1])

            moc_pompy_wh = profil.moc_pompy_ciepla_kw * 1000.0

            # Optymalizacja CO
            if profil.pompa_ciepla_co and miesiac in MIESIACE_GRZEWCZE and zuzycie_co_miesiac_wh > 0:
                dzienne_zapotrzebowanie_co_wh = zuzycie_co_miesiac_wh / dni_w_miesiacu
                godziny_potrzebne_co = math.ceil(dzienne_zapotrzebowanie_co_wh / moc_pompy_wh)
                godziny_potrzebne_co = min(godziny_potrzebne_co, 24)
                godziny_pracy_co = set(g for g, _ in ceny_posortowane[:godziny_potrzebne_co])
                zuzycie_co_na_godzine_wh = dzienne_zapotrzebowanie_co_wh / godziny_potrzebne_co

            # Optymalizacja CWU
            if profil.pompa_ciepla_cwu and zuzycie_cwu_miesiac_wh > 0:
                dzienne_zapotrzebowanie_cwu_wh = zuzycie_cwu_miesiac_wh / dni_w_miesiacu
                godziny_potrzebne_cwu = math.ceil(dzienne_zapotrzebowanie_cwu_wh / moc_pompy_wh)
                godziny_potrzebne_cwu = min(godziny_potrzebne_cwu, 24)
                godziny_pracy_cwu = set(g for g, _ in ceny_posortowane[:godziny_potrzebne_cwu])
                zuzycie_cwu_na_godzine_wh = dzienne_zapotrzebowanie_cwu_wh / godziny_potrzebne_cwu

        for dzien in range(1, dni_w_miesiacu + 1):
            wolny = czy_dzien_wolny(rok, miesiac, dzien)

            for godzina in range(24):
                # 1. Zuzycie bazowe (standby) - W zamieniane na Wh (1h)
                zuzycie_wh = profil.zuzycie_bazowe_w * sezonowosc

                # 2. Dodatkowe zuzycie z profilu godzinowego
                if wolny:
                    zuzycie_wh += profil.zuzycie_godzinowe_wolny[godzina] * sezonowosc
                else:
                    zuzycie_wh += profil.zuzycie_godzinowe_roboczy[godzina] * sezonowosc

                # 3. Pompa ciepla - ogrzewanie (CO)
                if profil.pompa_ciepla_co and miesiac in MIESIACE_GRZEWCZE:
                    if optymalizacja_cenowa and godziny_pracy_co is not None:
                        # Optymalizacja cenowa - zuzycie tylko w najtanszych godzinach
                        if godzina in godziny_pracy_co:
                            zuzycie_wh += zuzycie_co_na_godzine_wh
                    else:
                        # Standardowy profil rownomierny
                        wsp_godziny = PROFIL_GODZINOWY_POMPY_CO[godzina]
                        zuzycie_wh += (zuzycie_co_miesiac_wh / dni_w_miesiacu) * wsp_godziny

                # 4. Pompa ciepla - CWU
                if profil.pompa_ciepla_cwu:
                    if optymalizacja_cenowa and godziny_pracy_cwu is not None:
                        # Optymalizacja cenowa - zuzycie tylko w najtanszych godzinach
                        if godzina in godziny_pracy_cwu:
                            zuzycie_wh += zuzycie_cwu_na_godzine_wh
                    else:
                        # Standardowy profil rownomierny
                        wsp_godziny_cwu = PROFIL_GODZINOWY_CWU[godzina]
                        zuzycie_wh += (zuzycie_cwu_miesiac_wh / dni_w_miesiacu) * wsp_godziny_cwu

                wynik.append(round(zuzycie_wh, 2))
                godzina_roku += 1

    return wynik


def oblicz_zuzycie_miesieczne(profil_godzinowy: List[float], rok: int = 2025) -> List[float]:
    """
    Sumuje zuzycie godzinowe do wartosci miesiecznych.

    Parametry:
        profil_godzinowy: lista 8760 wartosci zuzycia w Wh
        rok: rok

    Zwraca:
        Lista 12 wartosci zuzycia w kWh (dla kazdego miesiaca)
    """
    wynik = []
    indeks = 0

    for miesiac in range(1, 13):
        dni = calendar.monthrange(rok, miesiac)[1]
        godziny = dni * 24
        suma_wh = sum(profil_godzinowy[indeks:indeks + godziny])
        wynik.append(round(suma_wh / 1000.0, 2))
        indeks += godziny

    return wynik


def stworz_profil_z_danych(dane: dict) -> ProfilZuzycia:
    """
    Tworzy obiekt ProfilZuzycia z danych wejsciowych (JSON z API).

    Parametry:
        dane: slownik z danymi profilu

    Zwraca:
        Obiekt ProfilZuzycia
    """
    zuzycie_roboczy = dane.get("zuzycie_godzinowe_roboczy", [0.0] * 24)
    zuzycie_wolny = dane.get("zuzycie_godzinowe_wolny", [0.0] * 24)

    # Upewnienie sie ze mamy 24 wartosci
    if len(zuzycie_roboczy) < 24:
        zuzycie_roboczy.extend([0.0] * (24 - len(zuzycie_roboczy)))
    if len(zuzycie_wolny) < 24:
        zuzycie_wolny.extend([0.0] * (24 - len(zuzycie_wolny)))

    zuzycie_miesieczne = dane.get("zuzycie_miesieczne_kwh", None)
    if zuzycie_miesieczne and len(zuzycie_miesieczne) < 12:
        zuzycie_miesieczne.extend([0.0] * (12 - len(zuzycie_miesieczne)))

    return ProfilZuzycia(
        zuzycie_bazowe_w=float(dane.get("zuzycie_bazowe_w", 200.0)),
        zuzycie_godzinowe_roboczy=[float(x) for x in zuzycie_roboczy[:24]],
        zuzycie_godzinowe_wolny=[float(x) for x in zuzycie_wolny[:24]],
        pompa_ciepla_co=bool(dane.get("pompa_ciepla_co", False)),
        zuzycie_co_roczne_kwh=float(dane.get("zuzycie_co_roczne_kwh", 0.0)),
        pompa_ciepla_cwu=bool(dane.get("pompa_ciepla_cwu", False)),
        zuzycie_cwu_roczne_kwh=float(dane.get("zuzycie_cwu_roczne_kwh", 0.0)),
        moc_pompy_ciepla_kw=float(dane.get("moc_pompy_ciepla_kw", 0.0)),
        zuzycie_miesieczne_kwh=zuzycie_miesieczne,
    )
