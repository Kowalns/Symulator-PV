"""
Serwis analizy ekonomicznej instalacji PV.

Godzina po godzinie analizuje:
1. Produkcje PV vs zuzycie domu
2. Nadwyzke sprzedawana do sieci po cenie RCE
3. Niedobor kupowany z sieci po wybranej taryfie
4. Magazyn energii - ladowanie z PV (priorytet) i z sieci (fallback)
5. Rozladowanie magazynu w godzinie z najwyzsza cena (16-22)

ZASADY MAGAZYNU:
- Priorytet ladowania: nadwyzka PV
- Fallback (taryfy dynamiczne): ladowanie z sieci w najtanszych godzinach dnia
- Energia z sieci w magazynie moze byc TYLKO zuzyta na wlasne potrzeby (autokonsumpcja)
- Energia z sieci w magazynie NIE moze byc sprzedawana do sieci
- Energia z PV w magazynie MOZE byc sprzedawana do sieci
- Sledzenie zrodla energii w magazynie (PV vs siec)
"""

import json
import calendar
from typing import Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass

from backend.services.rce_prices import pobierz_cene_rce, pobierz_cene_rce_sprzedaz


# Taryfy dynamiczne - optymalizacja cenowa jest aktywna
TARYFY_DYNAMICZNE = ("G11f_dynamiczna", "G11_dynamiczna")


# Sciezka do pliku z taryfami
TARIFFS_PATH = Path(__file__).parent.parent / "data" / "tariffs.json"


@dataclass
class KonfiguracjaMagazynu:
    """
    Konfiguracja magazynu energii dla analizy ekonomicznej.

    Atrybuty:
        pojemnosc_kwh: pojemnosc nominalna magazynu [kWh]
        moc_ladowania_kw: maksymalna moc ladowania [kW]
        moc_rozladowania_kw: maksymalna moc rozladowania [kW]
        sprawnosc_procent: sprawnosc roundtrip [%]
        dod_procent: glebokosc rozladowania (Depth of Discharge) [%]
        godzina_sprzedazy: preferowana godzina sprzedazy energii z magazynu (0-23)
        priorytet: "autokonsumpcja" lub "sprzedaz" - co robic z energia z magazynu
    """
    pojemnosc_kwh: float = 0.0
    moc_ladowania_kw: float = 0.0
    moc_rozladowania_kw: float = 0.0
    sprawnosc_procent: float = 95.0
    dod_procent: float = 100.0
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

    WAZNE: Oplata mocowa jest ryczaltem miesiecznym (nie per kWh) - nie jest
    wliczana w cene jednostkowa. Jest uwzgledniana w oplatach stalych.

    Parametry:
        taryfa: nazwa taryfy ("G11", "G11f_dynamiczna", "G11_dynamiczna")
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)
        taryfy_dane: opcjonalne - wczytane dane taryf (jesli None, wczyta z pliku)

    Zwraca:
        Cena w PLN/kWh (brutto z VAT 23%)
    """
    if taryfy_dane is None:
        taryfy_dane = wczytaj_taryfy()

    if taryfa == "G11":
        return taryfy_dane["G11"]["cena_calkowita_brutto_zl_kwh"]
    elif taryfa in ("G11f_dynamiczna", "G11_dynamiczna"):
        # Taryfy dynamiczne: cena = CTGE_brutto + WK_brutto + dystrybucja_brutto + oplaty_brutto
        # CTGE pochodzi z pobierz_cene_rce() (juz przeliczona na PLN/kWh brutto)
        # Roznica miedzy G11f a G11: dystrybucja zmienna (0.0635 vs 0.4287 brutto)
        # Oplata mocowa NIE jest per kWh - jest ryczaltem miesiecznym
        dane_brutto = taryfy_dane[taryfa]["skladniki_brutto_zl_kwh"]
        cena_rce_brutto = pobierz_cene_rce(miesiac, godzina)
        narzut = dane_brutto["narzut_sprzedawcy_wk"]
        dystrybucja = dane_brutto["dystrybucja_zmienna"]
        jakosciowa = dane_brutto["oplata_jakosciowa"]
        oze = dane_brutto["oplata_oze"]
        kogeneracja = dane_brutto["oplata_kogeneracyjna"]
        return round(cena_rce_brutto + narzut + dystrybucja + jakosciowa + oze + kogeneracja, 4)
    else:
        # Domyslnie G11
        return taryfy_dane["G11"]["cena_calkowita_brutto_zl_kwh"]


def oblicz_cene_sprzedazy(miesiac: int, godzina: int,
                          marza_sprzedawcy: float = 0.03) -> float:
    """
    Oblicza cene sprzedazy 1 kWh nadwyzki do sieci.

    Prosumer sprzedaje energie po cenie RCE (netto) pomniejszonej o marze sprzedawcy.

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)
        marza_sprzedawcy: marza sprzedawcy w PLN/kWh (domyslnie 0.03)

    Zwraca:
        Cena sprzedazy w PLN/kWh (netto, po odjeciu marzy, minimum 0)
    """
    cena_rce = pobierz_cene_rce_sprzedaz(miesiac, godzina)
    cena_po_marzy = cena_rce - marza_sprzedawcy
    return max(0.0, cena_po_marzy)


def oblicz_oplaty_stale(taryfa: str, taryfy_dane: Optional[Dict] = None) -> float:
    """
    Oblicza miesieczne oplaty stale dla wybranej taryfy.

    Zawiera: oplata sieciowa stala, oplata mocowa (ryczalt!),
    oplata abonamentowa, oplata handlowa.

    Parametry:
        taryfa: nazwa taryfy ("G11", "G11f_dynamiczna", "G11_dynamiczna")
        taryfy_dane: opcjonalne - wczytane dane taryf

    Zwraca:
        Suma oplat stalych w PLN/miesiac (brutto)
    """
    if taryfy_dane is None:
        taryfy_dane = wczytaj_taryfy()

    klucz = taryfa if taryfa in taryfy_dane else "G11"
    oplaty = taryfy_dane[klucz].get("oplaty_stale_brutto_zl_mc", {})
    return round(sum(oplaty.values()), 2)


def _znajdz_godzine_szczytowa(miesiac: int, taryfa: str, priorytet: str,
                               taryfy_dane: Dict,
                               marza_sprzedawcy: float = 0.03) -> int:
    """
    Znajduje optymalna godzine rozladowania magazynu w oknie 16-22.

    Dla trybu 'autokonsumpcja': godzina z najwyzsza cena kupna (oszczedzamy najwiecej).
    Dla trybu 'sprzedaz': godzina z najwyzsza cena sprzedazy RCE (zarabiamy najwiecej).

    Parametry:
        miesiac: numer miesiaca (1-12)
        taryfa: nazwa taryfy
        priorytet: "autokonsumpcja" lub "sprzedaz"
        taryfy_dane: wczytane dane taryf
        marza_sprzedawcy: marza sprzedawcy w PLN/kWh (domyslnie 0.03)

    Zwraca:
        Godzina (16-22) z najwyzsza cena
    """
    najlepsza_godzina = 18  # domyslna
    najlepsza_cena = -999.0

    for godzina in range(16, 23):  # 16-22 wlacznie
        if priorytet == "sprzedaz":
            cena = oblicz_cene_sprzedazy(miesiac, godzina, marza_sprzedawcy)
        else:
            cena = oblicz_cene_kupna(taryfa, miesiac, godzina, taryfy_dane)
        if cena > najlepsza_cena:
            najlepsza_cena = cena
            najlepsza_godzina = godzina

    return najlepsza_godzina


def analizuj_ekonomie(
    produkcja_godzinowa_wh: List[float],
    zuzycie_godzinowe_wh: List[float],
    taryfa: str = "G11",
    magazyn: Optional[KonfiguracjaMagazynu] = None,
    rok: int = 2025,
    marza_sprzedawcy: float = 0.03,
) -> Dict:
    """
    Przeprowadza pelna analize ekonomiczna godzina po godzinie.

    Algorytm dwuprzebiegowy (per dzien):
    Przebieg 1: Standardowe bilansowanie (PV laduje magazyn, nadwyzka sprzedawana)
    Po przebiegu 1: Jesli magazyn nie pelny i taryfa dynamiczna - zaplanuj
                    ladowanie z sieci w najtanszych godzinach dnia
    Przebieg 2: Zastosuj decyzje o ladowaniu z sieci + rozladowanie w szczycie

    Sledzenie zrodla energii w magazynie:
    - magazyn_energia_pv_wh: energia z PV (moze byc sprzedana lub zuzyta)
    - magazyn_energia_siec_wh: energia z sieci (TYLKO autokonsumpcja!)

    Parametry:
        produkcja_godzinowa_wh: 8760 wartosci produkcji PV [Wh]
        zuzycie_godzinowe_wh: 8760 wartosci zuzycia [Wh]
        taryfa: wybrana taryfa ("G11", "G11f_dynamiczna", "G11_dynamiczna")
        magazyn: konfiguracja magazynu (None = brak magazynu)
        rok: rok analizy
        marza_sprzedawcy: marza sprzedawcy w PLN/kWh (domyslnie 0.03)

    Zwraca:
        Slownik z wynikami analizy (bilans miesieczny, roczny, oszczednosci)
    """
    taryfy_dane = wczytaj_taryfy()

    # Czy taryfa jest dynamiczna (optymalizacja cenowa aktywna)
    taryfa_dynamiczna = taryfa in TARYFY_DYNAMICZNE

    # Stan magazynu [Wh] - sledzenie zrodla energii
    magazyn_stan_pv = 0.0   # energia w magazynie pochodzaca z PV
    magazyn_stan_siec = 0.0  # energia w magazynie pochodzaca z sieci
    magazyn_pojemnosc_wh = 0.0
    magazyn_moc_lad_wh = 0.0
    magazyn_moc_rozlad_wh = 0.0
    sprawnosc = 1.0

    if magazyn and magazyn.pojemnosc_kwh > 0:
        # Efektywna pojemnosc uwzglednia DoD (glebokosc rozladowania)
        dod = magazyn.dod_procent / 100.0
        magazyn_pojemnosc_wh = magazyn.pojemnosc_kwh * 1000.0 * dod
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

    # Iteracja przez kazdy dzien roku - algorytm dwuprzebiegowy
    indeks = 0
    for miesiac in range(1, 13):
        dni = calendar.monthrange(rok, miesiac)[1]

        # Znajdz optymalna godzine rozladowania dla tego miesiaca
        if magazyn and magazyn.pojemnosc_kwh > 0 and taryfa_dynamiczna:
            godzina_rozladowania = _znajdz_godzine_szczytowa(
                miesiac, taryfa, magazyn.priorytet, taryfy_dane,
                marza_sprzedawcy
            )
        elif magazyn and magazyn.pojemnosc_kwh > 0:
            godzina_rozladowania = magazyn.godzina_sprzedazy
        else:
            godzina_rozladowania = 18

        for dzien in range(1, dni + 1):
            indeks_dnia = indeks
            mi = miesiac - 1  # indeks miesiaca (0-based)

            # === PRZEBIEG 1: PV ladowanie i standardowe bilansowanie ===
            # Symulujemy dzien aby okreslic ile PV naladowalo magazyn
            magazyn_stan_pv_start = magazyn_stan_pv
            magazyn_stan_siec_start = magazyn_stan_siec

            # Zbierz dane dnia
            dane_dnia = []
            for g in range(24):
                idx = indeks_dnia + g
                if idx >= len(produkcja_godzinowa_wh) or idx >= len(zuzycie_godzinowe_wh):
                    break
                dane_dnia.append((produkcja_godzinowa_wh[idx], zuzycie_godzinowe_wh[idx]))

            # Przebieg 1: tylko PV ladowanie magazynu (symulacja)
            # Tymczasowy stan magazynu do obliczenia ile PV naladuje
            tmp_pv = magazyn_stan_pv
            tmp_siec = magazyn_stan_siec
            # Zbior godzin z nadwyzka PV - do wykluczenia z ladowania sieciowego
            godziny_nadwyzki_pv = set()

            for g, (produkcja, zuzycie) in enumerate(dane_dnia):
                bilans = produkcja - zuzycie
                if bilans > 0 and magazyn and magazyn.pojemnosc_kwh > 0:
                    # Nadwyzka PV - laduj magazyn
                    godziny_nadwyzki_pv.add(g)
                    # Nie laduj magazynu w godzinie rozladowania (unikamy ladowania i rozladowania w tej samej godzinie)
                    if g != godzina_rozladowania:
                        nadwyzka = bilans
                        magazyn_stan_tmp = tmp_pv + tmp_siec
                        dostepna_pojemnosc = magazyn_pojemnosc_wh - magazyn_stan_tmp
                        max_ladowanie = min(nadwyzka, magazyn_moc_lad_wh, dostepna_pojemnosc)
                        if max_ladowanie > 0:
                            tmp_pv += max_ladowanie * sprawnosc_ladowania
                elif bilans < 0 and magazyn and magazyn.pojemnosc_kwh > 0:
                    # Niedobor - rozladuj na autokonsumpcje (tylko w trybie autokonsumpcja)
                    if magazyn.priorytet == "autokonsumpcja":
                        niedobor = abs(bilans)
                        magazyn_stan_tmp = tmp_pv + tmp_siec
                        max_rozlad = min(niedobor, magazyn_moc_rozlad_wh, magazyn_stan_tmp)
                        if max_rozlad > 0 and magazyn_stan_tmp > 0:
                            udzial_pv = tmp_pv / magazyn_stan_tmp
                            tmp_pv -= max_rozlad * udzial_pv
                            tmp_siec -= max_rozlad * (1.0 - udzial_pv)
                elif bilans > 0:
                    # Nadwyzka PV bez magazynu - nadal zaznacz godzine
                    godziny_nadwyzki_pv.add(g)

                # Symuluj rozladowanie w godzinie szczytowej (sprzedaz lub autokonsumpcja)
                if (magazyn and magazyn.pojemnosc_kwh > 0 and
                        g == godzina_rozladowania):
                    magazyn_stan_tmp = tmp_pv + tmp_siec
                    if magazyn_stan_tmp > 0:
                        if magazyn.priorytet == "sprzedaz":
                            # Sprzedajemy tylko czesc PV
                            do_sprzedazy = min(tmp_pv, magazyn_moc_rozlad_wh)
                            if do_sprzedazy > 0:
                                tmp_pv -= do_sprzedazy
                        elif magazyn.priorytet == "autokonsumpcja":
                            # Rozladuj na autokonsumpcje w szczycie (cale zuzycie godziny)
                            rozlad = min(zuzycie, magazyn_moc_rozlad_wh, magazyn_stan_tmp)
                            if rozlad > 0:
                                udzial_pv = tmp_pv / magazyn_stan_tmp if magazyn_stan_tmp > 0 else 0.0
                                tmp_pv -= rozlad * udzial_pv
                                tmp_siec -= rozlad * (1.0 - udzial_pv)

            # Po przebiegu 1: sprawdz czy magazyn potrzebuje doladowania z sieci
            magazyn_stan_po_pv = tmp_pv + tmp_siec
            godziny_ladowania_siec = set()  # zestaw godzin do ladowania z sieci

            if (magazyn and magazyn.pojemnosc_kwh > 0 and
                    taryfa_dynamiczna and
                    magazyn_stan_po_pv < magazyn_pojemnosc_wh):
                # Zaplanuj ladowanie z sieci w najtanszych godzinach dnia
                brakujaca_energia = magazyn_pojemnosc_wh - magazyn_stan_po_pv

                # Pobierz ceny RCE dla kazdej godziny dnia
                ceny_godzin = []
                for g in range(len(dane_dnia)):
                    cena = pobierz_cene_rce(miesiac, g)
                    ceny_godzin.append((cena, g))

                # Sortuj od najtanszej
                ceny_godzin.sort(key=lambda x: x[0])

                # Wybierz najtansze godziny do ladowania
                energia_do_naladowania = brakujaca_energia
                for cena, g in ceny_godzin:
                    if energia_do_naladowania <= 0:
                        break
                    # Nie laduj z sieci w godzinie rozladowania
                    if g == godzina_rozladowania:
                        continue
                    # Nie laduj z sieci w godzinach z nadwyzka PV (kolizja double-charge)
                    if g in godziny_nadwyzki_pv:
                        continue
                    godziny_ladowania_siec.add(g)
                    # Jedna godzina = moc_ladowania (z uwzglednieniem sprawnosci)
                    energia_z_godziny = magazyn_moc_lad_wh * sprawnosc_ladowania
                    energia_do_naladowania -= energia_z_godziny

            # === PRZEBIEG 2: Wlasciwa symulacja dnia ===
            for g, (produkcja, zuzycie) in enumerate(dane_dnia):
                wyniki_miesieczne[mi]["produkcja_kwh"] += produkcja / 1000.0
                wyniki_miesieczne[mi]["zuzycie_kwh"] += zuzycie / 1000.0

                bilans = produkcja - zuzycie
                magazyn_stan = magazyn_stan_pv + magazyn_stan_siec

                if bilans >= 0:
                    # Nadwyzka - produkcja pokrywa zuzycie
                    autokonsumpcja = zuzycie
                    nadwyzka = bilans

                    wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += autokonsumpcja / 1000.0

                    # Laduj magazyn z nadwyzki PV
                    # Nie laduj w godzinie rozladowania (unikamy stratnego ladowania i natychmiastowego rozladowania)
                    if (magazyn and magazyn.pojemnosc_kwh > 0 and nadwyzka > 0
                            and g != godzina_rozladowania):
                        dostepna_pojemnosc = magazyn_pojemnosc_wh - magazyn_stan
                        max_ladowanie = min(nadwyzka, magazyn_moc_lad_wh, dostepna_pojemnosc)
                        if max_ladowanie > 0:
                            magazyn_stan_pv += max_ladowanie * sprawnosc_ladowania
                            nadwyzka -= max_ladowanie
                            wyniki_miesieczne[mi]["magazyn_ladowanie_kwh"] += max_ladowanie / 1000.0

                    # Reszta nadwyzki sprzedawana do sieci
                    if nadwyzka > 0:
                        cena_sprzedazy = oblicz_cene_sprzedazy(miesiac, g, marza_sprzedawcy)
                        przychod = (nadwyzka / 1000.0) * cena_sprzedazy
                        wyniki_miesieczne[mi]["sprzedaz_kwh"] += nadwyzka / 1000.0
                        wyniki_miesieczne[mi]["przychod_sprzedazy_zl"] += przychod

                else:
                    # Niedobor - zuzycie wieksze niz produkcja
                    autokonsumpcja = produkcja
                    niedobor = abs(bilans)

                    wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += autokonsumpcja / 1000.0

                    # Rozladuj magazyn na autokonsumpcje (jesli priorytet = autokonsumpcja)
                    if (magazyn and magazyn.pojemnosc_kwh > 0 and
                            magazyn.priorytet == "autokonsumpcja" and magazyn_stan > 0):
                        max_rozladowanie = min(niedobor, magazyn_moc_rozlad_wh, magazyn_stan)
                        if max_rozladowanie > 0:
                            # Proporcjonalnie rozladuj PV i siec
                            udzial_pv = magazyn_stan_pv / magazyn_stan if magazyn_stan > 0 else 0.0
                            rozlad_pv = max_rozladowanie * udzial_pv
                            rozlad_siec = max_rozladowanie * (1.0 - udzial_pv)
                            magazyn_stan_pv -= rozlad_pv
                            magazyn_stan_siec -= rozlad_siec
                            # Sprawnosc rozladowania - dostarczamy mniej
                            energia_dostarczona = max_rozladowanie * sprawnosc_rozladowania
                            niedobor -= energia_dostarczona
                            wyniki_miesieczne[mi]["magazyn_rozladowanie_kwh"] += energia_dostarczona / 1000.0
                            wyniki_miesieczne[mi]["autokonsumpcja_kwh"] += energia_dostarczona / 1000.0

                    # Reszta niedoboru kupowana z sieci
                    if niedobor > 0:
                        cena_kupna = oblicz_cene_kupna(taryfa, miesiac, g, taryfy_dane)
                        koszt = (niedobor / 1000.0) * cena_kupna
                        wyniki_miesieczne[mi]["kupno_kwh"] += niedobor / 1000.0
                        wyniki_miesieczne[mi]["koszt_kupna_zl"] += koszt

                # Ladowanie z sieci w zaplanowanych godzinach (fallback)
                if (magazyn and magazyn.pojemnosc_kwh > 0 and
                        g in godziny_ladowania_siec):
                    magazyn_stan = magazyn_stan_pv + magazyn_stan_siec
                    dostepna_pojemnosc = magazyn_pojemnosc_wh - magazyn_stan
                    max_ladowanie_siec = min(magazyn_moc_lad_wh, dostepna_pojemnosc)
                    if max_ladowanie_siec > 0:
                        # Ladujemy z sieci - koszt kupna
                        magazyn_stan_siec += max_ladowanie_siec * sprawnosc_ladowania
                        cena_kupna = oblicz_cene_kupna(taryfa, miesiac, g, taryfy_dane)
                        koszt = (max_ladowanie_siec / 1000.0) * cena_kupna
                        wyniki_miesieczne[mi]["kupno_kwh"] += max_ladowanie_siec / 1000.0
                        wyniki_miesieczne[mi]["koszt_kupna_zl"] += koszt
                        wyniki_miesieczne[mi]["magazyn_ladowanie_kwh"] += max_ladowanie_siec / 1000.0

                # Rozladowanie magazynu w godzinie szczytowej (sprzedaz lub autokonsumpcja)
                magazyn_stan = magazyn_stan_pv + magazyn_stan_siec
                if (magazyn and magazyn.pojemnosc_kwh > 0 and
                        g == godzina_rozladowania and magazyn_stan > 0):

                    if magazyn.priorytet == "sprzedaz":
                        # Sprzedaj TYLKO czesc PV z magazynu (energia z sieci nie moze byc sprzedana)
                        do_sprzedazy_raw = min(magazyn_stan_pv, magazyn_moc_rozlad_wh)
                        if do_sprzedazy_raw > 0:
                            magazyn_stan_pv -= do_sprzedazy_raw
                            do_sprzedazy = do_sprzedazy_raw * sprawnosc_rozladowania
                            cena_sprzedazy = oblicz_cene_sprzedazy(miesiac, g, marza_sprzedawcy)
                            przychod = (do_sprzedazy / 1000.0) * cena_sprzedazy
                            wyniki_miesieczne[mi]["magazyn_rozladowanie_kwh"] += do_sprzedazy / 1000.0
                            wyniki_miesieczne[mi]["sprzedaz_kwh"] += do_sprzedazy / 1000.0
                            wyniki_miesieczne[mi]["przychod_sprzedazy_zl"] += przychod

                    elif magazyn.priorytet == "autokonsumpcja" and g == godzina_rozladowania:
                        # Rozladuj magazyn na autokonsumpcje w szczycie
                        # Jesli nie bylo niedoboru w tej godzinie (PV pokrywa zuzycie),
                        # rozladuj magazyn aby pokryc zuzycie - nadwyzka PV jest wtedy
                        # sprzedawana po wysokiej cenie szczytowej
                        if bilans >= 0:
                            zuzycie_godziny = dane_dnia[g][1]
                            rozlad_docelowy = min(zuzycie_godziny, magazyn_moc_rozlad_wh, magazyn_stan)
                            if rozlad_docelowy > 0:
                                udzial_pv = magazyn_stan_pv / magazyn_stan if magazyn_stan > 0 else 0.0
                                rozlad_pv = rozlad_docelowy * udzial_pv
                                rozlad_siec = rozlad_docelowy * (1.0 - udzial_pv)
                                magazyn_stan_pv -= rozlad_pv
                                magazyn_stan_siec -= rozlad_siec
                                energia_dostarczona = rozlad_docelowy * sprawnosc_rozladowania
                                wyniki_miesieczne[mi]["magazyn_rozladowanie_kwh"] += energia_dostarczona / 1000.0
                                # Magazyn pokrywa zuzycie zamiast PV - uwolniona PV idzie na sprzedaz
                                # nadwyzka_uwolniona = ile zuzycia magazyn pokryl (nie wiecej niz zuzycie)
                                # Odejmujemy od autokonsumpcja_kwh bo teraz magazyn (nie PV) pokrywa zuzycie
                                nadwyzka_uwolniona = min(energia_dostarczona, zuzycie_godziny)
                                if nadwyzka_uwolniona > 0:
                                    wyniki_miesieczne[mi]["autokonsumpcja_kwh"] -= nadwyzka_uwolniona / 1000.0
                                    cena_sprzedazy = oblicz_cene_sprzedazy(miesiac, g, marza_sprzedawcy)
                                    przychod = (nadwyzka_uwolniona / 1000.0) * cena_sprzedazy
                                    wyniki_miesieczne[mi]["sprzedaz_kwh"] += nadwyzka_uwolniona / 1000.0
                                    wyniki_miesieczne[mi]["przychod_sprzedazy_zl"] += przychod

                # Zabezpieczenie przed ujemnymi wartosciami
                if magazyn_stan_pv < 0:
                    magazyn_stan_pv = 0.0
                if magazyn_stan_siec < 0:
                    magazyn_stan_siec = 0.0

            indeks += len(dane_dnia)

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

    # Komunikat o strategii magazynu
    if taryfa_dynamiczna and magazyn and magazyn.pojemnosc_kwh > 0:
        uwaga = ("Magazyn ladowany z PV (priorytet) i z sieci w najtanszych godzinach "
                 "(fallback na autokonsumpcje). Energia z sieci w magazynie NIE moze byc sprzedawana.")
    else:
        uwaga = "Magazyn ladowany TYLKO z nadwyzki PV. Dla taryfy stalej (G11) ladowanie z sieci nieaktywne."

    return {
        "taryfa": taryfa,
        "rok": rok,
        "podsumowanie_roczne": roczne,
        "miesiace": wyniki_miesieczne,
        "oplaty_stale_miesieczne_zl": oplaty_stale_mc,
        "magazyn_uzyty": magazyn is not None and magazyn.pojemnosc_kwh > 0,
        "uwaga_arbitraz": uwaga,
    }

