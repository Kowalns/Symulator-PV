"""
Serwis generowania raportu rocznego i miesiecznego instalacji PV.

Raport zawiera:
1. Produkcja roczna i miesieczna (kWh) z uwzglednieniem zacienienia
2. Straty vs identyczna instalacja bez zacienienia (%)
3. Bilans energetyczny miesieczny: produkcja, zuzycie, nadwyzka, niedobor
4. Samowystarczalnosc: w ilu miesiacach produkcja >= zuzycie (z magazynem)
5. Rekomendacje: zmiana kata nachylenia, pozycji paneli, orientacji
6. Wplyw degradacji 0.5%/rok na 25 lat
"""

import math
import calendar
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from backend.services.panel_performance import (
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    oblicz_wydajnosc_panela,
    NAPROMIENIOWANIE_SZCZYTOWE_POLSKA,
)
from backend.services.energy_profile import oblicz_zuzycie_miesieczne
from backend.services.economics import analizuj_ekonomie, KonfiguracjaMagazynu


# Degradacja domyslna paneli [%/rok]
DEGRADACJA_DOMYSLNA = 0.5

# Lata prognozy degradacji
LATA_PROGNOZY = 25


@dataclass
class KonfiguracjaRaportu:
    """
    Konfiguracja wejsciowa do generowania raportu.

    Atrybuty:
        produkcja_miesieczna_kwh: produkcja miesieczna z zacienieniem [kWh] (12 wartosci)
        produkcja_bez_zacienienia_kwh: produkcja miesieczna bez zacienienia [kWh] (12 wartosci)
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        pojemnosc_magazynu_kwh: pojemnosc uzyteczna magazynu [kWh]
        sprawnosc_magazynu_procent: sprawnosc roundtrip magazynu [%]
        kat_nachylenia: aktualny kat nachylenia paneli [stopnie]
        azymut: azymut instalacji [stopnie, 0=poludnie]
        moc_instalacji_kwp: laczna moc instalacji [kWp]
        degradacja_roczna_procent: roczna degradacja paneli [%]
        taryfa: nazwa taryfy
    """
    produkcja_miesieczna_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    produkcja_bez_zacienienia_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    zuzycie_miesieczne_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    pojemnosc_magazynu_kwh: float = 0.0
    sprawnosc_magazynu_procent: float = 95.0
    kat_nachylenia: float = 30.0
    azymut: float = 0.0
    moc_instalacji_kwp: float = 5.0
    degradacja_roczna_procent: float = DEGRADACJA_DOMYSLNA
    taryfa: str = "G11"


def oblicz_straty_zacienienia(produkcja_kwh: List[float],
                               produkcja_bez_zacienienia_kwh: List[float]) -> Dict:
    """
    Oblicza straty z powodu zacienienia - miesieczne i roczne.

    Parametry:
        produkcja_kwh: produkcja miesieczna z zacienieniem [kWh] (12 wartosci)
        produkcja_bez_zacienienia_kwh: produkcja bez zacienienia [kWh] (12 wartosci)

    Zwraca:
        Slownik ze stratami miesiecznymi i roczna
    """
    straty_miesieczne = []
    roczna_z_zacien = sum(produkcja_kwh)
    roczna_bez_zacien = sum(produkcja_bez_zacienienia_kwh)

    for i in range(12):
        if produkcja_bez_zacienienia_kwh[i] > 0:
            strata = (1.0 - produkcja_kwh[i] / produkcja_bez_zacienienia_kwh[i]) * 100.0
        else:
            strata = 0.0
        straty_miesieczne.append(round(strata, 2))

    strata_roczna = 0.0
    if roczna_bez_zacien > 0:
        strata_roczna = (1.0 - roczna_z_zacien / roczna_bez_zacien) * 100.0

    return {
        "straty_miesieczne_procent": straty_miesieczne,
        "strata_roczna_procent": round(strata_roczna, 2),
        "energia_utracona_rocznie_kwh": round(roczna_bez_zacien - roczna_z_zacien, 2),
    }


def oblicz_bilans_miesieczny(produkcja_kwh: List[float],
                              zuzycie_kwh: List[float],
                              pojemnosc_magazynu_kwh: float = 0.0,
                              sprawnosc_procent: float = 95.0) -> Dict:
    """
    Oblicza bilans energetyczny miesieczny: produkcja vs zuzycie.

    Uwzglednia magazyn energii - nadwyzka dzienna moze pokryc wieczorny niedobor.

    Parametry:
        produkcja_kwh: produkcja miesieczna [kWh] (12 wartosci)
        zuzycie_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        pojemnosc_magazynu_kwh: pojemnosc uzyteczna magazynu [kWh]
        sprawnosc_procent: sprawnosc roundtrip magazynu [%]

    Zwraca:
        Slownik z bilansem miesiecznym i wskaznikami samowystarczalnosci
    """
    sprawnosc = sprawnosc_procent / 100.0
    bilans_miesieczny = []
    miesiace_samowystarczalne = 0

    for i in range(12):
        prod = produkcja_kwh[i]
        zuz = zuzycie_kwh[i]
        nadwyzka = max(0.0, prod - zuz)
        niedobor = max(0.0, zuz - prod)

        # Magazyn pokrywa czesc niedoboru (jesli jest nadwyzka dzienna)
        pokrycie_magazynem = 0.0
        if pojemnosc_magazynu_kwh > 0 and nadwyzka > 0:
            # Magazyn moze przechowac nadwyzke z dnia na wieczor/noc
            # Ograniczenie: pojemnosc magazynu i sprawnosc
            energia_dostepna = min(nadwyzka, pojemnosc_magazynu_kwh * 30) * sprawnosc
            pokrycie_magazynem = min(energia_dostepna, niedobor)
        elif pojemnosc_magazynu_kwh > 0 and prod >= zuz:
            # Produkcja pokrywa zuzycie - magazyn pomaga w cyklach dziennych
            pokrycie_magazynem = 0.0

        bilans_netto = prod + pokrycie_magazynem - zuz
        samowystarczalny = bilans_netto >= 0

        if samowystarczalny:
            miesiace_samowystarczalne += 1

        bilans_miesieczny.append({
            "miesiac": i + 1,
            "produkcja_kwh": round(prod, 2),
            "zuzycie_kwh": round(zuz, 2),
            "nadwyzka_kwh": round(max(0.0, bilans_netto), 2),
            "niedobor_kwh": round(max(0.0, -bilans_netto), 2),
            "pokrycie_magazynem_kwh": round(pokrycie_magazynem, 2),
            "samowystarczalny": samowystarczalny,
        })

    return {
        "bilans_miesieczny": bilans_miesieczny,
        "miesiace_samowystarczalne": miesiace_samowystarczalne,
        "produkcja_roczna_kwh": round(sum(produkcja_kwh), 2),
        "zuzycie_roczne_kwh": round(sum(zuzycie_kwh), 2),
    }


def oblicz_projekcje_degradacji(produkcja_roczna_kwh: float,
                                 degradacja_roczna_procent: float = DEGRADACJA_DOMYSLNA,
                                 lata: int = LATA_PROGNOZY) -> List[Dict]:
    """
    Oblicza projekcje produkcji z uwzglednieniem degradacji paneli.

    Degradacja 0.5%/rok oznacza, ze po 25 latach panele produkuja ~88% oryginalnej mocy.

    Parametry:
        produkcja_roczna_kwh: produkcja w pierwszym roku [kWh]
        degradacja_roczna_procent: roczna degradacja [%]
        lata: liczba lat prognozy

    Zwraca:
        Lista slownikow z prognoza na kazdy rok
    """
    degradacja = degradacja_roczna_procent / 100.0
    prognoza = []

    for rok in range(1, lata + 1):
        wspolczynnik = (1.0 - degradacja) ** (rok - 1)
        produkcja = produkcja_roczna_kwh * wspolczynnik

        prognoza.append({
            "rok": rok,
            "wspolczynnik_degradacji": round(wspolczynnik, 4),
            "produkcja_kwh": round(produkcja, 2),
            "spadek_procent": round((1.0 - wspolczynnik) * 100.0, 2),
        })

    return prognoza


def _ocen_produkcje_dla_kata(kat: float, miesiac: int) -> float:
    """
    Szacuje wzgledna produkcje dla danego kata nachylenia w danym miesiacu.

    Wyzszy kat nachylenia = wieksza produkcja zima (niskie slonce),
    mniejsza produkcja latem (wysokie slonce).

    Parametry:
        kat: kat nachylenia [stopnie]
        miesiac: numer miesiaca (1-12)

    Zwraca:
        Wzgledna produkcja (1.0 = optymalna dla tego miesiaca)
    """
    # Srednie elewacje slonca w poludnie dla Polski (szer. ~52N)
    elewacje_poludniowe = [15, 20, 30, 42, 52, 58, 55, 47, 37, 26, 18, 13]
    elewacja = elewacje_poludniowe[miesiac - 1]

    # Optymalny kat nachylenia = 90 - elewacja slonca
    optymalny_kat = 90 - elewacja

    # Roznica od optimum - im wieksza, tym gorsza wydajnosc
    roznica = abs(kat - optymalny_kat)

    # Cosinus roznica - kazdy stopien od optimum to ok. 0.5% straty
    # (uproszczony model)
    wspolczynnik = math.cos(math.radians(roznica * 0.8))
    return max(0.3, wspolczynnik)


def generuj_rekomendacje(config: KonfiguracjaRaportu) -> List[Dict]:
    """
    Generuje rekomendacje optymalizacji instalacji.

    Analizuje:
    1. Kat nachylenia - czy wyzszy kat poprawi samowystarczalnosc jesienia
    2. Orientacja (azymut) - czy lekkie odchylenie moze pomoc
    3. Pozycja paneli - ogolne wskazowki

    Parametry:
        config: konfiguracja raportu

    Zwraca:
        Lista rekomendacji z opisem i prognozowanym efektem
    """
    rekomendacje = []
    produkcja = config.produkcja_miesieczna_kwh
    zuzycie = config.zuzycie_miesieczne_kwh
    kat = config.kat_nachylenia

    # Analiza jesienno-wiosennej samowystarczalnosci
    # Miesiace przejsciowe: marzec(3), kwiecien(4), wrzesien(9), pazdziernik(10)
    miesiace_przejsciowe = [2, 3, 8, 9]  # indeksy 0-based
    niedobory_przejsciowe = []
    for m in miesiace_przejsciowe:
        if m < len(produkcja) and m < len(zuzycie):
            if zuzycie[m] > produkcja[m]:
                niedobory_przejsciowe.append(m)

    # Rekomendacja 1: Zwiekszenie kata nachylenia
    if kat < 45 and niedobory_przejsciowe:
        # Oblicz szacowany zysk z wiekszego kata
        kat_nowy = min(kat + 10, 55)

        # Szacuj zmiane produkcji dla wyzszego kata
        zysk_jesien = 0.0
        strata_lato = 0.0
        for m in range(12):
            wsp_obecny = _ocen_produkcje_dla_kata(kat, m + 1)
            wsp_nowy = _ocen_produkcje_dla_kata(kat_nowy, m + 1)
            zmiana = (wsp_nowy - wsp_obecny) / max(wsp_obecny, 0.01)

            if m in [8, 9, 10]:  # wrzesien-listopad
                zysk_jesien += zmiana * produkcja[m]
            elif m in [5, 6]:  # czerwiec-lipiec
                strata_lato += zmiana * produkcja[m]

        if zysk_jesien > abs(strata_lato) * 0.3:
            rekomendacje.append({
                "typ": "kat_nachylenia",
                "priorytet": "wysoki",
                "opis": f"Zwieksz kat nachylenia z {kat} do {kat_nowy} stopni",
                "uzasadnienie": (
                    "Wyzszy kat nachylenia zwieksza produkcje w miesiacach "
                    "jesiennych i wiosennych (niskie slonce), co poprawia "
                    "samowystarczalnosc w okresie przejsciowym. "
                    f"Szacowany zysk jesienia: +{round(zysk_jesien, 1)} kWh."
                ),
                "szacowany_efekt": {
                    "zysk_jesien_kwh": round(zysk_jesien, 2),
                    "strata_lato_kwh": round(strata_lato, 2),
                    "nowy_kat": kat_nowy,
                },
            })

    # Rekomendacja 2: Orientacja
    azymut = config.azymut
    if abs(azymut) > 15:
        rekomendacje.append({
            "typ": "orientacja",
            "priorytet": "sredni",
            "opis": "Skoryguj azymut blizej poludnia (0 stopni)",
            "uzasadnienie": (
                f"Obecny azymut ({azymut} st.) odchyla instalacje od optymalnego "
                "polozenia poludniowego. Korekta do 0 stopni zwieksza "
                "calkowita roczna produkcje o 2-5%."
            ),
            "szacowany_efekt": {
                "obecny_azymut": azymut,
                "optymalny_azymut": 0,
            },
        })

    # Rekomendacja 3: Magazyn energii
    if config.pojemnosc_magazynu_kwh == 0:
        # Sprawdz czy jest nadwyzka w ciagu dnia i niedobor wieczorem
        suma_nadwyzek = sum(max(0, p - z) for p, z in zip(produkcja, zuzycie))
        suma_niedoborow = sum(max(0, z - p) for p, z in zip(produkcja, zuzycie))

        if suma_nadwyzek > 0 and suma_niedoborow > 0:
            rekomendacje.append({
                "typ": "magazyn_energii",
                "priorytet": "wysoki",
                "opis": "Zainstaluj magazyn energii",
                "uzasadnienie": (
                    "Instalacja generuje nadwyzke w ciagu dnia, ale ma niedobory "
                    "wieczorem/noca. Magazyn energii pozwoli przesunac nadwyzke "
                    "na godziny wieczorne, zwiekszajac samowystarczalnosc."
                ),
                "szacowany_efekt": {
                    "nadwyzka_roczna_kwh": round(suma_nadwyzek, 2),
                    "niedobor_roczny_kwh": round(suma_niedoborow, 2),
                },
            })

    # Rekomendacja 4: Straty zacienienia
    straty = oblicz_straty_zacienienia(
        config.produkcja_miesieczna_kwh,
        config.produkcja_bez_zacienienia_kwh,
    )
    if straty["strata_roczna_procent"] > 10:
        rekomendacje.append({
            "typ": "pozycja_paneli",
            "priorytet": "wysoki",
            "opis": "Zmien pozycje paneli aby zmniejszyc zacienienie",
            "uzasadnienie": (
                f"Straty z powodu zacienienia wynosza {straty['strata_roczna_procent']}% rocznie "
                f"({straty['energia_utracona_rocznie_kwh']} kWh). "
                "Rozwaznie przesuniecie paneli dalej od zrodla cienia lub "
                "zmniejszenie liczby rzedow."
            ),
            "szacowany_efekt": {
                "strata_obecna_procent": straty["strata_roczna_procent"],
                "energia_do_odzyskania_kwh": straty["energia_utracona_rocznie_kwh"],
            },
        })
    elif straty["strata_roczna_procent"] > 5:
        rekomendacje.append({
            "typ": "pozycja_paneli",
            "priorytet": "sredni",
            "opis": "Rozwaznie optymalizatory mocy lub zmiane pozycji paneli",
            "uzasadnienie": (
                f"Straty zacienienia ({straty['strata_roczna_procent']}%) sa umiarkowane. "
                "Optymalizatory mocy (np. SolarEdge, Tigo) zmniejsza wplyw "
                "zacienienia na caly string paneli."
            ),
            "szacowany_efekt": {
                "strata_obecna_procent": straty["strata_roczna_procent"],
            },
        })

    return rekomendacje


def generuj_raport(config: KonfiguracjaRaportu) -> Dict:
    """
    Generuje kompletny raport roczny i miesieczny instalacji PV.

    Raport zawiera:
    - Produkcja roczna/miesieczna z zacienieniem
    - Straty vs instalacja bez zacienienia
    - Bilans energetyczny (produkcja vs zuzycie)
    - Samowystarczalnosc miesieczna
    - Rekomendacje optymalizacji
    - Projekcja degradacji na 25 lat

    Parametry:
        config: konfiguracja raportu (KonfiguracjaRaportu)

    Zwraca:
        Slownik z kompletnym raportem
    """
    # 1. Straty zacienienia
    straty = oblicz_straty_zacienienia(
        config.produkcja_miesieczna_kwh,
        config.produkcja_bez_zacienienia_kwh,
    )

    # 2. Bilans energetyczny
    bilans = oblicz_bilans_miesieczny(
        config.produkcja_miesieczna_kwh,
        config.zuzycie_miesieczne_kwh,
        config.pojemnosc_magazynu_kwh,
        config.sprawnosc_magazynu_procent,
    )

    # 3. Projekcja degradacji
    produkcja_roczna = sum(config.produkcja_miesieczna_kwh)
    degradacja = oblicz_projekcje_degradacji(
        produkcja_roczna,
        config.degradacja_roczna_procent,
        LATA_PROGNOZY,
    )

    # 4. Rekomendacje
    rekomendacje = generuj_rekomendacje(config)

    # 5. Podsumowanie
    zuzycie_roczne = sum(config.zuzycie_miesieczne_kwh)
    autarchia = 0.0
    if zuzycie_roczne > 0:
        autarchia = min(100.0, produkcja_roczna / zuzycie_roczne * 100.0)

    raport = {
        "podsumowanie": {
            "produkcja_roczna_kwh": round(produkcja_roczna, 2),
            "produkcja_bez_zacienienia_kwh": round(sum(config.produkcja_bez_zacienienia_kwh), 2),
            "zuzycie_roczne_kwh": round(zuzycie_roczne, 2),
            "autarchia_procent": round(autarchia, 1),
            "miesiace_samowystarczalne": bilans["miesiace_samowystarczalne"],
            "moc_instalacji_kwp": config.moc_instalacji_kwp,
            "kat_nachylenia": config.kat_nachylenia,
            "azymut": config.azymut,
            "pojemnosc_magazynu_kwh": config.pojemnosc_magazynu_kwh,
            "taryfa": config.taryfa,
        },
        "straty_zacienienia": straty,
        "bilans_miesieczny": bilans["bilans_miesieczny"],
        "degradacja_25_lat": degradacja,
        "rekomendacje": rekomendacje,
        "parametry": {
            "degradacja_roczna_procent": config.degradacja_roczna_procent,
            "sprawnosc_magazynu_procent": config.sprawnosc_magazynu_procent,
            "lata_prognozy": LATA_PROGNOZY,
        },
    }

    return raport
