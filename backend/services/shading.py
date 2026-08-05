"""
Serwis obliczania zacienienia paneli PV przez budynek.

Algorytm rzutowania cienia:
1. Budynek jest uproszczony do prostopadloscianu (bounding box z Dom.STL).
2. Dla kazdej godziny roku oblicza sie kierunek promieni slonecznych.
3. Cien budynku jest rzutowany na plaszczyzne paneli.
4. Dla kazdego panela obliczany jest stopien zacienienia (0.0 - 1.0).
5. Na podstawie zacienienia okreslane sa aktywacje bypass diod i wplyw
   technologii half-cut.

Uklad wspolrzednych (zgodny z installation_layout.py):
- X: os wschod-zachod (dodatnia = wschod)
- Y: os pionowa (wysokosc nad gruntem)
- Z: os polnoc-poludnie (dodatnia = poludnie)

Budynek jest umieszczony na polnoc od instalacji (ujemne Z).
"""

import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from backend.services.solar_position import get_solar_position, oblicz_wektor_sloneczny
from backend.models.installation import PanelPosition, InstallationConfig


# Przyblizony bounding box budynku Dom.STL (wymiary w metrach)
# Budynek ustawiony na polnoc od instalacji PV
BUDYNEK_SZEROKOSC_M = 10.0   # wymiar w osi X
BUDYNEK_GLEBOKOSC_M = 8.0    # wymiar w osi Z (polnoc-poludnie)
BUDYNEK_WYSOKOSC_M = 8.0     # wymiar w osi Y (wysokosc z dachem)


@dataclass
class BudynekConfig:
    """
    Konfiguracja pozycji budynku wzgledem instalacji PV.

    Atrybuty:
        x: pozycja srodka budynku w osi X [m]
        z: pozycja srodka budynku w osi Z [m] (ujemna = na polnoc od instalacji)
        szerokosc: szerokosc budynku [m] (os X)
        glebokosc: glebokosc budynku [m] (os Z)
        wysokosc: wysokosc budynku [m] (os Y)
    """
    x: float = 0.0
    z: float = -10.0  # Budynek 10m na polnoc od srodka instalacji
    szerokosc: float = BUDYNEK_SZEROKOSC_M
    glebokosc: float = BUDYNEK_GLEBOKOSC_M
    wysokosc: float = BUDYNEK_WYSOKOSC_M


@dataclass
class WynikZacienieniaPanel:
    """
    Wynik analizy zacienienia pojedynczego panela w danej godzinie.

    Atrybuty:
        panel_index: numer panela
        stopien_zacienienia: ulamek powierzchni panela w cieniu (0.0 - 1.0)
        sekcje_zacienione: lista flag dla kazdej sekcji bypass (True=zacieniona >50%)
        bypass_aktywne: ile sekcji ma aktywna bypass diode
        polowa_gorna_zacieniona: czy gorna polowa panela jest zacieniona (half-cut)
        polowa_dolna_zacieniona: czy dolna polowa panela jest zacieniona (half-cut)
    """
    panel_index: int = 0
    stopien_zacienienia: float = 0.0
    sekcje_zacienione: List[bool] = field(default_factory=list)
    bypass_aktywne: int = 0
    polowa_gorna_zacieniona: bool = False
    polowa_dolna_zacieniona: bool = False


@dataclass
class WynikZacienieniaGodzina:
    """
    Wynik zacienienia dla wszystkich paneli w jednej godzinie.

    Atrybuty:
        miesiac: numer miesiaca (1-12)
        dzien: dzien miesiaca
        godzina: godzina (0-23)
        azymut_slonca: azymut Slonca [stopnie]
        elewacja_slonca: elewacja Slonca [stopnie]
        panele: lista wynikow zacienienia dla kazdego panela
    """
    miesiac: int = 1
    dzien: int = 1
    godzina: int = 0
    azymut_slonca: float = 0.0
    elewacja_slonca: float = 0.0
    panele: List[WynikZacienieniaPanel] = field(default_factory=list)


def _oblicz_wierzcholki_budynku(budynek: BudynekConfig) -> List[Tuple[float, float, float]]:
    """
    Oblicza 8 wierzcholkow prostopadloscianu budynku.

    Zwraca liste krotek (x, y, z) wierzcholkow.
    """
    pol_szer = budynek.szerokosc / 2.0
    pol_gleb = budynek.glebokosc / 2.0
    h = budynek.wysokosc

    wierzcholki = []
    for dx in [-pol_szer, pol_szer]:
        for dz in [-pol_gleb, pol_gleb]:
            for dy in [0.0, h]:
                wierzcholki.append((
                    budynek.x + dx,
                    dy,
                    budynek.z + dz
                ))
    return wierzcholki


def _rzutuj_punkt_na_plaszczyzne(punkt: Tuple[float, float, float],
                                  wektor_slonca: Tuple[float, float, float],
                                  y_plaszczyzny: float = 0.0) -> Optional[Tuple[float, float]]:
    """
    Rzutuje punkt na plaszczyzne pozioma (y=y_plaszczyzny) wzdluz kierunku promieni.

    Parametry:
        punkt: (x, y, z) punkt do rzutowania (wierzcholek budynku)
        wektor_slonca: (dx, dy, dz) znormalizowany wektor kierunku promieni
        y_plaszczyzny: wysokosc plaszczyzny na ktora rzutujemy

    Zwraca:
        (x_rzut, z_rzut) - wspolrzedne rzutu lub None jesli rzut niemozliwy
    """
    px, py, pz = punkt
    dx, dy, dz = wektor_slonca

    # Jesli promienie ida w gore lub sa poziome, nie ma cienia na dole
    if dy >= 0:
        return None

    # Parametr t - odleglosc wzdluz promienia do plaszczyzny
    # py + t * dy = y_plaszczyzny
    t = (y_plaszczyzny - py) / dy

    if t < 0:
        # Punkt jest ponizej plaszczyzny - brak rzutowania
        return None

    # Wspolrzedne rzutu
    x_rzut = px + t * dx
    z_rzut = pz + t * dz

    return (x_rzut, z_rzut)


def _oblicz_cien_budynku_na_gruncie(budynek: BudynekConfig,
                                     azymut_deg: float,
                                     elewacja_deg: float) -> Optional[List[Tuple[float, float]]]:
    """
    Oblicza rzut cienia budynku na plaszczyzne gruntu (y=0).

    Rzutuje gorne wierzcholki budynku wzdluz kierunku promieni slonecznych.
    Cien to wypukla otoczka (convex hull) rzutow + obrys budynku na gruncie.

    Parametry:
        budynek: konfiguracja budynku
        azymut_deg: azymut Slonca [stopnie]
        elewacja_deg: elewacja Slonca [stopnie]

    Zwraca:
        Lista punktow (x, z) tworzacych prostokat cienia (min/max),
        lub None jesli Slonce jest pod horyzontem.
    """
    if elewacja_deg <= 0:
        return None

    # Wektor kierunku promieni slonecznych
    wektor = oblicz_wektor_sloneczny(azymut_deg, elewacja_deg)

    # Gorne wierzcholki budynku (y = budynek.wysokosc)
    pol_szer = budynek.szerokosc / 2.0
    pol_gleb = budynek.glebokosc / 2.0
    h = budynek.wysokosc

    # Wszystkie gorne wierzcholki
    gorne_wierzcholki = [
        (budynek.x - pol_szer, h, budynek.z - pol_gleb),
        (budynek.x + pol_szer, h, budynek.z - pol_gleb),
        (budynek.x - pol_szer, h, budynek.z + pol_gleb),
        (budynek.x + pol_szer, h, budynek.z + pol_gleb),
    ]

    # Rzutuj kazdy gorny wierzcholek na grunt
    rzuty = []
    for w in gorne_wierzcholki:
        rzut = _rzutuj_punkt_na_plaszczyzne(w, wektor, 0.0)
        if rzut is not None:
            rzuty.append(rzut)

    # Dolne wierzcholki (obrys budynku na gruncie)
    dolne = [
        (budynek.x - pol_szer, budynek.z - pol_gleb),
        (budynek.x + pol_szer, budynek.z - pol_gleb),
        (budynek.x - pol_szer, budynek.z + pol_gleb),
        (budynek.x + pol_szer, budynek.z + pol_gleb),
    ]

    # Wszystkie punkty cienia (rzuty gornych + dolne)
    wszystkie = rzuty + dolne

    if len(wszystkie) < 2:
        return None

    return wszystkie


def _bounding_box_cienia(punkty: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """
    Oblicza prostokat ograniczajacy (bounding box) zbioru punktow 2D.

    Zwraca (x_min, x_max, z_min, z_max).
    """
    x_coords = [p[0] for p in punkty]
    z_coords = [p[1] for p in punkty]

    return (min(x_coords), max(x_coords), min(z_coords), max(z_coords))


def _oblicz_zacienienie_panela(panel: PanelPosition,
                               cien_bbox: Tuple[float, float, float, float],
                               kat_nachylenia: float,
                               liczba_sekcji: int = 3,
                               technologia: str = "standard") -> WynikZacienieniaPanel:
    """
    Oblicza zacienienie pojedynczego panela przez cien budynku.

    Panel jest nachylony - rzutujemy jego pozycje na grunt i sprawdzamy
    nakladanie sie z cieniem.

    Sekcje bypass diod sa ulozone wzdluz dlugosci panela (gora-dol w pionie).
    Dla panela w orientacji pionowej:
    - Sekcja 0 (dolna): najblizej gruntu
    - Sekcja 1 (srodkowa): srodek panela
    - Sekcja 2 (gorna): najdalej od gruntu (najwyzej)

    Cien budynku z polnocy pada przede wszystkim na dolne czesci panela
    (bo Slonce jest na poludniu i cien pada na polnoc).

    Parametry:
        panel: pozycja panela w przestrzeni
        cien_bbox: prostokat cienia na gruncie (x_min, x_max, z_min, z_max)
        kat_nachylenia: kat nachylenia panela [stopnie]
        liczba_sekcji: liczba sekcji bypass diod (typowo 3)
        technologia: "half-cut" lub "standard"

    Zwraca:
        WynikZacienieniaPanel z informacja o zacienieniu
    """
    kat_rad = math.radians(kat_nachylenia)

    # Pozycja panela - jego rzut na grunt (os Z)
    # Panel jest nachylony, wiec zajmuje zakres Z od dolnej do gornej krawedzi
    pol_wysokosc_rzut = (panel.wysokosc_m * math.cos(kat_rad)) / 2.0
    pol_szerokosc = panel.szerokosc_m / 2.0

    panel_x_min = panel.x - pol_szerokosc
    panel_x_max = panel.x + pol_szerokosc
    panel_z_min = panel.z - pol_wysokosc_rzut  # dolna krawedz (blizej polnocy)
    panel_z_max = panel.z + pol_wysokosc_rzut  # gorna krawedz (blizej poludnia)

    cien_x_min, cien_x_max, cien_z_min, cien_z_max = cien_bbox

    # Przeciecie prostokatow (panel vs cien) w osi X
    overlap_x_min = max(panel_x_min, cien_x_min)
    overlap_x_max = min(panel_x_max, cien_x_max)

    # Przeciecie w osi Z
    overlap_z_min = max(panel_z_min, cien_z_min)
    overlap_z_max = min(panel_z_max, cien_z_max)

    # Sprawdz czy jest jakiekolwiek nakladanie
    if overlap_x_min >= overlap_x_max or overlap_z_min >= overlap_z_max:
        # Brak zacienienia
        return WynikZacienieniaPanel(
            panel_index=panel.index,
            stopien_zacienienia=0.0,
            sekcje_zacienione=[False] * liczba_sekcji,
            bypass_aktywne=0,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=False,
        )

    # Oblicz stopien zacienienia calego panela
    panel_szer = panel_x_max - panel_x_min
    panel_gleb = panel_z_max - panel_z_min

    overlap_szer = overlap_x_max - overlap_x_min
    overlap_gleb = overlap_z_max - overlap_z_min

    powierzchnia_panela = panel_szer * panel_gleb
    powierzchnia_cienia = overlap_szer * overlap_gleb

    if powierzchnia_panela <= 0:
        return WynikZacienieniaPanel(panel_index=panel.index)

    stopien_zacienienia = min(1.0, powierzchnia_cienia / powierzchnia_panela)

    # Oblicz zacienienie kazdej sekcji bypass
    # Sekcje sa ulozone wzdluz osi Z (od polnocy/dol do poludnia/gora)
    sekcja_glebokosc = panel_gleb / liczba_sekcji
    sekcje_zacienione = []

    for i in range(liczba_sekcji):
        # Zakres Z dla sekcji i (sekcja 0 = najblizej polnocy = dol panela)
        sekcja_z_min = panel_z_min + i * sekcja_glebokosc
        sekcja_z_max = panel_z_min + (i + 1) * sekcja_glebokosc

        # Przeciecie sekcji z cieniem w osi Z
        s_overlap_z_min = max(sekcja_z_min, overlap_z_min)
        s_overlap_z_max = min(sekcja_z_max, overlap_z_max)

        if s_overlap_z_min >= s_overlap_z_max:
            sekcje_zacienione.append(False)
        else:
            # Stopien zacienienia sekcji (uwzgledniamy tez overlap w X)
            sekcja_pow = panel_szer * sekcja_glebokosc
            sekcja_cien_pow = overlap_szer * (s_overlap_z_max - s_overlap_z_min)
            sekcja_stopien = sekcja_cien_pow / sekcja_pow if sekcja_pow > 0 else 0

            # Bypass aktywuje sie gdy sekcja zacieniona >50%
            sekcje_zacienione.append(sekcja_stopien > 0.5)

    bypass_aktywne = sum(1 for s in sekcje_zacienione if s)

    # Analiza half-cut: panel ma 2 niezalezne polowy (gorna i dolna)
    # Dolna polowa = sekcje blizej polnocy (indeksy nizsze)
    # Gorna polowa = sekcje dalej od polnocy (indeksy wyzsze)
    polowa_punkt = liczba_sekcji / 2.0

    # Sprawdz zacienienie polowek (na podstawie zakresu Z)
    polowa_z_srodek = (panel_z_min + panel_z_max) / 2.0

    # Dolna polowa zacieniona: cien pokrywa >50% dolnej polowy
    dolna_pol_z_min = panel_z_min
    dolna_pol_z_max = polowa_z_srodek
    dolna_overlap_z = max(0, min(overlap_z_max, dolna_pol_z_max) - max(overlap_z_min, dolna_pol_z_min))
    dolna_pol_pow = panel_szer * (dolna_pol_z_max - dolna_pol_z_min)
    dolna_cien_pow = overlap_szer * dolna_overlap_z
    polowa_dolna_zacieniona = (dolna_cien_pow / dolna_pol_pow > 0.5) if dolna_pol_pow > 0 else False

    # Gorna polowa zacieniona
    gorna_pol_z_min = polowa_z_srodek
    gorna_pol_z_max = panel_z_max
    gorna_overlap_z = max(0, min(overlap_z_max, gorna_pol_z_max) - max(overlap_z_min, gorna_pol_z_min))
    gorna_pol_pow = panel_szer * (gorna_pol_z_max - gorna_pol_z_min)
    gorna_cien_pow = overlap_szer * gorna_overlap_z
    polowa_gorna_zacieniona = (gorna_cien_pow / gorna_pol_pow > 0.5) if gorna_pol_pow > 0 else False

    return WynikZacienieniaPanel(
        panel_index=panel.index,
        stopien_zacienienia=stopien_zacienienia,
        sekcje_zacienione=sekcje_zacienione,
        bypass_aktywne=bypass_aktywne,
        polowa_gorna_zacieniona=polowa_gorna_zacieniona,
        polowa_dolna_zacieniona=polowa_dolna_zacieniona,
    )


def oblicz_zacienienie_godzinowe(panele: List[PanelPosition],
                                  budynek: BudynekConfig,
                                  szerokosc_geo: float,
                                  dlugosc_geo: float,
                                  rok: int = 2025,
                                  kat_nachylenia: float = 30.0,
                                  liczba_sekcji: int = 3,
                                  technologia: str = "standard",
                                  strefa_czasowa: float = 1.0) -> List[WynikZacienieniaGodzina]:
    """
    Oblicza zacienienie paneli dla kazdej godziny roku.

    Parametry:
        panele: lista pozycji paneli
        budynek: konfiguracja budynku
        szerokosc_geo: szerokosc geograficzna
        dlugosc_geo: dlugosc geograficzna
        rok: rok symulacji
        kat_nachylenia: kat nachylenia paneli [stopnie]
        liczba_sekcji: liczba sekcji bypass diod
        technologia: "half-cut" lub "standard"
        strefa_czasowa: strefa czasowa

    Zwraca:
        Lista WynikZacienieniaGodzina dla kazdej godziny roku
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
                # Oblicz pozycje Slonca
                azymut, elewacja = get_solar_position(
                    szerokosc_geo, dlugosc_geo,
                    rok, miesiac, dzien, godzina,
                    strefa_czasowa=strefa_czasowa
                )

                wynik_godzina = WynikZacienieniaGodzina(
                    miesiac=miesiac,
                    dzien=dzien,
                    godzina=godzina,
                    azymut_slonca=azymut,
                    elewacja_slonca=elewacja,
                    panele=[],
                )

                # Jesli Slonce jest pod horyzontem - brak zacienienia (i produkcji)
                if elewacja <= 0:
                    for panel in panele:
                        wynik_godzina.panele.append(WynikZacienieniaPanel(
                            panel_index=panel.index,
                            stopien_zacienienia=0.0,
                            sekcje_zacienione=[False] * liczba_sekcji,
                            bypass_aktywne=0,
                            polowa_gorna_zacieniona=False,
                            polowa_dolna_zacieniona=False,
                        ))
                    wyniki.append(wynik_godzina)
                    continue

                # Oblicz cien budynku
                punkty_cienia = _oblicz_cien_budynku_na_gruncie(
                    budynek, azymut, elewacja
                )

                if punkty_cienia is None or len(punkty_cienia) < 2:
                    # Brak cienia
                    for panel in panele:
                        wynik_godzina.panele.append(WynikZacienieniaPanel(
                            panel_index=panel.index,
                            stopien_zacienienia=0.0,
                            sekcje_zacienione=[False] * liczba_sekcji,
                            bypass_aktywne=0,
                            polowa_gorna_zacieniona=False,
                            polowa_dolna_zacieniona=False,
                        ))
                    wyniki.append(wynik_godzina)
                    continue

                # Bounding box cienia
                cien_bbox = _bounding_box_cienia(punkty_cienia)

                # Oblicz zacienienie kazdego panela
                for panel in panele:
                    wynik_panel = _oblicz_zacienienie_panela(
                        panel, cien_bbox, kat_nachylenia,
                        liczba_sekcji, technologia
                    )
                    wynik_godzina.panele.append(wynik_panel)

                wyniki.append(wynik_godzina)

    return wyniki


def oblicz_zacienienie_pojedyncza_godzina(panele: List[PanelPosition],
                                           budynek: BudynekConfig,
                                           azymut_slonca: float,
                                           elewacja_slonca: float,
                                           kat_nachylenia: float = 30.0,
                                           liczba_sekcji: int = 3,
                                           technologia: str = "standard") -> List[WynikZacienieniaPanel]:
    """
    Oblicza zacienienie paneli dla jednej konkretnej pozycji Slonca.

    Uproszczona wersja do testowania i szybkich obliczen.

    Parametry:
        panele: lista pozycji paneli
        budynek: konfiguracja budynku
        azymut_slonca: azymut Slonca [stopnie]
        elewacja_slonca: elewacja Slonca [stopnie]
        kat_nachylenia: kat nachylenia paneli [stopnie]
        liczba_sekcji: liczba sekcji bypass
        technologia: "half-cut" lub "standard"

    Zwraca:
        Lista WynikZacienieniaPanel dla kazdego panela
    """
    if elewacja_slonca <= 0:
        return [
            WynikZacienieniaPanel(
                panel_index=p.index,
                stopien_zacienienia=0.0,
                sekcje_zacienione=[False] * liczba_sekcji,
                bypass_aktywne=0,
            )
            for p in panele
        ]

    # Oblicz cien budynku
    punkty_cienia = _oblicz_cien_budynku_na_gruncie(
        budynek, azymut_slonca, elewacja_slonca
    )

    if punkty_cienia is None or len(punkty_cienia) < 2:
        return [
            WynikZacienieniaPanel(
                panel_index=p.index,
                stopien_zacienienia=0.0,
                sekcje_zacienione=[False] * liczba_sekcji,
                bypass_aktywne=0,
            )
            for p in panele
        ]

    cien_bbox = _bounding_box_cienia(punkty_cienia)

    wyniki = []
    for panel in panele:
        wynik = _oblicz_zacienienie_panela(
            panel, cien_bbox, kat_nachylenia,
            liczba_sekcji, technologia
        )
        wyniki.append(wynik)

    return wyniki
