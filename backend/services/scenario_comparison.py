"""
Serwis porownania scenariuszy instalacji PV side-by-side.

Porownywane scenariusze:
1. Bazowy (bez PV) - pelne zuzycie z sieci
2. PV bez magazynu - nadwyzka sprzedawana po RCE
3. PV z magazynem - nadwyzka buforowana, wieczor pokrywany z magazynu
4. Rozne katy nachylenia (30/40/50 stopni) - wplyw na sezonowosc
5. Z optymalizatorami vs bez - wplyw na straty mismatch
6. Porownanie taryf G11 vs G11f vs dynamiczna

Wynik: tabela side-by-side z kosztami rocznymi, oszczednosciami, ROI,
liczbq miesiecy samowystarczalnosci.
"""

import math
import calendar
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from backend.services.economics import (
    analizuj_ekonomie,
    KonfiguracjaMagazynu,
    wczytaj_taryfy,
    oblicz_cene_kupna,
    oblicz_oplaty_stale,
)
from backend.services.energy_profile import oblicz_zuzycie_miesieczne
from backend.services.panel_performance import (
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    oblicz_wydajnosc_panela,
    NAPROMIENIOWANIE_SZCZYTOWE_POLSKA,
)
from backend.services.report_generator import (
    oblicz_bilans_miesieczny,
    _ocen_produkcje_dla_kata,
)
from backend.services.rce_prices import pobierz_cene_rce_sprzedaz


@dataclass
class KonfiguracjaScenariusza:
    """
    Konfiguracja pojedynczego scenariusza do porownania.

    Atrybuty:
        nazwa: nazwa scenariusza (np. "PV bez magazynu")
        produkcja_miesieczna_kwh: produkcja miesieczna [kWh] (12 wartosci)
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        taryfa: nazwa taryfy ("G11", "G11f", "dynamiczna")
        magazyn: konfiguracja magazynu (None = brak)
        kat_nachylenia: kat nachylenia paneli [stopnie]
        z_optymalizatorami: czy z optymalizatorami mocy
        koszt_instalacji_zl: calkowity koszt instalacji [PLN]
    """
    nazwa: str = ""
    produkcja_miesieczna_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    zuzycie_miesieczne_kwh: List[float] = field(default_factory=lambda: [0.0] * 12)
    taryfa: str = "G11"
    magazyn: Optional[KonfiguracjaMagazynu] = None
    kat_nachylenia: float = 30.0
    z_optymalizatorami: bool = False
    koszt_instalacji_zl: float = 0.0


def _rozloz_produkcje_na_godziny(energia_miesieczna_kwh: List[float],
                                   rok: int = 2025) -> List[float]:
    """
    Rozklada miesieczna produkcje PV na godziny (profil solarny).

    Parametry:
        energia_miesieczna_kwh: 12 wartosci produkcji [kWh]
        rok: rok do obliczen

    Zwraca:
        Lista 8760 wartosci produkcji w Wh
    """
    # Profil godzinowy produkcji solarnej (normalizowany do sumy 1.0)
    profil_solarny = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.01, 0.03, 0.06, 0.09, 0.12,
        0.14, 0.15, 0.15, 0.14, 0.12, 0.09, 0.06, 0.03, 0.01, 0.0,
        0.0, 0.0, 0.0, 0.0,
    ]
    suma_profilu = sum(profil_solarny)
    if suma_profilu > 0:
        profil_solarny = [p / suma_profilu for p in profil_solarny]

    wynik = []
    for miesiac in range(1, 13):
        energia_mc_kwh = energia_miesieczna_kwh[miesiac - 1]
        dni = calendar.monthrange(rok, miesiac)[1]
        energia_dzien_wh = (energia_mc_kwh * 1000.0) / dni if dni > 0 else 0.0

        for dzien in range(dni):
            for godzina in range(24):
                produkcja_wh = energia_dzien_wh * profil_solarny[godzina]
                wynik.append(round(produkcja_wh, 2))

    return wynik


def _rozloz_zuzycie_na_godziny(zuzycie_miesieczne_kwh: List[float],
                                 rok: int = 2025) -> List[float]:
    """
    Rozklada miesieczne zuzycie na godziny (profil zuzycia domowego).

    Parametry:
        zuzycie_miesieczne_kwh: 12 wartosci zuzycia [kWh]
        rok: rok

    Zwraca:
        Lista 8760 wartosci zuzycia w Wh
    """
    # Profil godzinowy zuzycia domowego
    profil_zuzycia = [
        0.025, 0.020, 0.020, 0.020, 0.025, 0.030, 0.045, 0.055,
        0.060, 0.055, 0.045, 0.040, 0.040, 0.040, 0.040, 0.045,
        0.055, 0.065, 0.070, 0.065, 0.060, 0.050, 0.040, 0.030,
    ]
    suma_profilu = sum(profil_zuzycia)
    if suma_profilu > 0:
        profil_zuzycia = [p / suma_profilu for p in profil_zuzycia]

    wynik = []
    for miesiac in range(1, 13):
        zuzycie_mc_kwh = zuzycie_miesieczne_kwh[miesiac - 1]
        dni = calendar.monthrange(rok, miesiac)[1]
        zuzycie_dzien_wh = (zuzycie_mc_kwh * 1000.0) / dni if dni > 0 else 0.0

        for dzien in range(dni):
            for godzina in range(24):
                zuzycie_wh = zuzycie_dzien_wh * profil_zuzycia[godzina]
                wynik.append(round(zuzycie_wh, 2))

    return wynik


def oblicz_scenariusz_bazowy(zuzycie_miesieczne_kwh: List[float],
                              taryfa: str = "G11",
                              rok: int = 2025) -> Dict:
    """
    Oblicza scenariusz bazowy - pelne zuzycie z sieci (bez PV).

    Parametry:
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12 wartosci)
        taryfa: nazwa taryfy
        rok: rok

    Zwraca:
        Slownik z kosztami rocznymi
    """
    zuzycie_godzinowe = _rozloz_zuzycie_na_godziny(zuzycie_miesieczne_kwh, rok)
    produkcja_zero = [0.0] * len(zuzycie_godzinowe)

    wynik = analizuj_ekonomie(
        produkcja_godzinowa_wh=produkcja_zero,
        zuzycie_godzinowe_wh=zuzycie_godzinowe,
        taryfa=taryfa,
        magazyn=None,
        rok=rok,
    )

    return wynik


def oblicz_scenariusz(config: KonfiguracjaScenariusza, rok: int = 2025) -> Dict:
    """
    Oblicza wyniki dla jednego scenariusza.

    Parametry:
        config: konfiguracja scenariusza
        rok: rok analizy

    Zwraca:
        Slownik z wynikami (koszty, oszczednosci, ROI, samowystarczalnosc)
    """
    # Rozloz produkcje i zuzycie na godziny
    produkcja_godzinowa = _rozloz_produkcje_na_godziny(
        config.produkcja_miesieczna_kwh, rok
    )
    zuzycie_godzinowe = _rozloz_zuzycie_na_godziny(
        config.zuzycie_miesieczne_kwh, rok
    )

    # Analiza ekonomiczna
    wynik_ekonomii = analizuj_ekonomie(
        produkcja_godzinowa_wh=produkcja_godzinowa,
        zuzycie_godzinowe_wh=zuzycie_godzinowe,
        taryfa=config.taryfa,
        magazyn=config.magazyn,
        rok=rok,
    )

    # Bilans miesieczny i samowystarczalnosc
    pojemnosc_mag = 0.0
    sprawnosc_mag = 95.0
    if config.magazyn:
        pojemnosc_mag = config.magazyn.pojemnosc_kwh
        sprawnosc_mag = config.magazyn.sprawnosc_procent

    bilans = oblicz_bilans_miesieczny(
        config.produkcja_miesieczna_kwh,
        config.zuzycie_miesieczne_kwh,
        pojemnosc_mag,
        sprawnosc_mag,
    )

    # ROI
    roczne = wynik_ekonomii["podsumowanie_roczne"]
    oszczednosc = roczne["oszczednosc_roczna_zl"]
    roi_lat = 0.0
    if oszczednosc > 0 and config.koszt_instalacji_zl > 0:
        roi_lat = config.koszt_instalacji_zl / oszczednosc

    return {
        "nazwa": config.nazwa,
        "taryfa": config.taryfa,
        "kat_nachylenia": config.kat_nachylenia,
        "z_optymalizatorami": config.z_optymalizatorami,
        "magazyn_kwh": pojemnosc_mag,
        "koszt_roczny_zl": roczne["koszt_calkowity_zl"],
        "oszczednosc_roczna_zl": oszczednosc,
        "przychod_sprzedazy_zl": roczne["przychod_sprzedazy_zl"],
        "koszt_kupna_zl": roczne["koszt_kupna_zl"],
        "autokonsumpcja_procent": roczne["autokonsumpcja_procent"],
        "autarchia_procent": roczne["autarchia_procent"],
        "produkcja_roczna_kwh": roczne["produkcja_kwh"],
        "zuzycie_roczne_kwh": roczne["zuzycie_kwh"],
        "miesiace_samowystarczalne": bilans["miesiace_samowystarczalne"],
        "roi_lat": round(roi_lat, 1),
        "koszt_instalacji_zl": config.koszt_instalacji_zl,
    }


def przeskaluj_produkcje_dla_kata(produkcja_miesieczna_kwh: List[float],
                                    kat_bazowy: float,
                                    kat_nowy: float) -> List[float]:
    """
    Przeskalowuje produkcje miesieczna dla innego kata nachylenia.

    Wyzszy kat = mniej latem, wiecej zima/wiosna/jesien.

    Parametry:
        produkcja_miesieczna_kwh: bazowa produkcja [kWh] (12 wartosci)
        kat_bazowy: obecny kat nachylenia [stopnie]
        kat_nowy: nowy kat nachylenia [stopnie]

    Zwraca:
        Przeskalowana produkcja miesieczna [kWh] (12 wartosci)
    """
    nowa_produkcja = []
    for m in range(12):
        wsp_bazowy = _ocen_produkcje_dla_kata(kat_bazowy, m + 1)
        wsp_nowy = _ocen_produkcje_dla_kata(kat_nowy, m + 1)

        if wsp_bazowy > 0:
            skala = wsp_nowy / wsp_bazowy
        else:
            skala = 1.0

        nowa_produkcja.append(round(produkcja_miesieczna_kwh[m] * skala, 2))

    return nowa_produkcja


def porownaj_scenariusze(
        produkcja_miesieczna_kwh: List[float],
        zuzycie_miesieczne_kwh: List[float],
        kat_nachylenia: float = 30.0,
        koszt_instalacji_zl: float = 30000.0,
        koszt_magazynu_zl: float = 15000.0,
        pojemnosc_magazynu_kwh: float = 10.0,
        sprawnosc_magazynu_procent: float = 95.0,
        strata_zacienienia_procent: float = 5.0,
        rok: int = 2025) -> Dict:
    """
    Porownuje scenariusze side-by-side.

    Scenariusze:
    1. Bez PV (bazowy) - dla kazdej taryfy
    2. PV bez magazynu - dla kazdej taryfy
    3. PV z magazynem - dla kazdej taryfy
    4. Rozne katy nachylenia (30/40/50)
    5. Z optymalizatorami vs bez (przy zacienieniu)

    Parametry:
        produkcja_miesieczna_kwh: produkcja miesieczna z PV [kWh] (12)
        zuzycie_miesieczne_kwh: zuzycie miesieczne [kWh] (12)
        kat_nachylenia: obecny kat nachylenia [stopnie]
        koszt_instalacji_zl: koszt instalacji PV [PLN]
        koszt_magazynu_zl: koszt magazynu energii [PLN]
        pojemnosc_magazynu_kwh: pojemnosc magazynu [kWh]
        sprawnosc_magazynu_procent: sprawnosc roundtrip [%]
        strata_zacienienia_procent: strata z powodu zacienienia [%]
        rok: rok analizy

    Zwraca:
        Slownik z porownaniem wszystkich scenariuszy
    """
    taryfy = ["G11", "G11f", "dynamiczna"]
    wyniki = []

    # Konfiguracja magazynu
    magazyn = KonfiguracjaMagazynu(
        pojemnosc_kwh=pojemnosc_magazynu_kwh,
        moc_ladowania_kw=pojemnosc_magazynu_kwh / 2.0,
        moc_rozladowania_kw=pojemnosc_magazynu_kwh / 2.0,
        sprawnosc_procent=sprawnosc_magazynu_procent,
        godzina_sprzedazy=18,
        priorytet="autokonsumpcja",
    )

    # --- Scenariusz 1: Bez PV (kazda taryfa) ---
    for taryfa in taryfy:
        config = KonfiguracjaScenariusza(
            nazwa=f"Bez PV ({taryfa})",
            produkcja_miesieczna_kwh=[0.0] * 12,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa=taryfa,
            magazyn=None,
            kat_nachylenia=0.0,
            z_optymalizatorami=False,
            koszt_instalacji_zl=0.0,
        )
        wynik = oblicz_scenariusz(config, rok)
        wyniki.append(wynik)

    # --- Scenariusz 2: PV bez magazynu (kazda taryfa) ---
    for taryfa in taryfy:
        config = KonfiguracjaScenariusza(
            nazwa=f"PV bez magazynu ({taryfa})",
            produkcja_miesieczna_kwh=produkcja_miesieczna_kwh,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa=taryfa,
            magazyn=None,
            kat_nachylenia=kat_nachylenia,
            z_optymalizatorami=False,
            koszt_instalacji_zl=koszt_instalacji_zl,
        )
        wynik = oblicz_scenariusz(config, rok)
        wyniki.append(wynik)

    # --- Scenariusz 3: PV z magazynem (kazda taryfa) ---
    for taryfa in taryfy:
        config = KonfiguracjaScenariusza(
            nazwa=f"PV z magazynem ({taryfa})",
            produkcja_miesieczna_kwh=produkcja_miesieczna_kwh,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa=taryfa,
            magazyn=magazyn,
            kat_nachylenia=kat_nachylenia,
            z_optymalizatorami=False,
            koszt_instalacji_zl=koszt_instalacji_zl + koszt_magazynu_zl,
        )
        wynik = oblicz_scenariusz(config, rok)
        wyniki.append(wynik)

    # --- Scenariusz 4: Rozne katy nachylenia (taryfa G11) ---
    katy = [30, 40, 50]
    for kat in katy:
        produkcja_kat = przeskaluj_produkcje_dla_kata(
            produkcja_miesieczna_kwh, kat_nachylenia, float(kat)
        )
        config = KonfiguracjaScenariusza(
            nazwa=f"Kat {kat} stopni (G11)",
            produkcja_miesieczna_kwh=produkcja_kat,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa="G11",
            magazyn=magazyn,
            kat_nachylenia=float(kat),
            z_optymalizatorami=False,
            koszt_instalacji_zl=koszt_instalacji_zl + koszt_magazynu_zl,
        )
        wynik = oblicz_scenariusz(config, rok)
        wyniki.append(wynik)

    # --- Scenariusz 5: Z optymalizatorami vs bez (taryfa G11) ---
    if strata_zacienienia_procent > 2.0:
        # Bez optymalizatorow - obecna produkcja
        config_bez = KonfiguracjaScenariusza(
            nazwa="Bez optymalizatorow (G11)",
            produkcja_miesieczna_kwh=produkcja_miesieczna_kwh,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa="G11",
            magazyn=magazyn,
            kat_nachylenia=kat_nachylenia,
            z_optymalizatorami=False,
            koszt_instalacji_zl=koszt_instalacji_zl + koszt_magazynu_zl,
        )
        wynik_bez = oblicz_scenariusz(config_bez, rok)
        wyniki.append(wynik_bez)

        # Z optymalizatorami - redukcja strat zacienienia o ~60%
        # (optymalizatory odzyskuja wiekszosc strat mismatch)
        redukcja_strat = strata_zacienienia_procent * 0.6 / 100.0
        produkcja_z_opt = [
            round(p * (1.0 + redukcja_strat), 2)
            for p in produkcja_miesieczna_kwh
        ]
        # Koszt optymalizatorow: ~300-500 PLN/panel, zakladamy 10 paneli
        koszt_optymalizatorow = 4000.0

        config_z = KonfiguracjaScenariusza(
            nazwa="Z optymalizatorami (G11)",
            produkcja_miesieczna_kwh=produkcja_z_opt,
            zuzycie_miesieczne_kwh=zuzycie_miesieczne_kwh,
            taryfa="G11",
            magazyn=magazyn,
            kat_nachylenia=kat_nachylenia,
            z_optymalizatorami=True,
            koszt_instalacji_zl=koszt_instalacji_zl + koszt_magazynu_zl + koszt_optymalizatorow,
        )
        wynik_z = oblicz_scenariusz(config_z, rok)
        wyniki.append(wynik_z)

    # Podsumowanie
    return {
        "scenariusze": wyniki,
        "parametry": {
            "kat_nachylenia_bazowy": kat_nachylenia,
            "pojemnosc_magazynu_kwh": pojemnosc_magazynu_kwh,
            "koszt_instalacji_zl": koszt_instalacji_zl,
            "koszt_magazynu_zl": koszt_magazynu_zl,
            "strata_zacienienia_procent": strata_zacienienia_procent,
            "rok": rok,
        },
        "najlepszy_scenariusz": _znajdz_najlepszy(wyniki),
    }


def _znajdz_najlepszy(wyniki: List[Dict]) -> Dict:
    """
    Znajduje najlepszy scenariusz wedlug kryterium samowystarczalnosci i kosztu.

    Priorytet:
    1. Najwiecej miesiecy samowystarczalnych
    2. Przy remisie - najnizszy koszt roczny

    Parametry:
        wyniki: lista wynikow scenariuszy

    Zwraca:
        Slownik z najlepszym scenariuszem
    """
    if not wyniki:
        return {"nazwa": "brak", "powod": "Brak scenariuszy do porownania"}

    # Filtruj scenariusze z PV (nie bazowe)
    z_pv = [w for w in wyniki if w["produkcja_roczna_kwh"] > 0]
    if not z_pv:
        return {"nazwa": "brak PV", "powod": "Brak scenariuszy z instalacja PV"}

    # Sortuj: najpierw po samowystarczalnosci (malejaco), potem po koszcie (rosnaco)
    posortowane = sorted(
        z_pv,
        key=lambda w: (-w["miesiace_samowystarczalne"], w["koszt_roczny_zl"])
    )

    najlepszy = posortowane[0]
    return {
        "nazwa": najlepszy["nazwa"],
        "miesiace_samowystarczalne": najlepszy["miesiace_samowystarczalne"],
        "koszt_roczny_zl": najlepszy["koszt_roczny_zl"],
        "oszczednosc_roczna_zl": najlepszy["oszczednosc_roczna_zl"],
        "powod": (
            f"Najlepsza opcja pod wzgledem samowystarczalnosci "
            f"({najlepszy['miesiace_samowystarczalne']} mies.) i kosztow rocznych."
        ),
    }
