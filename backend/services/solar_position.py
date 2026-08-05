"""
Serwis obliczania pozycji Slonca (azymut i elewacja).

Wykorzystuje uproszczony algorytm oparty na formule Meeus/SPA do obliczenia
pozycji Slonca dla dowolnej daty, godziny i lokalizacji geograficznej.

Uklad wspolrzednych:
- Azymut: mierzony od polnocy zgodnie z ruchem wskazowek zegara
  (0=polnoc, 90=wschod, 180=poludnie, 270=zachod)
- Elewacja (wysokosc): kat nad horyzontem (0=horyzont, 90=zenit)

Algorytm uwzglednia:
- Deklinacje Slonca (zmiana w ciagu roku)
- Rownanie czasu (roznica miedzy czasem slonecznym a zegarowym)
- Kat godzinowy (pozycja Slonca w ciagu dnia)
- Refrakcje atmosferyczna (podnosi Slonce o ~0.57 stopnia przy horyzoncie)
- Czas letni CEST (ostatnia niedziela marca - ostatnia niedziela pazdziernika)
"""

import math
from typing import Tuple


def _ostatnia_niedziela_miesiaca(rok: int, miesiac: int) -> int:
    """
    Oblicza dzien ostatniej niedzieli w danym miesiacu.

    Polska zmienia czas:
    - Na letni (CEST, +2): ostatnia niedziela marca o 2:00
    - Na zimowy (CET, +1): ostatnia niedziela pazdziernika o 3:00

    Parametry:
        rok: rok
        miesiac: miesiac (1-12)

    Zwraca:
        Dzien miesiaca (1-31) ostatniej niedzieli
    """
    import calendar
    # Ostatni dzien miesiaca
    ostatni_dzien = calendar.monthrange(rok, miesiac)[1]
    # Dzien tygodnia ostatniego dnia (0=poniedzialek, 6=niedziela)
    dzien_tyg = calendar.weekday(rok, miesiac, ostatni_dzien)
    # Ile dni cofnac do niedzieli (niedziela = 6)
    cofniecie = (dzien_tyg - 6) % 7
    return ostatni_dzien - cofniecie


def czy_czas_letni(rok: int, miesiac: int, dzien: int, godzina: int = 12) -> bool:
    """
    Sprawdza czy w Polsce obowiazuje czas letni (CEST = UTC+2).

    Czas letni (CEST) obowiazuje od ostatniej niedzieli marca (godz. 2:00 CET)
    do ostatniej niedzieli pazdziernika (godz. 3:00 CEST, czyli 1:00 UTC).

    Parametry:
        rok: rok
        miesiac: miesiac (1-12)
        dzien: dzien miesiaca (1-31)
        godzina: godzina lokalna (0-23)

    Zwraca:
        True jesli obowiazuje CEST (czas letni, +2), False jesli CET (czas zimowy, +1)
    """
    # Miesiace jednoznaczne
    if miesiac < 3 or miesiac > 10:
        return False
    if miesiac > 3 and miesiac < 10:
        return True

    # Marzec - zmiana na letni w ostatnia niedziele
    if miesiac == 3:
        ostatnia_nd = _ostatnia_niedziela_miesiaca(rok, 3)
        if dzien < ostatnia_nd:
            return False
        if dzien > ostatnia_nd:
            return True
        # W dniu zmiany - zmiana o 2:00 CET na 3:00 CEST
        return godzina >= 2

    # Pazdziernik - zmiana na zimowy w ostatnia niedziele
    if miesiac == 10:
        ostatnia_nd = _ostatnia_niedziela_miesiaca(rok, 10)
        if dzien < ostatnia_nd:
            return True
        if dzien > ostatnia_nd:
            return False
        # W dniu zmiany - zmiana o 3:00 CEST na 2:00 CET
        return godzina < 3

    return False


def _julian_day(rok: int, miesiac: int, dzien: int,
                godzina: int = 12, minuta: int = 0) -> float:
    """
    Oblicza Dzien Julianski (JD) dla podanej daty i godziny UTC.

    Dzien Julianski to ciagla numeracja dni od 1 stycznia 4713 p.n.e.
    Uzywa sie go w astronomii do precyzyjnych obliczen.

    Parametry:
        rok: rok (np. 2026)
        miesiac: miesiac (1-12)
        dzien: dzien miesiaca (1-31)
        godzina: godzina UTC (0-23)
        minuta: minuta (0-59)

    Zwraca:
        Dzien Julianski jako liczba zmiennoprzecinkowa
    """
    # Korekta dla stycznia i lutego (traktowane jako miesiace 13 i 14
    # poprzedniego roku w algorytmie)
    if miesiac <= 2:
        rok -= 1
        miesiac += 12

    # Czesc calkowita dnia (ulamek dnia z godziny i minuty)
    ulamek_dnia = (godzina + minuta / 60.0) / 24.0

    # Algorytm Julianski
    a = int(rok / 100)
    b = 2 - a + int(a / 4)

    jd = (int(365.25 * (rok + 4716)) +
          int(30.6001 * (miesiac + 1)) +
          dzien + ulamek_dnia + b - 1524.5)

    return jd


def _oblicz_deklinacje_i_rownanie_czasu(dzien_roku: int) -> Tuple[float, float]:
    """
    Oblicza deklinacje Slonca i rownanie czasu na podstawie dnia roku.

    Deklinacja - kat miedzy kierunkiem na Slonce a plaszczyzna rownika.
    Zmienia sie od -23.45 (przesilenie zimowe) do +23.45 (przesilenie letnie).

    Rownanie czasu - roznica miedzy srednim czasem slonecznym a prawdziwym.
    Wynika z eliptycznosci orbity Ziemi i nachylenia osi obrotu.

    Parametry:
        dzien_roku: numer dnia w roku (1-365/366)

    Zwraca:
        Tuple (deklinacja_stopnie, rownanie_czasu_minuty)
    """
    # Kat B uzywany w obliczeniach (Spencer, 1971)
    b = 2.0 * math.pi * (dzien_roku - 1) / 365.0

    # Deklinacja Slonca w stopniach (przyblizenie)
    deklinacja = (0.006918 - 0.399912 * math.cos(b) +
                  0.070257 * math.sin(b) -
                  0.006758 * math.cos(2 * b) +
                  0.000907 * math.sin(2 * b) -
                  0.002697 * math.cos(3 * b) +
                  0.00148 * math.sin(3 * b))
    deklinacja_stopnie = math.degrees(deklinacja)

    # Rownanie czasu w minutach (roznica czas sredni - czas prawdziwy)
    eot = (229.18 * (0.000075 + 0.001868 * math.cos(b) -
                     0.032077 * math.sin(b) -
                     0.014615 * math.cos(2 * b) -
                     0.04089 * math.sin(2 * b)))

    return deklinacja_stopnie, eot


def _dzien_roku(rok: int, miesiac: int, dzien: int) -> int:
    """
    Oblicza numer dnia w roku (1-365/366).

    Parametry:
        rok: rok
        miesiac: miesiac (1-12)
        dzien: dzien miesiaca (1-31)

    Zwraca:
        Numer dnia w roku
    """
    # Liczba dni w kazdym miesiacu (rok nieprzestepny)
    dni_w_miesiacach = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    # Korekta dla roku przestepnego
    if (rok % 4 == 0 and rok % 100 != 0) or (rok % 400 == 0):
        dni_w_miesiacach[1] = 29

    numer = sum(dni_w_miesiacach[:miesiac - 1]) + dzien
    return numer


def get_solar_position(szerokosc_geo: float, dlugosc_geo: float,
                       rok: int, miesiac: int, dzien: int,
                       godzina: int, minuta: int = 0,
                       strefa_czasowa: float = None) -> Tuple[float, float]:
    """
    Oblicza pozycje Slonca (azymut i elewacje) dla podanej lokalizacji i czasu.

    Parametry:
        szerokosc_geo: szerokosc geograficzna w stopniach (N dodatnia)
        dlugosc_geo: dlugosc geograficzna w stopniach (E dodatnia)
        rok: rok (np. 2026)
        miesiac: miesiac (1-12)
        dzien: dzien miesiaca (1-31)
        godzina: godzina czasu lokalnego (0-23)
        minuta: minuta (0-59)
        strefa_czasowa: przesuniecie strefy czasowej wzgledem UTC w godzinach
                        (Polska: 1.0 zima CET, 2.0 lato CEST)
                        Jesli None - automatyczne wykrywanie czasu letniego/zimowego

    Zwraca:
        Tuple (azymut_stopnie, elewacja_stopnie):
        - azymut: 0=polnoc, 90=wschod, 180=poludnie, 270=zachod
        - elewacja: kat nad horyzontem (ujemna = Slonce pod horyzontem)
    """
    # Automatyczne wykrywanie strefy czasowej (CEST/CET) dla Polski
    if strefa_czasowa is None:
        if czy_czas_letni(rok, miesiac, dzien, godzina):
            strefa_czasowa = 2.0  # CEST (czas letni)
        else:
            strefa_czasowa = 1.0  # CET (czas zimowy)
    # Numer dnia w roku
    n = _dzien_roku(rok, miesiac, dzien)

    # Deklinacja i rownanie czasu
    deklinacja_deg, eot_min = _oblicz_deklinacje_i_rownanie_czasu(n)
    deklinacja_rad = math.radians(deklinacja_deg)

    # Szerokosc geograficzna w radianach
    fi_rad = math.radians(szerokosc_geo)

    # Czas sloneczny (Solar Time)
    # Korekta na dlugosc geograficzna: kazdy stopien = 4 minuty
    # Meridian standardowy dla strefy czasowej
    meridian_standardowy = strefa_czasowa * 15.0
    korekta_dlugosci = 4.0 * (dlugosc_geo - meridian_standardowy)  # minuty

    # Czas sloneczny w minutach od polnocy
    czas_lokalny_min = godzina * 60.0 + minuta
    czas_sloneczny_min = czas_lokalny_min + eot_min + korekta_dlugosci

    # Kat godzinowy (Hour Angle) - 0 w poludnie sloneczne
    # 15 stopni na godzine, ujemny przed poludniem, dodatni po
    kat_godzinowy_deg = (czas_sloneczny_min - 720.0) / 4.0
    kat_godzinowy_rad = math.radians(kat_godzinowy_deg)

    # Elewacja (wysokosc) Slonca
    sin_elewacja = (math.sin(fi_rad) * math.sin(deklinacja_rad) +
                    math.cos(fi_rad) * math.cos(deklinacja_rad) *
                    math.cos(kat_godzinowy_rad))

    # Ograniczenie do zakresu [-1, 1] (bledy numeryczne)
    sin_elewacja = max(-1.0, min(1.0, sin_elewacja))
    elewacja_rad = math.asin(sin_elewacja)
    elewacja_deg = math.degrees(elewacja_rad)

    # Azymut Slonca
    cos_elewacja = math.cos(elewacja_rad)

    if cos_elewacja == 0:
        # Slonce dokladnie w zenicie
        azymut_deg = 180.0
    else:
        cos_azymut = ((math.sin(deklinacja_rad) -
                       math.sin(fi_rad) * sin_elewacja) /
                      (math.cos(fi_rad) * cos_elewacja))

        # Ograniczenie do zakresu [-1, 1]
        cos_azymut = max(-1.0, min(1.0, cos_azymut))
        azymut_rad = math.acos(cos_azymut)
        azymut_deg = math.degrees(azymut_rad)

        # Korekta na polowe dnia - po poludniu azymut > 180
        if kat_godzinowy_deg > 0:
            azymut_deg = 360.0 - azymut_deg

    # Korekta refrakcji atmosferycznej (podnosi Slonce blisko horyzontu)
    if elewacja_deg > -0.575:
        if elewacja_deg > 5.0:
            refrakcja = 58.1 / math.tan(math.radians(elewacja_deg))
            refrakcja -= 0.07 / (math.tan(math.radians(elewacja_deg)) ** 3)
            refrakcja += 0.000086 / (math.tan(math.radians(elewacja_deg)) ** 5)
        elif elewacja_deg > -0.575:
            refrakcja = (1735.0 + elewacja_deg *
                        (-518.2 + elewacja_deg *
                         (103.4 + elewacja_deg *
                          (-12.79 + elewacja_deg * 0.711))))
        refrakcja_deg = refrakcja / 3600.0  # sekundy lukowe -> stopnie
        elewacja_deg += refrakcja_deg

    return azymut_deg, elewacja_deg


def oblicz_wektor_sloneczny(azymut_deg: float,
                            elewacja_deg: float) -> Tuple[float, float, float]:
    """
    Oblicza wektor kierunkowy promieni slonecznych na podstawie azymutu i elewacji.

    Wektor wskazuje KIERUNEK od Slonca do ziemi (kierunek padania promieni).

    Uklad wspolrzednych:
    - X: os wschod-zachod (dodatnia = wschod)
    - Y: os pionowa (dodatnia = gora)
    - Z: os polnoc-poludnie (dodatnia = poludnie)

    Parametry:
        azymut_deg: azymut Slonca w stopniach (0=polnoc, 90=wschod, 180=poludnie)
        elewacja_deg: elewacja Slonca w stopniach nad horyzontem

    Zwraca:
        Tuple (dx, dy, dz) - znormalizowany wektor kierunku promieni
        (wskazuje od Slonca ku ziemi)
    """
    azymut_rad = math.radians(azymut_deg)
    elewacja_rad = math.radians(elewacja_deg)

    # Wektor od ziemi do Slonca:
    # X = cos(elewacja) * sin(azymut) -- wschod dodatni, azymut od polnocy
    # Y = sin(elewacja) -- gora
    # Z = cos(elewacja) * cos(azymut) -- polnoc? Nie - nasz uklad ma Z=poludnie
    # Azymut 0=polnoc, 180=poludnie:
    # sin(0)=0 (polnoc, X=0), sin(180)=0 (poludnie, X=0), sin(90)=1 (wschod)
    # cos(0)=1 (polnoc), cos(180)=-1 (poludnie)
    # Nasz Z jest dodatni na poludnie, wiec Z_slonce = -cos(azymut)*cos(elewacja)

    # Kierunek DO slonca
    sx = math.sin(azymut_rad) * math.cos(elewacja_rad)
    sy = math.sin(elewacja_rad)
    sz = -math.cos(azymut_rad) * math.cos(elewacja_rad)

    # Kierunek promieni (od Slonca ku ziemi) - odwrotny
    dx = -sx
    dy = -sy
    dz = -sz

    return dx, dy, dz


def oblicz_godziny_sloneczne_rok(szerokosc_geo: float, dlugosc_geo: float,
                                  rok: int = 2025,
                                  strefa_czasowa: float = None) -> list:
    """
    Oblicza pozycje Slonca dla kazdej godziny calego roku.

    Zwraca liste 8760 (lub 8784 dla roku przestepnego) rekordow
    z pozycja Slonca dla kazdej godziny.

    Parametry:
        szerokosc_geo: szerokosc geograficzna
        dlugosc_geo: dlugosc geograficzna
        rok: rok do obliczen (domyslnie 2025)
        strefa_czasowa: strefa czasowa (None = automatycznie CEST/CET)

    Zwraca:
        Lista slownikow z kluczami:
        - miesiac, dzien, godzina: czas
        - azymut, elewacja: pozycja Slonca
        - dzien_roku: numer dnia w roku
    """
    # Czy rok przestepny
    if (rok % 4 == 0 and rok % 100 != 0) or (rok % 400 == 0):
        dni_w_miesiacach = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    else:
        dni_w_miesiacach = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    wyniki = []

    for miesiac_idx in range(12):
        miesiac = miesiac_idx + 1
        for dzien in range(1, dni_w_miesiacach[miesiac_idx] + 1):
            for godzina in range(24):
                azymut, elewacja = get_solar_position(
                    szerokosc_geo, dlugosc_geo,
                    rok, miesiac, dzien, godzina,
                    strefa_czasowa=strefa_czasowa
                )
                wyniki.append({
                    "miesiac": miesiac,
                    "dzien": dzien,
                    "godzina": godzina,
                    "azymut": azymut,
                    "elewacja": elewacja,
                    "dzien_roku": _dzien_roku(rok, miesiac, dzien),
                })

    return wyniki
