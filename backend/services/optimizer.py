"""
Serwis logiki optymalizatorow mocy (Power Optimizers).

Optymalizatory mocy (np. SolarEdge, Tigo) to urzadzenia montowane
na kazdym panelu, ktore zapewniaja niezalezne sledzenie MPPT
(Maximum Power Point Tracking) dla kazdego panela osobno.

Kluczowe zasady:
1. BEZ optymalizatorow: panele polaczone szeregowo w string. Prad calego
   stringa jest ograniczony przez panel o najnizszym pradzie (najgorzej
   zacieniony). Jeden zacieniony panel obniza wydajnosc calego stringa.

2. Z optymalizatorami: kazdy panel ma wlasne MPPT. Zacieniony panel
   produkuje mniej, ale NIE wplywa na inne panele w stringu.

3. Zastosowanie praktyczne:
   - Optymalizatory stosuje sie TYLKO gdy jest realne zacienienie
   - Nie montuje sie ich "profilaktycznie" (koszt nieuzasadniony)
   - Typowe producenty: SolarEdge (zintegrowane z falownikiem), Tigo (addon)
   - Wymagaja kompatybilnego falownika (SolarEdge wymaga swoich falownikow)
"""

import math
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from backend.services.shading import WynikZacienieniaPanel
from backend.services.panel_performance import (
    oblicz_wspolczynnik_zacienienia,
    oblicz_wydajnosc_panela,
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    STRATY_SYSTEMOWE_DOMYSLNE,
)


@dataclass
class KonfiguracjaStringa:
    """
    Konfiguracja stringa paneli (polaczenie szeregowe).

    Atrybuty:
        indeksy_paneli: lista indeksow paneli w tym stringu
        nazwa: opcjonalna nazwa stringa (np. "String 1")
    """
    indeksy_paneli: List[int] = field(default_factory=list)
    nazwa: str = ""


@dataclass
class WynikOptymalizatora:
    """
    Wynik porownania pracy z i bez optymalizatorow.

    Atrybuty:
        energia_bez_optymalizatorow_wh: energia godzinowa bez optymalizatorow [Wh]
        energia_z_optymalizatorami_wh: energia godzinowa z optymalizatorami [Wh]
        zysk_optymalizatorow_wh: roznica energii [Wh]
        zysk_procent: procentowy zysk z optymalizatorow
        mismatch_loss_procent: strata z powodu mismatch (bez optymalizatorow)
    """
    energia_bez_optymalizatorow_wh: float = 0.0
    energia_z_optymalizatorami_wh: float = 0.0
    zysk_optymalizatorow_wh: float = 0.0
    zysk_procent: float = 0.0
    mismatch_loss_procent: float = 0.0


def oblicz_mismatch_stringa(wspolczynniki_zacienienia: List[float]) -> float:
    """
    Oblicza strate mismatch w stringu paneli bez optymalizatorow.

    W polaczeniu szeregowym prad calego stringa jest ograniczony
    przez panel z najnizszym pradem. Jesli jeden panel jest zacieniony,
    caly string traci proporcjonalnie.

    Parametry:
        wspolczynniki_zacienienia: lista wspolczynnikow (0-1) dla kazdego panela

    Zwraca:
        Wspolczynnik mocy calego stringa (0-1).
        Bez mismatch bylby to srednia, z mismatch to minimum.
    """
    if not wspolczynniki_zacienienia:
        return 1.0

    # W polaczeniu szeregowym prad ogranicza najslabszy panel
    # Kazdy panel ma prad proporcjonalny do swojego wspolczynnika
    # Prad stringa = min(prady paneli)
    # Ale napiecie jest sumowane, wiec moc stringa = V_sum * I_min
    # To upraszczamy: najgorszy panel determinuje prad calego stringa

    min_wsp = min(wspolczynniki_zacienienia)
    srednia_wsp = sum(wspolczynniki_zacienienia) / len(wspolczynniki_zacienienia)

    if srednia_wsp <= 0:
        return 0.0

    # Mismatch: moc stringa = napiecie kazdego panela * wspolny prad (minimum)
    # Dokladniej: kazdy panel pracuje na pradzie min, wiec kazdy traci
    # Moc stringa = suma(V_i) * I_min
    # Jesli wszystkie panele maja te sama charakterystyke V-I,
    # to V_i przy I_min jest bliskie V_mpp (bo prad jest ograniczony)
    # Uproszczenie: moc stringa = N * V_mpp * I_min = N * P_mpp * min_wsp
    # Srednia moc bez mismatch = N * P_mpp * srednia_wsp
    # Wiec: wsp_stringa = min_wsp (bo kazdy panel jest ograniczony do tego pradu)

    # Bardziej realistyczny model:
    # Panele bez zacienienia pracuja na swoim MPP (max moc)
    # Panel zacieniony ogranicza prad - wszystkie panele daja mniej
    # Ale bypass diody pomagaja - omijaja zacieniony panel
    # Wiec strata nie jest az tak dramatyczna

    # Uproszczony model: moc stringa = srednia * (min/srednia)^0.5
    # To daje mniejsza strate niz czyste minimum, ale wieksza niz srednia
    if min_wsp >= srednia_wsp * 0.99:
        # Prawie brak mismatch
        return srednia_wsp

    # Mismatch: moc jest ograniczona przez najgorszy panel
    # ale nie tak drastycznie jak czyste minimum (dzieki bypass)
    # Realistyczny model: moc = min_wsp (najgorszy przypadek)
    return min_wsp


def oblicz_produkcje_stringa_bez_optymalizatorow(
        wspolczynniki_zacienienia_paneli: List[float],
        moc_stc_w: float,
        napromieniowanie_wm2: float,
        temperatura_panela_c: float,
        wspolczynnik_temp: float,
        straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
        degradacja_roczna: float = 0.005,
        rok_eksploatacji: int = 1) -> float:
    """
    Oblicza laczna produkcje stringa paneli BEZ optymalizatorow.

    Mismatch loss: najgorszy panel ogranicza caly string.

    Parametry:
        wspolczynniki_zacienienia_paneli: wspolczynniki zacienienia (0-1) kazdego panela
        moc_stc_w: moc nominalna jednego panela [W]
        napromieniowanie_wm2: napromieniowanie [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wspolczynnik_temp: wspolczynnik temperaturowy [%/C]
        straty_systemowe: straty kablowe + falownik
        degradacja_roczna: degradacja roczna
        rok_eksploatacji: rok eksploatacji

    Zwraca:
        Laczna energia stringa w [Wh]
    """
    if napromieniowanie_wm2 <= 0:
        return 0.0

    n_paneli = len(wspolczynniki_zacienienia_paneli)
    if n_paneli == 0:
        return 0.0

    # Mismatch - najgorszy panel ogranicza string
    wsp_mismatch = oblicz_mismatch_stringa(wspolczynniki_zacienienia_paneli)

    # Kazdy panel w stringu produkuje moc ograniczona przez mismatch
    wynik = oblicz_wydajnosc_panela(
        moc_stc_w, napromieniowanie_wm2, temperatura_panela_c,
        wspolczynnik_temp, wsp_mismatch,
        straty_systemowe, degradacja_roczna, rok_eksploatacji
    )

    # Caly string - N paneli po tej samej mocy (ograniczonej)
    return wynik.energia_wh * n_paneli


def oblicz_produkcje_stringa_z_optymalizatorami(
        wspolczynniki_zacienienia_paneli: List[float],
        moc_stc_w: float,
        napromieniowanie_wm2: float,
        temperatura_panela_c: float,
        wspolczynnik_temp: float,
        straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
        degradacja_roczna: float = 0.005,
        rok_eksploatacji: int = 1) -> float:
    """
    Oblicza laczna produkcje stringa paneli Z optymalizatorami.

    Kazdy panel pracuje niezaleznie na swoim MPPT.
    Zacieniony panel nie wplywa na inne panele.

    Parametry:
        (jak w oblicz_produkcje_stringa_bez_optymalizatorow)

    Zwraca:
        Laczna energia stringa w [Wh]
    """
    if napromieniowanie_wm2 <= 0:
        return 0.0

    energia_calkowita = 0.0

    for wsp_zacien in wspolczynniki_zacienienia_paneli:
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w, napromieniowanie_wm2, temperatura_panela_c,
            wspolczynnik_temp, wsp_zacien,
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )
        energia_calkowita += wynik.energia_wh

    return energia_calkowita


def porownaj_z_bez_optymalizatorow(
        wspolczynniki_zacienienia_paneli: List[float],
        moc_stc_w: float,
        napromieniowanie_wm2: float,
        temperatura_panela_c: float,
        wspolczynnik_temp: float,
        straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE) -> WynikOptymalizatora:
    """
    Porownuje produkcje z i bez optymalizatorow dla jednej godziny.

    Parametry:
        wspolczynniki_zacienienia_paneli: wspolczynniki kazdego panela
        moc_stc_w: moc nominalna jednego panela [W]
        napromieniowanie_wm2: napromieniowanie [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wspolczynnik_temp: wspolczynnik temperaturowy [%/C]
        straty_systemowe: straty systemowe

    Zwraca:
        WynikOptymalizatora z porownaniem
    """
    energia_bez = oblicz_produkcje_stringa_bez_optymalizatorow(
        wspolczynniki_zacienienia_paneli,
        moc_stc_w, napromieniowanie_wm2, temperatura_panela_c,
        wspolczynnik_temp, straty_systemowe
    )

    energia_z = oblicz_produkcje_stringa_z_optymalizatorami(
        wspolczynniki_zacienienia_paneli,
        moc_stc_w, napromieniowanie_wm2, temperatura_panela_c,
        wspolczynnik_temp, straty_systemowe
    )

    zysk = energia_z - energia_bez
    zysk_procent = (zysk / energia_bez * 100.0) if energia_bez > 0 else 0.0

    # Mismatch loss
    mismatch = 0.0
    if energia_z > 0:
        mismatch = (1.0 - energia_bez / energia_z) * 100.0

    return WynikOptymalizatora(
        energia_bez_optymalizatorow_wh=round(energia_bez, 2),
        energia_z_optymalizatorami_wh=round(energia_z, 2),
        zysk_optymalizatorow_wh=round(zysk, 2),
        zysk_procent=round(zysk_procent, 2),
        mismatch_loss_procent=round(mismatch, 2),
    )


def czy_optymalizatory_uzasadnione(strata_roczna_zacienienie_procent: float,
                                    liczba_paneli: int,
                                    moc_panela_wp: float) -> Dict:
    """
    Ocenia czy zastosowanie optymalizatorow jest uzasadnione ekonomicznie.

    Zasady praktyczne:
    - Optymalizatory kosztuja ok. 200-400 PLN za sztuke
    - Mają sens gdy straty z zacienienia > 5-10% rocznej produkcji
    - Nie stosuje sie ich profilaktycznie (bez realnego zacienienia)
    - Musza byc kompatybilne z falownikiem (SolarEdge = wlasny system)

    Parametry:
        strata_roczna_zacienienie_procent: roczna strata z zacienienia [%]
        liczba_paneli: liczba paneli w instalacji
        moc_panela_wp: moc pojedynczego panela [Wp]

    Zwraca:
        Slownik z rekomendacja i uzasadnieniem
    """
    # Szacunkowy koszt optymalizatora na panel [PLN]
    KOSZT_OPTYMALIZATORA_PLN = 300.0

    # Szacunkowa cena energii [PLN/kWh]
    CENA_ENERGII_PLN = 0.75

    # Szacunkowa roczna produkcja na 1 kWp w Polsce [kWh]
    PRODUKCJA_NA_KWP = 1000.0

    # Okres zwrotu akceptowalny [lata]
    MAX_OKRES_ZWROTU = 8

    koszt_calkowity = KOSZT_OPTYMALIZATORA_PLN * liczba_paneli
    moc_instalacji_kwp = (moc_panela_wp * liczba_paneli) / 1000.0
    roczna_produkcja_kwh = moc_instalacji_kwp * PRODUKCJA_NA_KWP

    # Zysk z optymalizatorow = odzyskana energia * cena
    # Optymalizatory odzyskuja ok. 70-80% straty mismatch
    odzyskanie_procent = strata_roczna_zacienienie_procent * 0.75
    roczny_zysk_kwh = roczna_produkcja_kwh * (odzyskanie_procent / 100.0)
    roczny_zysk_pln = roczny_zysk_kwh * CENA_ENERGII_PLN

    # Okres zwrotu
    if roczny_zysk_pln > 0:
        okres_zwrotu_lat = koszt_calkowity / roczny_zysk_pln
    else:
        okres_zwrotu_lat = 999.0

    # Decyzja
    uzasadnione = (strata_roczna_zacienienie_procent >= 5.0 and
                   okres_zwrotu_lat <= MAX_OKRES_ZWROTU)

    if strata_roczna_zacienienie_procent < 3.0:
        rekomendacja = "NIE - minimalne zacienienie, optymalizatory nieuzasadnione"
    elif strata_roczna_zacienienie_procent < 5.0:
        rekomendacja = "WĄTPLIWE - niewielkie zacienienie, rozważ inne rozwiązania"
    elif okres_zwrotu_lat > MAX_OKRES_ZWROTU:
        rekomendacja = "NIE - okres zwrotu za długi"
    else:
        rekomendacja = "TAK - optymalizatory uzasadnione ekonomicznie"

    return {
        "uzasadnione": uzasadnione,
        "rekomendacja": rekomendacja,
        "strata_zacienienie_procent": round(strata_roczna_zacienienie_procent, 2),
        "koszt_optymalizatorow_pln": round(koszt_calkowity, 0),
        "roczny_zysk_pln": round(roczny_zysk_pln, 0),
        "okres_zwrotu_lat": round(okres_zwrotu_lat, 1),
        "odzyskanie_energii_procent": round(odzyskanie_procent, 2),
    }
