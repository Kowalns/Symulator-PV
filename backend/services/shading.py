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
                                     elewacja_deg: float,
                                     wysokosc_paneli: float = 0.0) -> Optional[List[Tuple[float, float]]]:
    """
    Oblicza rzut cienia budynku na plaszczyzne paneli.

    Rzutuje gorne wierzcholki budynku wzdluz kierunku promieni slonecznych
    na plaszczyzne na wysokosci dolnej krawedzi paneli (przeswit nad gruntem).
    Cien to wypukla otoczka (convex hull) rzutow + obrys budynku na tej plasczyznie.

    Parametry:
        budynek: konfiguracja budynku
        azymut_deg: azymut Slonca [stopnie]
        elewacja_deg: elewacja Slonca [stopnie]
        wysokosc_paneli: wysokosc dolnej krawedzi paneli nad gruntem [m]
                         (przeswit nad gruntem)

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

    # Tylko jesli budynek jest wyzszy niz plaszczyzna paneli
    if h <= wysokosc_paneli:
        return None

    # Wszystkie gorne wierzcholki
    gorne_wierzcholki = [
        (budynek.x - pol_szer, h, budynek.z - pol_gleb),
        (budynek.x + pol_szer, h, budynek.z - pol_gleb),
        (budynek.x - pol_szer, h, budynek.z + pol_gleb),
        (budynek.x + pol_szer, h, budynek.z + pol_gleb),
    ]

    # Rzutuj kazdy gorny wierzcholek na plaszczyzne paneli (y=wysokosc_paneli)
    rzuty = []
    for w in gorne_wierzcholki:
        rzut = _rzutuj_punkt_na_plaszczyzne(w, wektor, wysokosc_paneli)
        if rzut is not None:
            rzuty.append(rzut)

    # Dolne wierzcholki - obrys budynku na plasczyznie paneli
    # Te punkty reprezentuja czesc budynku ktora bezposrednio blokuje swiatlo
    # na wysokosci paneli (jesli budynek jest nad plaszczyzna paneli)
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


def _cross_2d(o: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Iloczyn wektorowy 2D (OA x OB) - do wyznaczania zwrotu."""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(punkty: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Oblicza wypukla otoczke (convex hull) zbioru punktow 2D.

    Algorytm Andrew's monotone chain - O(n log n).
    Zwraca wierzcholki otoczki w kolejnosci przeciwnej do wskazowek zegara.
    """
    punkty_sorted = sorted(set(punkty))
    n = len(punkty_sorted)
    if n <= 2:
        return list(punkty_sorted)

    # Dolna czesc otoczki
    lower = []
    for p in punkty_sorted:
        while len(lower) >= 2 and _cross_2d(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # Gorna czesc otoczki
    upper = []
    for p in reversed(punkty_sorted):
        while len(upper) >= 2 and _cross_2d(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Polaczenie (usuwamy ostatni punkt z kazdej czesci bo sie powtarza)
    return lower[:-1] + upper[:-1]


def _punkt_w_wielokacie(punkt: Tuple[float, float],
                         wielokat: List[Tuple[float, float]]) -> bool:
    """
    Sprawdza czy punkt lezy wewnatrz wielokata wypuklego (convex polygon).

    Metoda: ray casting (parzystosc przeciec z polprosta).
    Dziala dla dowolnych wielokatow (nie tylko wypuklych).
    """
    x, y = punkt
    n = len(wielokat)
    wewnatrz = False

    j = n - 1
    for i in range(n):
        xi, yi = wielokat[i]
        xj, yj = wielokat[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            wewnatrz = not wewnatrz
        j = i

    return wewnatrz


def _clip_polygon_edge(polygon: List[Tuple[float, float]],
                        edge_start: Tuple[float, float],
                        edge_end: Tuple[float, float]) -> List[Tuple[float, float]]:
    """
    Przycina wielokat wzgledem jednej krawedzi (Sutherland-Hodgman).

    Zachowuje czesc wielokata lezaca po lewej stronie krawedzi
    (patrząc od edge_start do edge_end).
    """
    if not polygon:
        return []

    result = []
    ex, ey = edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]

    def is_inside(p):
        """Czy punkt jest po lewej stronie krawedzi."""
        return ex * (p[1] - edge_start[1]) - ey * (p[0] - edge_start[0]) >= 0

    def intersection(p1, p2):
        """Punkt przeciecia odcinka p1-p2 z krawedzia."""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = edge_start
        x4, y4 = edge_end

        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p1  # Rownolegle - zwroc punkt poczatkowy

        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    prev = polygon[-1]
    prev_inside = is_inside(prev)

    for curr in polygon:
        curr_inside = is_inside(curr)

        if curr_inside:
            if not prev_inside:
                result.append(intersection(prev, curr))
            result.append(curr)
        elif prev_inside:
            result.append(intersection(prev, curr))

        prev = curr
        prev_inside = curr_inside

    return result


def _polygon_intersection_area(poly_a: List[Tuple[float, float]],
                                poly_b: List[Tuple[float, float]]) -> float:
    """
    Oblicza pole przeciecia dwoch wielokatow wypuklych.

    Uzywa algorytmu Sutherland-Hodgman do przycinania poly_a
    wzgledem krawedzi poly_b, a nastepnie oblicza pole wyniku
    formula Shoelace.

    Parametry:
        poly_a: wielokat A (lista wierzcholkow)
        poly_b: wielokat B (lista wierzcholkow - musi byc wypukly)

    Zwraca:
        Pole powierzchni przeciecia
    """
    if not poly_a or not poly_b:
        return 0.0

    # Przycinanie poly_a krawedzami poly_b (Sutherland-Hodgman)
    clipped = list(poly_a)
    n_b = len(poly_b)

    for i in range(n_b):
        if not clipped:
            return 0.0
        edge_start = poly_b[i]
        edge_end = poly_b[(i + 1) % n_b]
        clipped = _clip_polygon_edge(clipped, edge_start, edge_end)

    if len(clipped) < 3:
        return 0.0

    # Pole wielokata (Shoelace formula)
    area = 0.0
    n = len(clipped)
    for i in range(n):
        j = (i + 1) % n
        area += clipped[i][0] * clipped[j][1]
        area -= clipped[j][0] * clipped[i][1]

    return abs(area) / 2.0


def _oblicz_zacienienie_panela(panel: PanelPosition,
                               cien_polygon: List[Tuple[float, float]],
                               kat_nachylenia: float,
                               liczba_sekcji: int = 3,
                               technologia: str = "standard") -> WynikZacienieniaPanel:
    """
    Oblicza zacienienie pojedynczego panela przez cien budynku.

    Panel jest nachylony - rzutujemy jego pozycje na grunt i sprawdzamy
    nakladanie sie z wielokatem cienia (convex hull).

    Sekcje bypass diod sa ulozone wzdluz dlugosci panela (gora-dol w pionie).
    Dla panela w orientacji pionowej:
    - Sekcja 0 (dolna): najblizej gruntu
    - Sekcja 1 (srodkowa): srodek panela
    - Sekcja 2 (gorna): najdalej od gruntu (najwyzej)

    Cien budynku z polnocy pada przede wszystkim na dolne czesci panela
    (bo Slonce jest na poludniu i cien pada na polnoc).

    Parametry:
        panel: pozycja panela w przestrzeni
        cien_polygon: wielokat cienia (convex hull) jako lista (x, z)
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

    # Prostokat panela jako wielokat (do polygon intersection)
    panel_poly = [
        (panel_x_min, panel_z_min),
        (panel_x_max, panel_z_min),
        (panel_x_max, panel_z_max),
        (panel_x_min, panel_z_max),
    ]

    # Oblicz pole przeciecia wielokata cienia z prostokatem panela
    powierzchnia_panela = (panel_x_max - panel_x_min) * (panel_z_max - panel_z_min)

    if powierzchnia_panela <= 0:
        return WynikZacienieniaPanel(panel_index=panel.index)

    # Pole przeciecia wielokata cienia z panelem
    overlap_area = _polygon_intersection_area(panel_poly, cien_polygon)

    if overlap_area <= 0:
        # Brak zacienienia
        return WynikZacienieniaPanel(
            panel_index=panel.index,
            stopien_zacienienia=0.0,
            sekcje_zacienione=[False] * liczba_sekcji,
            bypass_aktywne=0,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=False,
        )

    stopien_zacienienia = min(1.0, overlap_area / powierzchnia_panela)

    # Oblicz zacienienie kazdej sekcji bypass
    # Sekcje sa ulozone wzdluz osi Z (od polnocy/dol do poludnia/gora)
    panel_szer = panel_x_max - panel_x_min
    panel_gleb = panel_z_max - panel_z_min
    sekcja_glebokosc = panel_gleb / liczba_sekcji
    sekcje_zacienione = []

    for i in range(liczba_sekcji):
        # Zakres Z dla sekcji i (sekcja 0 = najblizej polnocy = dol panela)
        sekcja_z_min = panel_z_min + i * sekcja_glebokosc
        sekcja_z_max = panel_z_min + (i + 1) * sekcja_glebokosc

        # Prostokat sekcji
        sekcja_poly = [
            (panel_x_min, sekcja_z_min),
            (panel_x_max, sekcja_z_min),
            (panel_x_max, sekcja_z_max),
            (panel_x_min, sekcja_z_max),
        ]

        sekcja_pow = panel_szer * sekcja_glebokosc
        sekcja_overlap = _polygon_intersection_area(sekcja_poly, cien_polygon)
        sekcja_stopien = sekcja_overlap / sekcja_pow if sekcja_pow > 0 else 0

        # Bypass aktywuje sie gdy sekcja zacieniona >15%
        # (w rzeczywistosci bypass aktywuje sie przy 10-20% zacienienia sekcji,
        # wystarczy ze kilka cel jest zacienionych aby prad spadl ponizej progu)
        sekcje_zacienione.append(sekcja_stopien > 0.15)

    bypass_aktywne = sum(1 for s in sekcje_zacienione if s)

    # Analiza half-cut: panel ma 2 niezalezne polowy (gorna i dolna)
    # Sprawdz zacienienie polowek (na podstawie zakresu Z)
    polowa_z_srodek = (panel_z_min + panel_z_max) / 2.0

    # Dolna polowa zacieniona: cien pokrywa >50% dolnej polowy
    dolna_poly = [
        (panel_x_min, panel_z_min),
        (panel_x_max, panel_z_min),
        (panel_x_max, polowa_z_srodek),
        (panel_x_min, polowa_z_srodek),
    ]
    dolna_pol_pow = panel_szer * (polowa_z_srodek - panel_z_min)
    dolna_overlap = _polygon_intersection_area(dolna_poly, cien_polygon)
    polowa_dolna_zacieniona = (dolna_overlap / dolna_pol_pow > 0.5) if dolna_pol_pow > 0 else False

    # Gorna polowa zacieniona
    gorna_poly = [
        (panel_x_min, polowa_z_srodek),
        (panel_x_max, polowa_z_srodek),
        (panel_x_max, panel_z_max),
        (panel_x_min, panel_z_max),
    ]
    gorna_pol_pow = panel_szer * (panel_z_max - polowa_z_srodek)
    gorna_overlap = _polygon_intersection_area(gorna_poly, cien_polygon)
    polowa_gorna_zacieniona = (gorna_overlap / gorna_pol_pow > 0.5) if gorna_pol_pow > 0 else False

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
                                  strefa_czasowa: Optional[float] = None,
                                  przeswit_nad_gruntem_m: float = 0.5) -> List[WynikZacienieniaGodzina]:
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
        strefa_czasowa: strefa czasowa (None = automatyczne wykrywanie CET/CEST)
        przeswit_nad_gruntem_m: wysokosc dolnej krawedzi paneli nad gruntem [m]

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
                    budynek, azymut, elewacja, przeswit_nad_gruntem_m
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

                # Convex hull cienia (dokladny wielokat zamiast AABB)
                cien_hull = _convex_hull(punkty_cienia)

                if len(cien_hull) < 3:
                    # Za malo punktow na wielokat - brak zacienienia
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

                # Oblicz zacienienie kazdego panela
                for panel in panele:
                    wynik_panel = _oblicz_zacienienie_panela(
                        panel, cien_hull, kat_nachylenia,
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
                                           technologia: str = "standard",
                                           przeswit_nad_gruntem_m: float = 0.5) -> List[WynikZacienieniaPanel]:
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
        przeswit_nad_gruntem_m: wysokosc dolnej krawedzi paneli nad gruntem [m]

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
        budynek, azymut_slonca, elewacja_slonca, przeswit_nad_gruntem_m
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

    cien_hull = _convex_hull(punkty_cienia)

    if len(cien_hull) < 3:
        return [
            WynikZacienieniaPanel(
                panel_index=p.index,
                stopien_zacienienia=0.0,
                sekcje_zacienione=[False] * liczba_sekcji,
                bypass_aktywne=0,
            )
            for p in panele
        ]

    wyniki = []
    for panel in panele:
        wynik = _oblicz_zacienienie_panela(
            panel, cien_hull, kat_nachylenia,
            liczba_sekcji, technologia
        )
        wyniki.append(wynik)

    return wyniki
