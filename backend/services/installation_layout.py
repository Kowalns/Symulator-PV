"""
Serwis obliczania rozmieszczenia paneli PV na stelazu naziemnym.

Oblicza pozycje kazdego panela w przestrzeni 3D na podstawie konfiguracji:
- Model panela (wymiary)
- Orientacja (pion/poziom)
- Kat nachylenia
- Przeswit nad gruntem
- Odstepy miedzy panelami (boczne i miedzy rzedami)
- Liczba paneli, rzedow, kolumn

Uklad wspolrzednych:
- X: os wschod-zachod (dodatnia = wschod)
- Y: os pionowa (wysokosc nad gruntem)
- Z: os polnoc-poludnie (dodatnia = poludnie, w kierunku slonca)

Panele sa ustawione frontem na poludnie (azymut 0).
"""

import json
import math
from pathlib import Path
from typing import Tuple, Optional

from backend.models.installation import (
    InstallationConfig,
    InstallationLayout,
    PanelPosition,
)

# Sciezka do bazy danych paneli
DATA_DIR = Path(__file__).parent.parent / "data"

# Limity mocy instalacji (kWp)
MIN_MOC_KWP = 2.0
MAX_MOC_KWP = 14.0


def wczytaj_baze_paneli() -> list:
    """Wczytuje baze danych paneli z pliku JSON."""
    sciezka = DATA_DIR / "panels_database.json"
    with open(sciezka, "r", encoding="utf-8") as f:
        return json.load(f)


def wczytaj_baze_falownikow() -> list:
    """Wczytuje baze danych falownikow z pliku JSON."""
    sciezka = DATA_DIR / "inverters_database.json"
    with open(sciezka, "r", encoding="utf-8") as f:
        return json.load(f)


def wczytaj_baze_baterii() -> list:
    """Wczytuje baze danych magazynow energii z pliku JSON."""
    sciezka = DATA_DIR / "batteries_database.json"
    with open(sciezka, "r", encoding="utf-8") as f:
        return json.load(f)


def znajdz_panel(panel_id: str) -> Optional[dict]:
    """Znajduje panel w bazie po identyfikatorze."""
    panele = wczytaj_baze_paneli()
    for panel in panele:
        if panel["id"] == panel_id:
            return panel
    return None


def waliduj_konfiguracje(config: InstallationConfig) -> Optional[str]:
    """
    Sprawdza poprawnosc konfiguracji instalacji.

    Zwraca komunikat bledu lub None jesli konfiguracja jest poprawna.
    """
    # Sprawdzenie orientacji
    if config.orientacja not in ("pion", "poziom"):
        return "Orientacja musi byc 'pion' lub 'poziom'"

    # Sprawdzenie kata nachylenia (15-60 stopni)
    if not (15 <= config.kat_nachylenia <= 60):
        return "Kat nachylenia musi byc miedzy 15 a 60 stopni"

    # Sprawdzenie przeswitu nad gruntem (20-100 cm)
    if not (20 <= config.przeswit_nad_gruntem_cm <= 100):
        return "Przeswit nad gruntem musi byc miedzy 20 a 100 cm"

    # Sprawdzenie odstepow
    if not (50 <= config.odstep_miedzy_rzedami_cm <= 300):
        return "Odstep miedzy rzedami musi byc miedzy 50 a 300 cm"

    if not (2 <= config.odstep_boczny_cm <= 20):
        return "Odstep boczny musi byc miedzy 2 a 20 cm"

    # Sprawdzenie liczby paneli
    if config.liczba_paneli < 1:
        return "Liczba paneli musi byc co najmniej 1"

    if config.liczba_kolumn < 1 or config.liczba_rzedow < 1:
        return "Liczba kolumn i rzedow musi byc co najmniej 1"

    if config.liczba_kolumn * config.liczba_rzedow < config.liczba_paneli:
        return (
            f"Siatka {config.liczba_kolumn}x{config.liczba_rzedow} "
            f"ma za malo miejsc ({config.liczba_kolumn * config.liczba_rzedow}) "
            f"na {config.liczba_paneli} paneli"
        )

    # Sprawdzenie czy panel istnieje w bazie
    panel = znajdz_panel(config.panel_id)
    if panel is None:
        return f"Nie znaleziono panela o ID '{config.panel_id}' w bazie"

    # Sprawdzenie mocy instalacji (2-14 kWp)
    moc_kwp = (panel["moc_wp"] * config.liczba_paneli) / 1000.0
    if moc_kwp < MIN_MOC_KWP:
        return (
            f"Moc instalacji ({moc_kwp:.2f} kWp) jest ponizej minimum "
            f"({MIN_MOC_KWP} kWp). Dodaj wiecej paneli."
        )
    if moc_kwp > MAX_MOC_KWP:
        return (
            f"Moc instalacji ({moc_kwp:.2f} kWp) przekracza maksimum "
            f"({MAX_MOC_KWP} kWp). Zmniejsz liczbe paneli."
        )

    return None


def oblicz_wymiary_panela_w_orientacji(
    panel: dict, orientacja: str
) -> Tuple[float, float]:
    """
    Oblicza wymiary panela w metrach dla danej orientacji montazu.

    Zwraca (szerokosc_m, wysokosc_m) gdzie:
    - szerokosc to wymiar poziomy (wzdluz osi X)
    - wysokosc to wymiar wzdluz nachylenia (wymiar w kierunku Z po rzucie)

    Parametry:
        panel: slownik z danymi panela (musi miec wymiary_mm)
        orientacja: "pion" (portrait) lub "poziom" (landscape)
    """
    szer_mm = panel["wymiary_mm"]["szerokosc"]
    wys_mm = panel["wymiary_mm"]["wysokosc"]

    if orientacja == "pion":
        # Portrait: krotszy bok na szerokosc, dluzszy na wysokosc
        return szer_mm / 1000.0, wys_mm / 1000.0
    else:
        # Landscape: dluzszy bok na szerokosc, krotszy na wysokosc
        return wys_mm / 1000.0, szer_mm / 1000.0


def oblicz_rozmieszczenie(config: InstallationConfig) -> InstallationLayout:
    """
    Oblicza rozmieszczenie paneli na stelazu naziemnym.

    Panele sa ukladane w siatce (rzedy x kolumny).
    Kazdy panel ma obliczona pozycje srodka w 3D.

    Geometria stelaza naziemnego:
    - Panel jest nachylony pod katem 'kat_nachylenia' wzgledem poziomu
    - Dolna krawedz panela jest na wysokosci 'przeswit_nad_gruntem_cm'
    - Rzedy paneli sa ustawione jeden za drugim (w osi Z)
    - Kolumny paneli stoja obok siebie (w osi X)

    Rzut panela na grunt (glebokosc w osi Z):
        glebokosc = wysokosc_panela * cos(kat)
    Wysokosc gornej krawedzi:
        h_gora = przeswit + wysokosc_panela * sin(kat)
    Srodek panela:
        y_srodek = przeswit + (wysokosc_panela * sin(kat)) / 2
        z_przesuniecie = (wysokosc_panela * cos(kat)) / 2
    """
    panel = znajdz_panel(config.panel_id)
    if panel is None:
        raise ValueError(f"Panel '{config.panel_id}' nie istnieje w bazie")

    # Wymiary panela w montazu
    szer_m, wys_m = oblicz_wymiary_panela_w_orientacji(panel, config.orientacja)

    # Kat w radianach
    kat_rad = math.radians(config.kat_nachylenia)

    # Przeswit w metrach
    przeswit_m = config.przeswit_nad_gruntem_cm / 100.0

    # Odstepy w metrach
    odstep_boczny_m = config.odstep_boczny_cm / 100.0
    odstep_rzedow_m = config.odstep_miedzy_rzedami_cm / 100.0

    # Rzut panela na plaszczyzne gruntu (glebokosc rzutu jednego panela)
    glebokosc_rzutu_m = wys_m * math.cos(kat_rad)

    # Wysokosc srodka panela nad gruntem
    # Dolna krawedz jest na przeswit_m, gorna krawedz na przeswit_m + wys_m * sin(kat)
    y_srodek = przeswit_m + (wys_m * math.sin(kat_rad)) / 2.0

    # Szerokosc calkowita jednego rzedu (wszystkie kolumny + odstepy)
    szerokosc_rzedu_m = (
        config.liczba_kolumn * szer_m
        + (config.liczba_kolumn - 1) * odstep_boczny_m
    )

    # Glebokosc calkowita instalacji (wszystkie rzedy + odstepy)
    glebokosc_instalacji_m = (
        config.liczba_rzedow * glebokosc_rzutu_m
        + (config.liczba_rzedow - 1) * odstep_rzedow_m
    )

    # Wysokosc gornej krawedzi najwyzszego panela
    wysokosc_max_m = przeswit_m + wys_m * math.sin(kat_rad)

    # Generowanie pozycji paneli
    panele = []
    panel_index = 0

    # Przesuniecie centrujace - srodek instalacji w (0, y, 0)
    offset_x = -szerokosc_rzedu_m / 2.0
    offset_z = -glebokosc_instalacji_m / 2.0

    for rzad in range(config.liczba_rzedow):
        for kolumna in range(config.liczba_kolumn):
            if panel_index >= config.liczba_paneli:
                break

            # Pozycja X - srodek panela w kolumnie
            x = offset_x + kolumna * (szer_m + odstep_boczny_m) + szer_m / 2.0

            # Pozycja Z - srodek rzutu panela na grunt w rzedzie
            z = offset_z + rzad * (glebokosc_rzutu_m + odstep_rzedow_m) + glebokosc_rzutu_m / 2.0

            pozycja = PanelPosition(
                index=panel_index,
                rzad=rzad,
                kolumna=kolumna,
                x=x,
                y=y_srodek,
                z=z,
                szerokosc_m=szer_m,
                wysokosc_m=wys_m,
                kat_nachylenia=config.kat_nachylenia,
            )
            panele.append(pozycja)
            panel_index += 1

        if panel_index >= config.liczba_paneli:
            break

    # Obliczenie mocy calkowitej
    moc_kwp = (panel["moc_wp"] * config.liczba_paneli) / 1000.0

    layout = InstallationLayout(
        panele=panele,
        moc_calkowita_kwp=moc_kwp,
        wymiary_instalacji_m={
            "szerokosc": round(szerokosc_rzedu_m, 3),
            "glebokosc": round(glebokosc_instalacji_m, 3),
            "wysokosc": round(wysokosc_max_m, 3),
        },
        liczba_paneli=config.liczba_paneli,
        panel_model={
            "id": panel["id"],
            "producent": panel["producent"],
            "model": panel["model"],
            "moc_wp": panel["moc_wp"],
            "wymiary_mm": panel["wymiary_mm"],
            "technologia": panel["technologia"],
        },
        config={
            "panel_id": config.panel_id,
            "orientacja": config.orientacja,
            "kat_nachylenia": config.kat_nachylenia,
            "azymut": config.azymut,
            "przeswit_nad_gruntem_cm": config.przeswit_nad_gruntem_cm,
            "odstep_miedzy_rzedami_cm": config.odstep_miedzy_rzedami_cm,
            "odstep_boczny_cm": config.odstep_boczny_cm,
            "liczba_paneli": config.liczba_paneli,
            "liczba_kolumn": config.liczba_kolumn,
            "liczba_rzedow": config.liczba_rzedow,
        },
    )

    return layout
