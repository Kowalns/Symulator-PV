"""
Serwis obliczania wydajnosci paneli PV.

Uwzglednia:
1. Wplyw temperatury (wspolczynnik temperaturowy mocy z danych panela)
2. Wplyw zacienienia z bypass diodami i technologia half-cut
3. Nasycenie promieniowaniem (irradiance) - uproszczony model dla Polski
4. Degradacja roczna paneli (typowo 0.5%)
5. Straty kablowe i na falowniku (2-5%)

Formula wydajnosci:
P_actual = P_stc * (G/1000) * (1 + coeff_temp * (T_panel - 25)) * shading_factor * (1 - system_losses)

Gdzie:
- P_stc: moc w warunkach STC [W]
- G: napromieniowanie [W/m2]
- coeff_temp: wspolczynnik temp. mocy [%/C] (np. -0.35)
- T_panel: temperatura panela [C]
- shading_factor: wspolczynnik redukcji od zacienienia (0-1)
- system_losses: straty systemowe (0.02-0.05)

Profil temperatury otoczenia dla Polski (srednie miesieczne):
Jan=-3, Feb=-1, Mar=3, Apr=9, May=14, Jun=17, Jul=20, Aug=19, Sep=14, Oct=9, Nov=4, Dec=-1

Temperatura panela = T_otoczenia + 25-30C (korekta NOCT)
"""

import math
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from backend.services.shading import WynikZacienieniaPanel


# Srednie miesieczne temperatury otoczenia w Polsce [C]
# Indeks 0 = styczen, indeks 11 = grudzien
TEMPERATURA_OTOCZENIA_POLSKA = [-3.0, -1.0, 3.0, 9.0, 14.0, 17.0,
                                 20.0, 19.0, 14.0, 9.0, 4.0, -1.0]

# Korekta NOCT - roznica miedzy temperatura panela a otoczenia [C]
# Panel w sloncu nagrzewa sie o ok. 25-30C powyzej otoczenia
DELTA_T_NOCT = 28.0

# Domyslne straty systemowe (kable + falownik)
STRATY_SYSTEMOWE_DOMYSLNE = 0.03  # 3%

# Uproszczony model napromieniowania dla Polski [W/m2]
# Srednia godzinowa irradiancja dla godzin slonecznych (wyzej = lato, nizej = zima)
# Wartosci szczytowe w poludnie, niskie rano/wieczorem
# Indeks 0=styczen, 11=grudzien - szczytowe napromieniowanie w poludnie
NAPROMIENIOWANIE_SZCZYTOWE_POLSKA = [200, 300, 450, 600, 750, 850,
                                      900, 800, 600, 400, 250, 150]


@dataclass
class WynikWydajnosciPanel:
    """
    Wynik obliczen wydajnosci pojedynczego panela w danej godzinie.

    Atrybuty:
        panel_index: numer panela
        moc_nominalna_w: moc nominalna w STC [W]
        moc_aktualna_w: moc po uwzglednieniu wszystkich strat [W]
        napromieniowanie_wm2: nasycenie promieniowaniem [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wsp_temperaturowy: mnoznik temperaturowy (< 1 w upale, > 1 w zimie)
        wsp_zacienienia: mnoznik zacienienia (0 do 1)
        wsp_strat_systemowych: mnoznik strat (0.95-0.98 typowo)
        wsp_degradacji: mnoznik degradacji (0.995 po 1 roku)
        energia_wh: energia wyprodukowana w tej godzinie [Wh]
    """
    panel_index: int = 0
    moc_nominalna_w: float = 0.0
    moc_aktualna_w: float = 0.0
    napromieniowanie_wm2: float = 0.0
    temperatura_panela_c: float = 25.0
    wsp_temperaturowy: float = 1.0
    wsp_zacienienia: float = 1.0
    wsp_strat_systemowych: float = 0.97
    wsp_degradacji: float = 1.0
    energia_wh: float = 0.0


def oblicz_temperature_panela(miesiac: int, godzina: int) -> float:
    """
    Oblicza temperature panela na podstawie miesiaca i godziny.

    Temperatura panela = T_otoczenia + NOCT_korekta * (G/800)
    W nocy panel ma temperature otoczenia.
    W ciagu dnia nagrzewa sie proporcjonalnie do napromieniowania.

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Temperatura panela w [C]
    """
    t_otoczenia = TEMPERATURA_OTOCZENIA_POLSKA[miesiac - 1]

    # Prosta modulacja temperatury w ciagu dnia
    # Godziny sloneczne: 6-20 (przyblizone)
    if godzina < 6 or godzina > 20:
        return t_otoczenia

    # Wspolczynnik dnia (0 rano/wieczorem, 1 w poludnie)
    if godzina <= 13:
        wsp_dnia = (godzina - 6) / 7.0
    else:
        wsp_dnia = (20 - godzina) / 7.0
    wsp_dnia = max(0.0, min(1.0, wsp_dnia))

    # Temperatura panela z korrekta NOCT
    t_panel = t_otoczenia + DELTA_T_NOCT * wsp_dnia

    return t_panel


def oblicz_napromieniowanie(miesiac: int, godzina: int, elewacja_slonca: float) -> float:
    """
    Oblicza napromieniowanie (irradiance) na podstawie pozycji Slonca.

    Uproszczony model: irradiancja proporcjonalna do sin(elewacja)
    z korrekta na porz roku (miesieczna srednia).

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)
        elewacja_slonca: elewacja Slonca [stopnie]

    Zwraca:
        Napromieniowanie w [W/m2] (0 gdy Slonce pod horyzontem)
    """
    if elewacja_slonca <= 0:
        return 0.0

    # Szczytowa irradiancja dla danego miesiaca
    szczytowe = NAPROMIENIOWANIE_SZCZYTOWE_POLSKA[miesiac - 1]

    # Irradiancja proporcjonalna do sin(elewacja)
    # Przy elewacji 90 stopni = szczytowa, przy niskiej elewacji = mniejsza
    sin_elewacja = math.sin(math.radians(elewacja_slonca))

    # Dodatkowy wspolczynnik atmosferyczny (air mass)
    # Im nizej Slonce, tym wiecej atmosfery przechodzi promien
    irradiancja = szczytowe * sin_elewacja

    # Ograniczenie do maksimum 1000 W/m2 (warunki STC)
    return min(1000.0, max(0.0, irradiancja))


def oblicz_wspolczynnik_zacienienia(zacienienie: WynikZacienieniaPanel,
                                     liczba_sekcji: int = 3,
                                     technologia: str = "standard") -> float:
    """
    Oblicza wspolczynnik redukcji mocy z powodu zacienienia.

    Reguly:
    1. Bypass diody: jesli sekcja zacieniona >50%, bypass aktywuje sie,
       sekcja daje 0 mocy (strata ~1/liczba_sekcji mocy panela).
    2. Half-cut: panel ma 2 niezalezne polowy. Jesli zacieniona jest
       tylko jedna polowa, druga produkuje normalnie (50% mocy).
    3. Bez half-cut i bypass: strata proporcjonalna do zacienienia.

    Parametry:
        zacienienie: wynik analizy zacienienia panela
        liczba_sekcji: liczba sekcji bypass (typowo 3)
        technologia: "half-cut" lub "standard"

    Zwraca:
        Wspolczynnik mocy 0.0 (caly panel wyciemniony) do 1.0 (bez strat)
    """
    if zacienienie.stopien_zacienienia <= 0:
        return 1.0

    if zacienienie.stopien_zacienienia >= 1.0:
        return 0.0

    # Jesli mamy informacje o bypass diodach
    if zacienienie.sekcje_zacienione:
        if technologia == "half-cut":
            # Half-cut: 2 niezalezne polowy
            # Jesli tylko jedna polowa zacieniona, druga daje pelna moc
            if zacienienie.polowa_gorna_zacieniona and not zacienienie.polowa_dolna_zacieniona:
                # Dolna polowa produkuje normalnie
                return 0.5
            elif zacienienie.polowa_dolna_zacieniona and not zacienienie.polowa_gorna_zacieniona:
                # Gorna polowa produkuje normalnie
                return 0.5
            elif zacienienie.polowa_gorna_zacieniona and zacienienie.polowa_dolna_zacieniona:
                # Obie polowy zacienione - strata proporcjonalna do bypass
                bypass = zacienienie.bypass_aktywne
                return max(0.0, 1.0 - bypass / liczba_sekcji)
            else:
                # Zadna polowa nie zacieniona wystarczajaco (>50%)
                # Ale poszczegolne sekcje moga byc aktywne
                bypass = zacienienie.bypass_aktywne
                if bypass > 0:
                    # Half-cut zmniejsza wplyw: kazdy bypass to strata polowy sekcji
                    # bo w half-cut sekcja jest podzielona na 2 polowki
                    return max(0.0, 1.0 - bypass / (liczba_sekcji * 2.0))
                else:
                    # Drobne zacienienie bez aktywacji bypass
                    return 1.0 - zacienienie.stopien_zacienienia * 0.3
        else:
            # Standard (bez half-cut): bypass diody standardowo
            bypass = zacienienie.bypass_aktywne
            if bypass > 0:
                # Kazda aktywna bypass to strata 1/N mocy
                return max(0.0, 1.0 - bypass / liczba_sekcji)
            else:
                # Drobne zacienienie bez aktywacji bypass - strata proporcjonalna
                return 1.0 - zacienienie.stopien_zacienienia * 0.5

    # Fallback: proporcjonalna strata
    return 1.0 - zacienienie.stopien_zacienienia


def oblicz_wydajnosc_panela(moc_stc_w: float,
                            napromieniowanie_wm2: float,
                            temperatura_panela_c: float,
                            wspolczynnik_temp_pmax: float,
                            wspolczynnik_zacienienia: float,
                            straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
                            degradacja_roczna: float = 0.005,
                            rok_eksploatacji: int = 1) -> WynikWydajnosciPanel:
    """
    Oblicza aktualna moc panela z uwzglednieniem wszystkich strat.

    Formula: P = P_stc * (G/1000) * wsp_temp * wsp_zacien * (1-straty) * wsp_degrad

    Parametry:
        moc_stc_w: moc nominalna w warunkach STC [W]
        napromieniowanie_wm2: napromieniowanie [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wspolczynnik_temp_pmax: wspolczynnik temperaturowy [%/C] (np. -0.35)
        wspolczynnik_zacienienia: wspolczynnik redukcji od cienia (0-1)
        straty_systemowe: straty na kablach i falowniku (0.02-0.05)
        degradacja_roczna: roczna degradacja mocy (0.005 = 0.5%)
        rok_eksploatacji: ktory rok eksploatacji (1 = pierwszy)

    Zwraca:
        WynikWydajnosciPanel z obliczona moca i energia
    """
    # Brak produkcji bez napromieniowania
    if napromieniowanie_wm2 <= 0:
        return WynikWydajnosciPanel(
            moc_nominalna_w=moc_stc_w,
            moc_aktualna_w=0.0,
            napromieniowanie_wm2=0.0,
            temperatura_panela_c=temperatura_panela_c,
            wsp_temperaturowy=1.0,
            wsp_zacienienia=wspolczynnik_zacienienia,
            wsp_strat_systemowych=1.0 - straty_systemowe,
            energia_wh=0.0,
        )

    # 1. Wspolczynnik napromieniowania (STC = 1000 W/m2)
    wsp_irradiancja = napromieniowanie_wm2 / 1000.0

    # 2. Wspolczynnik temperaturowy
    # wspolczynnik_temp_pmax jest podawany jako %/C (np. -0.35)
    # Delta T = T_panel - 25C (temperatura STC)
    delta_t = temperatura_panela_c - 25.0
    wsp_temp = 1.0 + (wspolczynnik_temp_pmax / 100.0) * delta_t

    # Ograniczenie do sensownych wartosci
    wsp_temp = max(0.5, min(1.2, wsp_temp))

    # 3. Wspolczynnik degradacji
    wsp_degradacji = (1.0 - degradacja_roczna) ** (rok_eksploatacji - 1)

    # 4. Wspolczynnik strat systemowych
    wsp_strat = 1.0 - straty_systemowe

    # Obliczenie mocy aktualnej
    moc_aktualna = (moc_stc_w * wsp_irradiancja * wsp_temp *
                    wspolczynnik_zacienienia * wsp_strat * wsp_degradacji)

    # Moc nie moze byc ujemna
    moc_aktualna = max(0.0, moc_aktualna)

    # Energia w Wh (moc * 1 godzina)
    energia_wh = moc_aktualna

    return WynikWydajnosciPanel(
        moc_nominalna_w=moc_stc_w,
        moc_aktualna_w=round(moc_aktualna, 2),
        napromieniowanie_wm2=napromieniowanie_wm2,
        temperatura_panela_c=temperatura_panela_c,
        wsp_temperaturowy=round(wsp_temp, 4),
        wsp_zacienienia=wspolczynnik_zacienienia,
        wsp_strat_systemowych=round(wsp_strat, 4),
        wsp_degradacji=round(wsp_degradacji, 6),
        energia_wh=round(energia_wh, 2),
    )


def oblicz_roczna_produkcje_panela(moc_stc_w: float,
                                    wspolczynnik_temp_pmax: float,
                                    technologia: str,
                                    liczba_sekcji: int,
                                    zacienienia_godzinowe: list,
                                    panel_index: int = 0,
                                    szerokosc_geo: float = 52.23,
                                    straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
                                    degradacja_roczna: float = 0.005,
                                    rok_eksploatacji: int = 1) -> Dict:
    """
    Oblicza roczna produkcje energii pojedynczego panela.

    Parametry:
        moc_stc_w: moc nominalna w STC [W]
        wspolczynnik_temp_pmax: wspolczynnik temperaturowy [%/C]
        technologia: "half-cut" lub "standard"
        liczba_sekcji: liczba sekcji bypass
        zacienienia_godzinowe: lista wynikow zacienienia (po jednym na godzine)
        panel_index: indeks panela do analizy
        szerokosc_geo: szerokosc geograficzna (do profilu napromieniowania)
        straty_systemowe: straty systemowe
        degradacja_roczna: roczna degradacja
        rok_eksploatacji: rok eksploatacji

    Zwraca:
        Slownik z wynikami rocznymi i miesiecznymi
    """
    energia_miesieczna = [0.0] * 12
    energia_roczna = 0.0
    energia_bez_zacienienia = 0.0
    godziny_z_zacienieniem = 0

    for godzina_dane in zacienienia_godzinowe:
        miesiac = godzina_dane.miesiac
        godzina = godzina_dane.godzina
        elewacja = godzina_dane.elewacja_slonca

        # Napromieniowanie
        irradiancja = oblicz_napromieniowanie(miesiac, godzina, elewacja)
        if irradiancja <= 0:
            continue

        # Temperatura panela
        temp_panel = oblicz_temperature_panela(miesiac, godzina)

        # Znajdz dane zacienienia dla tego panela
        panel_zacienienie = None
        for pz in godzina_dane.panele:
            if pz.panel_index == panel_index:
                panel_zacienienie = pz
                break

        if panel_zacienienie is None:
            wsp_zacien = 1.0
        else:
            wsp_zacien = oblicz_wspolczynnik_zacienienia(
                panel_zacienienie, liczba_sekcji, technologia
            )
            if panel_zacienienie.stopien_zacienienia > 0:
                godziny_z_zacienieniem += 1

        # Oblicz wydajnosc z zacienieniem
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w, irradiancja, temp_panel,
            wspolczynnik_temp_pmax, wsp_zacien,
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )

        energia_miesieczna[miesiac - 1] += wynik.energia_wh
        energia_roczna += wynik.energia_wh

        # Oblicz produkcje bez zacienienia (do porownania)
        wynik_bez = oblicz_wydajnosc_panela(
            moc_stc_w, irradiancja, temp_panel,
            wspolczynnik_temp_pmax, 1.0,  # brak zacienienia
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )
        energia_bez_zacienienia += wynik_bez.energia_wh

    # Straty z powodu zacienienia
    strata_zacienienie = 0.0
    if energia_bez_zacienienia > 0:
        strata_zacienienie = 1.0 - (energia_roczna / energia_bez_zacienienia)

    return {
        "panel_index": panel_index,
        "energia_roczna_kwh": round(energia_roczna / 1000.0, 2),
        "energia_miesieczna_kwh": [round(e / 1000.0, 2) for e in energia_miesieczna],
        "energia_bez_zacienienia_kwh": round(energia_bez_zacienienia / 1000.0, 2),
        "strata_zacienienie_procent": round(strata_zacienienie * 100.0, 2),
        "godziny_z_zacienieniem": godziny_z_zacienieniem,
        "moc_stc_w": moc_stc_w,
        "technologia": technologia,
    }
