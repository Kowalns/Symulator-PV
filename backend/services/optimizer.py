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


def podziel_na_stringi(liczba_paneli: int,
                       napiecie_mpp_panela: float,
                       zakres_mppt_min: float,
                       zakres_mppt_max: float) -> List[KonfiguracjaStringa]:
    """
    Automatycznie dzieli panele na stringi na podstawie zakresu MPPT falownika.

    Oblicza maksymalna i minimalna liczbe paneli w stringu na podstawie
    napiecia Vmpp panela i zakresu napieciowego MPPT falownika.
    Nastepnie rozdziela panele rownomiernie na stringi.

    Parametry:
        liczba_paneli: calkowita liczba paneli w instalacji
        napiecie_mpp_panela: napiecie w punkcie mocy maksymalnej (Vmpp) [V]
        zakres_mppt_min: minimalne napiecie MPPT falownika [V]
        zakres_mppt_max: maksymalne napiecie MPPT falownika [V]

    Zwraca:
        Lista obiektow KonfiguracjaStringa z przydzielonymi indeksami paneli
    """
    if liczba_paneli <= 0 or napiecie_mpp_panela <= 0:
        return []

    if zakres_mppt_max <= 0 or zakres_mppt_min <= 0:
        return [KonfiguracjaStringa(
            indeksy_paneli=list(range(liczba_paneli)),
            nazwa="String 1"
        )]

    # Maksymalna liczba paneli w stringu (nie przekraczac max napiecia MPPT)
    max_per_string = math.floor(zakres_mppt_max / napiecie_mpp_panela)
    # Minimalna liczba paneli w stringu (napiecie musi przekroczyc min MPPT)
    min_per_string = math.ceil(zakres_mppt_min / napiecie_mpp_panela)

    # Zabezpieczenie - minimum 1 panel na string
    max_per_string = max(1, max_per_string)
    min_per_string = max(1, min_per_string)

    # Jesli min > max - zakres MPPT jest za waski dla tego panela
    if min_per_string > max_per_string:
        # Fallback: jeden string z wszystkimi panelami
        return [KonfiguracjaStringa(
            indeksy_paneli=list(range(liczba_paneli)),
            nazwa="String 1"
        )]

    # Optymalna dlugosc stringa - preferuj srodek zakresu
    optymalna_dlugosc = (min_per_string + max_per_string) // 2
    optymalna_dlugosc = max(min_per_string, min(max_per_string, optymalna_dlugosc))

    # Ile stringow potrzebujemy?
    if optymalna_dlugosc >= liczba_paneli:
        # Wszystkie panele mieszcza sie w jednym stringu
        return [KonfiguracjaStringa(
            indeksy_paneli=list(range(liczba_paneli)),
            nazwa="String 1"
        )]

    # Oblicz liczbe stringow
    liczba_stringow = math.ceil(liczba_paneli / optymalna_dlugosc)

    # Rozdziel panele rownomiernie
    stringi = []
    panele_przydzielone = 0
    for i in range(liczba_stringow):
        # Rownomierny podzial - pozostale panele rozloz po jednym
        panele_w_stringu = liczba_paneli // liczba_stringow
        if i < (liczba_paneli % liczba_stringow):
            panele_w_stringu += 1

        indeksy = list(range(panele_przydzielone, panele_przydzielone + panele_w_stringu))
        stringi.append(KonfiguracjaStringa(
            indeksy_paneli=indeksy,
            nazwa=f"String {i + 1}"
        ))
        panele_przydzielone += panele_w_stringu

    return stringi


def oblicz_mismatch_stringa(wspolczynniki_zacienienia: List[float],
                            liczba_sekcji_bypass: int = 3) -> float:
    """
    Oblicza strate mismatch w stringu paneli bez optymalizatorow,
    uwzgledniajac dzialanie bypass diod.

    Model bypass diod w stringu:
    - W polaczeniu szeregowym prad jest ograniczony przez najslabsze ogniwo
    - Bypass diody pozwalaja ominac zacienione sekcje panela
    - Ominieta sekcja nie ogranicza pradu stringa
    - Panel z bypass traci moc proportionally do ominiętych sekcji
    - Reszta stringa pracuje normalnie

    Wynik jest zawsze:
    - Lepszy niz czyste minimum (stary model bez bypass)
    - Gorszy niz srednia (model z optymalizatorami)

    Parametry:
        wspolczynniki_zacienienia: lista wspolczynnikow (0-1) dla kazdego panela
        liczba_sekcji_bypass: ile sekcji bypass ma kazdy panel (domyslnie 3)

    Zwraca:
        Wspolczynnik mocy calego stringa (0-1).
    """
    if not wspolczynniki_zacienienia:
        return 1.0

    n = len(wspolczynniki_zacienienia)
    if n == 0:
        return 1.0

    min_wsp = min(wspolczynniki_zacienienia)
    srednia_wsp = sum(wspolczynniki_zacienienia) / n

    if srednia_wsp <= 0:
        return 0.0

    # Jesli nie ma roznicy (brak mismatch) - zwroc srednia
    if min_wsp >= srednia_wsp * 0.99:
        return srednia_wsp

    # Model bypass diod:
    # Bez bypass (stary model): wynik = min_wsp (caly string na najgorszym panelu)
    # Z bypass: zacienione sekcje najgorszego panela sa ominięte,
    # string traci tylko wklad napieciowy tych sekcji z calkowitego napiecia.
    #
    # Ile sekcji traci najgorszy panel?
    # stopien_zacienienia = (1 - min_wsp)
    # Sekcje sa aktywowane gdy pokrycie >50%
    stopien_zacienienia_max = 1.0 - min_wsp

    zacienione_sekcje = 0
    for s in range(liczba_sekcji_bypass):
        sekcja_start = s / liczba_sekcji_bypass
        sekcja_end = (s + 1) / liczba_sekcji_bypass
        pokrycie = max(0.0, min(stopien_zacienienia_max, sekcja_end) - sekcja_start)
        pokrycie_procent = pokrycie * liczba_sekcji_bypass
        if pokrycie_procent > 0.15:
            zacienione_sekcje += 1

    # Efektywna moc panela z bypass: aktywne sekcje pracuja,
    # prad nie jest ograniczony przez ominięte sekcje
    aktywne_sekcje = liczba_sekcji_bypass - zacienione_sekcje
    efektywny_wsp_bypass = aktywne_sekcje / liczba_sekcji_bypass

    # Moc stringa z bypass:
    # - (N-1) paneli bez zacienienia pracuje normalnie (wspolczynnik 1.0 lub ich wlasny)
    # - Najgorszy panel daje efektywny_wsp_bypass zamiast min_wsp
    # Ale prad stringa jest ograniczony przez efektywny prad najgorszego panela
    # (aktywne sekcje tego panela moga byc czesciowo zacienione)
    #
    # Uproszczenie: prad stringa = efektywny_wsp_bypass
    # Moc stringa = srednia napiecia * prad
    # Srednia napiecia jest bliska 1 (wieksczosc paneli pelna)
    # ale najgorszy panel daje mniej napiecia (bypass sekcje)
    #
    # Realistycznie: moc stringa = srednia wspolczynnikow z uwzglednieniem bypass
    # gdzie kazdy panel jest ograniczony do max(min_efektywny, swoj_wspolczynnik)
    # ale min_efektywny po bypass jest wyzsze niz czyste minimum

    # Wynikowy wspolczynnik: interpolacja miedzy min (bez bypass) a bypass model
    # String z bypass: N-1 paneli na pelnej mocy, 1 panel na bypass_wsp
    # To daje srednia = ((N-1) * srednia_reszty + efektywny_wsp_bypass) / N
    # Ale musi byc gorszy niz optymalizatory (srednia surowa)

    # Oblicz wsp bez najgorszego panela
    wspolczynniki_sorted = sorted(wspolczynniki_zacienienia)
    suma_reszty = sum(wspolczynniki_sorted[1:])  # bez najgorszego
    srednia_reszty = suma_reszty / (n - 1) if n > 1 else 0.0

    # Moc stringa z bypass: niezacienione panele pracuja na swoim MPP
    # ale prad jest ograniczony przez aktywne sekcje najgorszego panela
    # Prad stringa = efektywny_wsp_bypass (bo bypass omija zacienione sekcje)
    # Ale kazdy panel i tak produkuje co moze przy tym pradzie

    # Uproszczony model realny:
    # Moc stringa = min(efektywny_wsp_bypass, srednia_reszty) * napiecia
    # efektywny_wsp_bypass ogranicza prad, ale jest wyzszy niz min_wsp
    wynik = efektywny_wsp_bypass

    # Wynik powinien byc lepszy niz min_wsp ale gorszy niz srednia (optymalizatory)
    # Zapewniamy to ograniczeniem
    wynik = max(wynik, min_wsp)
    wynik = min(wynik, srednia_wsp)

    return wynik


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
