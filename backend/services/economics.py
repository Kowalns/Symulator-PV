"""
Serwis analizy ekonomicznej instalacji PV.

Godzina po godzinie analizuje:
1. Produkcje PV vs zuzycie domu
2. Nadwyzke sprzedawana do sieci po cenie RCE
3. Niedobor kupowany z sieci po wybranej taryfie
4. Magazyn energii - ladowanie z PV, rozladowanie w wybranej godzinie

KRYTYCZNE OGRANICZENIE:
Magazyn energii moze byc ladowany TYLKO z nadwyzki PV!
Arbitraz cenowy (kupowanie taniej energii z sieci do magazynu) jest
NIEMOZLIWY w Polsce. Sprzedawac mozna TYLKO energie z PV.
"""

import json
import math
import calendar
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

from backend.services.rce_prices import pobierz_cene_rce, pobierz_cene_rce_sprzedaz


# Sciezka do pliku z taryfami
TARIFFS_PATH = Path(__file__).parent.parent / "data" / "tariffs.json"


@dataclass
class KonfiguracjaMagazynu:
    """
    Konfiguracja magazynu energii dla analizy ekonomicznej.

    Atrybuty:
        pojemnosc_kwh: pojemnosc uzyteczna magazynu [kWh]
        moc_ladowania_kw: maksymalna moc ladowania [kW]
        moc_rozladowania_kw: maksymalna moc rozladowania [kW]
        sprawnosc_procent: sprawnosc roundtrip [%]
        godzina_sprzedazy: preferowana godzina sprzedazy energii z magazynu (0-23)
        priorytet: "autokonsumpcja" lub "sprzedaz" - co robic z energia z magazynu
    """
    pojemnosc_kwh: float = 0.0
    moc_ladowania_kw: float = 0.0
    moc_rozladowania_kw: float = 0.0
    sprawnosc_procent: float = 95.0
    godzina_sprzedazy: int = 18
    priorytet: str = "autokonsumpcja"


@dataclass
class WynikGodzinowy:
    """Wynik analizy ekonomicznej dla jednej godziny."""
    miesiac: int = 1
    godzina: int = 0
    produkcja_wh: float = 0.0
    zuzycie_wh: float = 0.0
    nadwyzka_wh: float = 0.0
    niedobor_wh: float = 0.0
    magazyn_ladowanie_wh: float = 0.0
    magazyn_rozladowanie_wh: float = 0.0
    magazyn_stan_wh: float = 0.0
    sprzedaz_do_sieci_wh: float = 0.0
    kupno_z_sieci_wh: float = 0.0
    koszt_kupna_zl: float = 0.0
    przychod_sprzedazy_zl: float = 0.0


def wczytaj_taryfy() -> Dict:
    """
    Wczytuje definicje taryf z pliku JSON.

    Zwraca:
        Slownik z taryfami (G11, G11f, dynamiczna)
    """
    with open(TARIFFS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def oblicz_cene_kupna(taryfa: str, miesiac: int, godzina: int,
                       taryfy_dane: Optional[Dict] = None) -> float:
    """
    Oblicza cene kupna 1 kWh z sieci wedlug wybranej taryfy.

    Parametry:
        taryfa: nazwa taryfy ("G11", "G11f", "dynamiczna")
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)
        taryfy_dane: opcjonalne - wczytane dane taryf (jesli None, wczyta z pliku)

    Zwraca:
        Cena w PLN/kWh (brutto)
    """
    if taryfy_dane is None:
        taryfy_dane = wczytaj_taryfy()

    if taryfa == "G11":
        return taryfy_dane["G11"]["cena_calkowita_zl_kwh"]
    elif taryfa == "G11f":
        return taryfy_dane["G11f"]["cena_calkowita_zl_kwh"]
    elif taryfa == "dynamiczna":
        # Cena dynamiczna = RCE + narzut + dystrybucja + oplaty
        dane_dyn = taryfy_dane["dynamiczna"]["skladniki"]
        cena_rce = pobierz_cene_rce(miesiac, godzina)
        narzut = dane_dyn["narzut_sprzedawcy_zl_kwh"]
        dystrybucja = dane_dyn["dystrybucja_zmienna_zl_kwh"]
        kogeneracja = dane_dyn["oplata_kogeneracyjna_zl_kwh"]
        oze = dane_dyn["oplata_oze_zl_kwh"]
        mocowa = dane_dyn["oplata_mocowa_zl_kwh"]
        jakosciowa = dane_dyn["skladnik_jakosciowy_zl_kwh"]
        return round(cena_rce + narzut + dystrybucja + kogeneracja + oze + mocowa + jakosciowa, 4)
    else:
        # Domyslnie G11
        return taryfy_dane["G11"]["cena_calkowita_zl_kwh"]


def oblicz_cene_sprzedazy(miesiac: int, godzina: int) -> float:
    """
    Oblicza cene sprzedazy 1 kWh nadwyzki do sieci.

    Prosumer sprzedaje energie po cenie RCE (netto).

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Cena sprzedazy w PLN/kWh (netto)
    """
    return pobierz_cene_rce_sprzedaz(miesiac, godzina)


def oblicz_oplaty_stale(taryfa: str, taryfy_dane: Optional[Dict] = None) -> float:
    """
    Oblicza miesieczne oplaty stale dla wybranej taryfy.

    Parametry:
        taryfa: nazwa taryfy ("G11", "G11f", "dynamiczna")
        taryfy_dane: opcjonalne - wczytane dane taryf

    Zwraca:
        Suma oplat stalych w PLN/miesiac
    """
    if taryfy_dane is None:
        taryfy_dane = wczytaj_taryfy()

    klucz = taryfa if taryfa in taryfy_dane else "G11"
    oplaty = taryfy_dane[klucz].get("oplaty_stale_zl_mc", {})
    return round(sum(oplaty.values()), 2)


def analizuj_ekonomie(
    produkcja_godzinowa_wh: List[float],
    zuzycie_godzinowe_wh: List[float],
    taryfa: str = "G11",
    magazyn: Optional[KonfiguracjaMagazynu] = None,
    rok: int = 2025,
) -> Dict:
    """
    Przeprowadza pelna analize ekonomiczna godzina po godzinie.

    KRYTYCZNE: Magazyn ladowany jest TYLKO z nadwyzki PV!
    Nie mozna kupowac energii z sieci do magazynu w celu odsprzedazy.

    Algorytm dla kazdej godziny:
    1. Oblicz bilans: produkcja - zuzycie
    2. Jesli nadwyzka (produkcja > zuzycie):
       a. Laduj magazyn (jesli jest i nie jest pelny)
       b. Reszte sprzedaj do sieci po cenie RCE
    3. Jesli niedobor (zuzycie > produkcja):
       a. Rozladuj magazyn (autokonsumpcja) LUB
       b. Kup z sieci po cenie taryfy
    4. W godzinie sprzedazy: rozladuj magazyn i sprzedaj po RCE

    Parametry:
        produkcja_godzinowa_wh: 8760 wartosci produkcji PV [Wh]
        zuzycie_godzinowe_wh: 8760 wartosci zuzycia [Wh]
        taryfa: wybrana taryfa ("G11", "G11f", "dynamiczna")
        magazyn: konfiguracja magazynu (None = brak magazynu)
        rok: rok analizy

    Zwraca:
        Slownik z wynikami analizy (bilans miesieczny, roczny, oszczednosci)
    """
    taryfy_dane = wczytaj_taryfy()

    # Stan magazynu [Wh]
    magazyn_stan = 0.0
    magazyn_pojemnosc_wh = 0.0
    magazyn_moc_lad_wh = 0.0
    magazyn_moc_rozlad_wh = 0.0
    sprawnosc = 1.0

    if magazyn and magazyn.pojemnosc_kwh > 0:
        magazyn_pojemnosc_wh = magazyn.pojemnosc_kwh * 1000.0
        magazyn_moc_lad_wh = magazyn.moc_ladowania_kw * 1000.0
        magazyn_moc_rozlad_wh = magazyn.moc_rozladowania_kw * 1000.0
        sprawnosc = magazyn.sprawnosc_procent / 100.0

    # Rozdzielenie sprawnosci roundtrip na czesc ladowania i rozladowania
    # sqrt(sprawnosc_roundtrip) na kazdym etapie - symetryczny model strat
    import math as _math
    sprawnosc_ladowania = _math.sqrt(sprawnosc)
    sprawnosc_rozladowania = _math.sqrt(sprawnosc)

    # Wyniki miesieczne
    wyniki_miesieczne = []
    for _ in range(12):
        wyniki_miesieczne.append({
            "produkcja_kwh": 0.0,
            "zuzycie_kwh": 0.0,
            "autokonsumpcja_kwh": 0.0,
            "sprzedaz_kwh": 0.0,
            "kupno_kwh": 0.0,
            "magazyn_ladowanie_kwh": 0.0,
            "magazyn_rozladowanie_kwh": 0.0,
            "koszt_kupna_zl": 0.0,
            "przychod_sprzedazy_zl": 0.0,
            "oszczednosc_zl": 0.0,
        })

    # Iteracja przez kazda godzine roku
    indeks = 0
    for miesiac in range(1, 13):
        dni = calendar.monthrange(rok, miesiac)[1]

        for dzien in range(1, dni + 1):
            for godzina in range(24):
                if indeks >= len(produkcja_godzinowa_wh) or indeks >= len(zuzycie_godzinowe_wh):
                    break

                produkcja = produkcja_godzinowa_wh[indeks]
                zuzycie = zuzycie_godzinowe_wh[indeks]
                mi = miesiac - 1  # indeks miesiaca (0-based)

                wyniki_miesieczne[mi]["produkcja_kwh"] += produkcja / 1000.0
                wyniki_miesieczne[mi]["zuzycie_kwh"] += zuzycie / 1000.0

                bilans = produkcja - zuzycie

                if bilans >= 0:
                    # Nadwyzka - produkcja pokrywa zuzycie
                    autokonsumpcja = zuzycie
                    nadwyzka = bilans

                    wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += autokonsumpcja / 1000.0

                    # Laduj magazyn z nadwyzki PV (TYLKO z PV!)
                    ladowanie = 0.0
                    if magazyn and magazyn.pojemnosc_kwh > 0 and nadwyzka > 0:
                        dostepna_pojemnosc = magazyn_pojemnosc_wh - magazyn_stan
                        max_ladowanie = min(nadwyzka, magazyn_moc_lad_wh, dostepna_pojemnosc)
                        if max_ladowanie > 0:
                            ladowanie = max_ladowanie
                            # Sprawnosc ladowania (sqrt z roundtrip)
                            magazyn_stan += ladowanie * sprawnosc_ladowania
                            nadwyzka -= ladowanie
                            wyniki_miesieczne[mi]["magazyn_ladowanie_kwh"] += ladowanie / 1000.0

                    # Reszta nadwyzki sprzedawana do sieci
                    if nadwyzka > 0:
                        cena_sprzedazy = oblicz_cene_sprzedazy(miesiac, godzina)
                        przychod = (nadwyzka / 1000.0) * cena_sprzedazy
                        wyniki_miesieczne[mi]["sprzedaz_kwh"] += nadwyzka / 1000.0
                        wyniki_miesieczne[mi]["przychod_sprzedazy_zl"] += przychod

                else:
                    # Niedobor - zuzycie wieksze niz produkcja
                    autokonsumpcja = produkcja
                    niedobor = abs(bilans)

                    wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += autokonsumpcja / 1000.0

                    # Rozladuj magazyn na autokonsumpcje (jesli priorytet = autokonsumpcja)
                    rozladowanie = 0.0
                    if (magazyn and magazyn.pojemnosc_kwh > 0 and
                            magazyn.priorytet == "autokonsumpcja" and magazyn_stan > 0):
                        max_rozladowanie = min(niedobor, magazyn_moc_rozlad_wh, magazyn_stan)
                        if max_rozladowanie > 0:
                            rozladowanie = max_rozladowanie
                            magazyn_stan -= rozladowanie
                            # Sprawnosc rozladowania (sqrt z roundtrip) - dostarczamy mniej
                            energia_dostarczona = rozladowanie * sprawnosc_rozladowania
                            niedobor -= energia_dostarczona
                            wyniki_miesieczne[mi]["magazyn_rozladowanie_kwh"] += energia_dostarczona / 1000.0
                            wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += energia_dostarczona / 1000.0

                    # Reszta niedoboru kupowana z sieci
                    if niedobor > 0:
                        cena_kupna = oblicz_cene_kupna(taryfa, miesiac, godzina, taryfy_dane)
                        koszt = (niedobor / 1000.0) * cena_kupna
                        wyniki_miesieczne[mi]["kupno_kwh"] += niedobor / 1000.0
                        wyniki_miesieczne[mi]["koszt_kupna_zl"] += koszt

                # Sprzedaz z magazynu w wybranej godzinie
                if (magazyn and magazyn.pojemnosc_kwh > 0 and
                        magazyn.priorytet == "sprzedaz" and
                        godzina == magazyn.godzina_sprzedazy and
                        magazyn_stan > 0):
                    # Sprzedaj energie z magazynu do sieci
                    do_sprzedazy_raw = min(magazyn_stan, magazyn_moc_rozlad_wh)
                    if do_sprzedazy_raw > 0:
                        magazyn_stan -= do_sprzedazy_raw
                        # Sprawnosc rozladowania - dostarczamy mniej do sieci
                        do_sprzedazy = do_sprzedazy_raw * sprawnosc_rozladowania
                        cena_sprzedazy = oblicz_cene_sprzedazy(miesiac, godzina)
                        przychod = (do_sprzedazy / 1000.0) * cena_sprzedazy
                        wyniki_miesieczne[mi]["magazyn_rozladowanie_kwh"] += do_sprzedazy / 1000.0
                        wyniki_miesieczne[mi]["sprzedaz_kwh"] += do_sprzedazy / 1000.0
                        wyniki_miesieczne[mi]["przychod_sprzedazy_zl"] += przychod

                indeks += 1

    # Oblicz oszczednosci i podsumowanie
    oplaty_stale_mc = oblicz_oplaty_stale(taryfa, taryfy_dane)

    # Koszt bez PV (caly rok kupowany z sieci)
    koszt_bez_pv = 0.0
    indeks_ref = 0
    for miesiac in range(1, 13):
        dni = calendar.monthrange(rok, miesiac)[1]
        for dzien in range(1, dni + 1):
            for godzina in range(24):
                if indeks_ref >= len(zuzycie_godzinowe_wh):
                    break
                zuzycie = zuzycie_godzinowe_wh[indeks_ref]
                cena = oblicz_cene_kupna(taryfa, miesiac, godzina, taryfy_dane)
                koszt_bez_pv += (zuzycie / 1000.0) * cena
                indeks_ref += 1

    # Sumaryczne wyniki roczne
    roczne = {
        "produkcja_kwh": 0.0,
        "zuzycie_kwh": 0.0,
        "autokonsumpcja_kwh": 0.0,
        "sprzedaz_kwh": 0.0,
        "kupno_kwh": 0.0,
        "koszt_kupna_zl": 0.0,
        "przychod_sprzedazy_zl": 0.0,
        "oplaty_stale_roczne_zl": oplaty_stale_mc * 12,
        "koszt_calkowity_zl": 0.0,
        "koszt_bez_pv_zl": round(koszt_bez_pv + oplaty_stale_mc * 12, 2),
        "oszczednosc_roczna_zl": 0.0,
        "autokonsumpcja_procent": 0.0,
        "autarchia_procent": 0.0,
    }

    for mi in range(12):
        wm = wyniki_miesieczne[mi]
        wm["oszczednosc_zl"] = round(wm["przychod_sprzedazy_zl"] - wm["koszt_kupna_zl"], 2)
        # Zaokraglenie wartosci miesiecznych
        for klucz in wm:
            wm[klucz] = round(wm[klucz], 2)

        roczne["produkcja_kwh"] += wyniki_miesieczne[mi]["produkcja_kwh"]
        roczne["zuzycie_kwh"] += wyniki_miesieczne[mi]["zuzycie_kwh"]
        roczne["autokonsumpcja_kwh"] += wyniki_miesieczne[mi]["autokonsumpcja_kwh"]
        roczne["sprzedaz_kwh"] += wyniki_miesieczne[mi]["sprzedaz_kwh"]
        roczne["kupno_kwh"] += wyniki_miesieczne[mi]["kupno_kwh"]
        roczne["koszt_kupna_zl"] += wyniki_miesieczne[mi]["koszt_kupna_zl"]
        roczne["przychod_sprzedazy_zl"] += wyniki_miesieczne[mi]["przychod_sprzedazy_zl"]

    roczne["koszt_calkowity_zl"] = round(
        roczne["koszt_kupna_zl"] + roczne["oplaty_stale_roczne_zl"] - roczne["przychod_sprzedazy_zl"], 2
    )
    roczne["oszczednosc_roczna_zl"] = round(
        roczne["koszt_bez_pv_zl"] - roczne["koszt_calkowity_zl"], 2
    )

    # Autokonsumpcja = procent produkcji zuzytej na miejscu
    if roczne["produkcja_kwh"] > 0:
        roczne["autokonsumpcja_procent"] = round(
            roczne["autokonsumpcja_kwh"] / roczne["produkcja_kwh"] * 100, 1
        )

    # Autarchia = procent zuzycia pokrytego z PV (wlacznie z magazynem)
    if roczne["zuzycie_kwh"] > 0:
        roczne["autarchia_procent"] = round(
            roczne["autokonsumpcja_kwh"] / roczne["zuzycie_kwh"] * 100, 1
        )

    # Zaokraglenie wartosci rocznych
    for klucz in roczne:
        if isinstance(roczne[klucz], float):
            roczne[klucz] = round(roczne[klucz], 2)

    return {
        "taryfa": taryfa,
        "rok": rok,
        "podsumowanie_roczne": roczne,
        "miesiace": wyniki_miesieczne,
        "oplaty_stale_miesieczne_zl": oplaty_stale_mc,
        "magazyn_uzyty": magazyn is not None and magazyn.pojemnosc_kwh > 0,
        "uwaga_arbitraz": "Magazyn ladowany TYLKO z nadwyzki PV. Arbitraz cenowy (ladowanie z sieci) jest niemozliwy w Polsce.",
    }
