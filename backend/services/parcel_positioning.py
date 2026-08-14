"""
Serwis pozycjonowania obiektow na dzialce.

Oblicza pozycje srodka budynku/paneli na podstawie odleglosci
od granicy poludniowej i wschodniej dzialki.

Uklad wspolrzednych: +X = wschod, +Z = poludnie (konwencja Three.js).

Algorytm:
1. Identyfikuj granice poludniowa (najdluzszy bok E-W) i wschodnia (najdluzszy bok N-S z max X)
2. Oblicz normalne wewnetrzne (w kierunku centroidu)
3. Przesun proste rownolegle do granic o zadane odleglosci
4. Znajdz punkt przeciecia = pozycja najblizszej sciany/krawedzi
5. Dodaj pol wymiarow wzdluz normalnych = srodek obiektu
"""

import math
from typing import List, Tuple, Optional, Dict, Any


def _dlugosc_odcinka(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Oblicza dlugosc odcinka miedzy dwoma punktami."""
    dx = p2[0] - p1[0]
    dz = p2[1] - p1[1]
    return math.sqrt(dx * dx + dz * dz)


def _kierunek_boku(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Oblicza azymut boku (kat od polnocy, zgodnie z ruchem wskazowek zegara).
    W ukladzie +X=wschod, +Z=poludnie:
    - Polnoc = -Z, Wschod = +X, Poludnie = +Z, Zachod = -X
    Azymut 0 = polnoc (kierunek -Z), 90 = wschod (+X), 180 = poludnie (+Z), 270 = zachod (-X)
    """
    dx = p2[0] - p1[0]
    dz = p2[1] - p1[1]
    # atan2(dx, -dz) daje kat od polnocy (os -Z) w prawo
    azymut = math.degrees(math.atan2(dx, -dz))
    if azymut < 0:
        azymut += 360.0
    return azymut


def _centroid(wierzcholki: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Oblicza centroid (srodek ciezkosci) wielokata."""
    n = len(wierzcholki)
    cx = sum(w[0] for w in wierzcholki) / n
    cz = sum(w[1] for w in wierzcholki) / n
    return (cx, cz)


def _normalna_zewnetrzna(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    """
    Oblicza znormalizowana normalna zewnetrzna do boku p1->p2.
    Normalna jest prostopadla do boku, po prawej stronie kierunku p1->p2.
    """
    dx = p2[0] - p1[0]
    dz = p2[1] - p1[1]
    dlugosc = math.sqrt(dx * dx + dz * dz)
    if dlugosc < 1e-10:
        return (0.0, 0.0)
    # Normalna po prawej stronie: (dz, -dx) / dlugosc
    # Ale w ukladzie +Z=poludnie, normalna po prawej to (dz, -dx)
    nx = dz / dlugosc
    nz = -dx / dlugosc
    return (nx, nz)


def _normalna_wewnetrzna(
    p1: Tuple[float, float], p2: Tuple[float, float],
    centroid_punkt: Tuple[float, float]
) -> Tuple[float, float]:
    """
    Oblicza znormalizowana normalna wewnetrzna (skierowana w strone centroidu).
    """
    nx, nz = _normalna_zewnetrzna(p1, p2)
    # Srodek boku
    sx = (p1[0] + p2[0]) / 2.0
    sz = (p1[1] + p2[1]) / 2.0
    # Wektor od srodka boku do centroidu
    do_centroidu_x = centroid_punkt[0] - sx
    do_centroidu_z = centroid_punkt[1] - sz
    # Iloczyn skalarny - jesli ujemny, odwracamy normalna
    dot = nx * do_centroidu_x + nz * do_centroidu_z
    if dot < 0:
        nx = -nx
        nz = -nz
    return (nx, nz)


def _odchylenie_od_ew(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Oblicza odchylenie boku od kierunku wschod-zachod (w stopniach).
    Kierunek E-W ma azymut 90 lub 270.
    Zwraca minimalne odchylenie od 90 lub 270 stopni.
    """
    azymut = _kierunek_boku(p1, p2)
    # Odchylenie od E (90) lub W (270)
    odch_e = min(abs(azymut - 90.0), abs(azymut - 90.0 - 360.0), abs(azymut - 90.0 + 360.0))
    odch_w = min(abs(azymut - 270.0), abs(azymut - 270.0 - 360.0), abs(azymut - 270.0 + 360.0))
    return min(odch_e, odch_w)


def _odchylenie_od_ns(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """
    Oblicza odchylenie boku od kierunku polnoc-poludnie (w stopniach).
    Kierunek N-S ma azymut 0/360 lub 180.
    Zwraca minimalne odchylenie od 0 lub 180 stopni.
    """
    azymut = _kierunek_boku(p1, p2)
    # Odchylenie od N (0/360) lub S (180)
    odch_n = min(abs(azymut), abs(azymut - 360.0))
    odch_s = abs(azymut - 180.0)
    return min(odch_n, odch_s)


def _srednia_x_boku(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Oblicza srednia wspolrzedna X boku."""
    return (p1[0] + p2[0]) / 2.0


def _przeciecie_prostych(
    p1: Tuple[float, float], d1: Tuple[float, float],
    p2: Tuple[float, float], d2: Tuple[float, float]
) -> Optional[Tuple[float, float]]:
    """
    Znajduje punkt przeciecia dwoch prostych.
    Prosta 1: punkt p1, kierunek d1
    Prosta 2: punkt p2, kierunek d2

    Zwraca None jesli proste sa rownolegle.
    """
    # p1 + t*d1 = p2 + s*d2
    # p1x + t*d1x = p2x + s*d2x
    # p1z + t*d1z = p2z + s*d2z
    det = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(det) < 1e-10:
        return None
    # Rozwiazanie ukladu rownan
    dpx = p2[0] - p1[0]
    dpz = p2[1] - p1[1]
    t = (dpx * d2[1] - dpz * d2[0]) / det
    x = p1[0] + t * d1[0]
    z = p1[1] + t * d1[1]
    return (x, z)


def _odleglosc_punkt_od_prostej(
    punkt: Tuple[float, float],
    prosta_punkt: Tuple[float, float],
    prosta_normalna: Tuple[float, float]
) -> float:
    """
    Oblicza odleglosc ze znakiem punktu od prostej.
    Prosta definiowana przez punkt na prostej i normalna.
    Dodatnia odleglosc = po stronie normalnej (wewnatrz).
    """
    dx = punkt[0] - prosta_punkt[0]
    dz = punkt[1] - prosta_punkt[1]
    return dx * prosta_normalna[0] + dz * prosta_normalna[1]


def identyfikuj_granice(
    wierzcholki: List[Tuple[float, float]]
) -> Dict[str, Any]:
    """
    Identyfikuje granice poludniowa i wschodnia dzialki.

    Granica poludniowa: najdluzszy bok biegnacy E-W (odchylenie < 30 st.)
    Granica wschodnia: najdluzszy bok N-S z najwieksza srednia X

    Parametry:
        wierzcholki: lista krotek (x, z) wierzcholkow dzialki

    Zwraca:
        Slownik z kluczami: poludniowa (start, end), wschodnia (start, end)
    """
    n = len(wierzcholki)
    centroid_punkt = _centroid(wierzcholki)

    # Zbierz wszystkie boki z ich parametrami
    boki = []
    for i in range(n):
        p1 = wierzcholki[i]
        p2 = wierzcholki[(i + 1) % n]
        dlugosc = _dlugosc_odcinka(p1, p2)
        odch_ew = _odchylenie_od_ew(p1, p2)
        odch_ns = _odchylenie_od_ns(p1, p2)
        srednia_x = _srednia_x_boku(p1, p2)
        # Srednia Z - im wieksza, tym bardziej na poludnie (bo +Z = poludnie)
        srednia_z = (p1[1] + p2[1]) / 2.0
        boki.append({
            "p1": p1, "p2": p2,
            "dlugosc": dlugosc,
            "odch_ew": odch_ew,
            "odch_ns": odch_ns,
            "srednia_x": srednia_x,
            "srednia_z": srednia_z,
            "index": i,
        })

    # Granica poludniowa: najdluzszy bok E-W (odchylenie < 30 st.)
    # Sposrod bokow E-W wybieramy ten z najwieksza srednia Z (najbardziej poludniowy)
    boki_ew = [b for b in boki if b["odch_ew"] < 30.0]
    if not boki_ew:
        # Fallback: bok o najmniejszym odchyleniu od E-W
        boki_ew = sorted(boki, key=lambda b: b["odch_ew"])[:2]

    # Sposrod bokow E-W, wybierz najdluzszy z max srednia Z
    # Priorytet: dlugosc * waga + srednia_z * waga
    boki_ew_sorted = sorted(boki_ew, key=lambda b: (-b["dlugosc"], -b["srednia_z"]))
    granica_pd = boki_ew_sorted[0]

    # Granica wschodnia: najdluzszy bok N-S (odchylenie < 30 st.) z max srednia X
    boki_ns = [b for b in boki if b["odch_ns"] < 30.0]
    if not boki_ns:
        # Fallback: bok o najmniejszym odchyleniu od N-S
        boki_ns = sorted(boki, key=lambda b: b["odch_ns"])[:2]

    # Sposrod bokow N-S, wybierz najdluzszy z max srednia X
    boki_ns_sorted = sorted(boki_ns, key=lambda b: (-b["dlugosc"], -b["srednia_x"]))
    granica_ws = boki_ns_sorted[0]

    # Oblicz normalne wewnetrzne
    normalna_pd = _normalna_wewnetrzna(granica_pd["p1"], granica_pd["p2"], centroid_punkt)
    normalna_ws = _normalna_wewnetrzna(granica_ws["p1"], granica_ws["p2"], centroid_punkt)

    return {
        "poludniowa": {
            "start": granica_pd["p1"],
            "end": granica_pd["p2"],
            "dlugosc": granica_pd["dlugosc"],
            "normalna": normalna_pd,
            "kierunek": _kierunek_boku(granica_pd["p1"], granica_pd["p2"]),
        },
        "wschodnia": {
            "start": granica_ws["p1"],
            "end": granica_ws["p2"],
            "dlugosc": granica_ws["dlugosc"],
            "normalna": normalna_ws,
            "kierunek": _kierunek_boku(granica_ws["p1"], granica_ws["p2"]),
        },
    }


def _kierunek_boku_wektor(p1: Tuple[float, float], p2: Tuple[float, float]) -> Tuple[float, float]:
    """Zwraca znormalizowany wektor kierunku boku p1->p2."""
    dx = p2[0] - p1[0]
    dz = p2[1] - p1[1]
    dlugosc = math.sqrt(dx * dx + dz * dz)
    if dlugosc < 1e-10:
        return (0.0, 0.0)
    return (dx / dlugosc, dz / dlugosc)


def _polwymiar_wzdluz_normalnej(
    szerokosc: float, glebokosc: float, azymut: float,
    normalna: Tuple[float, float]
) -> float:
    """
    Oblicza polowe wymiaru obiektu w kierunku podanej normalnej.

    Budynek obraca sie wg azymutu - sciany nie sa rownolegle do osi.
    Projekcja pol-prostokata na kierunek normalnej.

    Parametry:
        szerokosc: wymiar X obiektu (przed obrotem)
        glebokosc: wymiar Z obiektu (przed obrotem)
        azymut: kat obrotu obiektu (stopnie, od polnocy zgodnie z zegarem)
        normalna: wektor normalny (nx, nz)
    """
    # Azymut obrotu obiektu - w ukladzie +X=E, +Z=S
    # Azymut 0 = polnoc = obiekt "patrzy" na -Z
    kat_rad = math.radians(azymut)

    # Wektory lokalne obiektu po obrocie
    # Os lokalna X obiektu (szerokosc) po obrocie o azymut:
    # W ukladzie Three.js, obrot wokol Y (gora) o kat = azymut
    # Lokalne X -> (cos(kat), sin(kat)) w XZ, ale z konwencja:
    # sin(azymut) daje skladowa +X, cos(azymut) daje skladowa -Z
    lok_x = (math.cos(kat_rad), -math.sin(kat_rad))  # kierunek lokalnej osi X
    lok_z = (math.sin(kat_rad), math.cos(kat_rad))   # kierunek lokalnej osi Z

    # Projekcja pol-wymiarow na normalna
    proj_x = abs(lok_x[0] * normalna[0] + lok_x[1] * normalna[1]) * (szerokosc / 2.0)
    proj_z = abs(lok_z[0] * normalna[0] + lok_z[1] * normalna[1]) * (glebokosc / 2.0)

    return proj_x + proj_z


def _narozniki_obiektu(
    cx: float, cz: float,
    szerokosc: float, glebokosc: float, azymut: float
) -> List[Dict[str, float]]:
    """
    Oblicza wspolrzedne 4 naroznikow obiektu.

    Parametry:
        cx, cz: srodek obiektu
        szerokosc: wymiar X (przed obrotem)
        glebokosc: wymiar Z (przed obrotem)
        azymut: kat obrotu (stopnie od polnocy)

    Zwraca:
        Lista 4 slownikow {x, z} z naroznikami
    """
    kat_rad = math.radians(azymut)

    # Polwymiary
    hw = szerokosc / 2.0
    hd = glebokosc / 2.0

    # Narozniki w ukladzie lokalnym (przed obrotem)
    lokalne = [
        (-hw, -hd),  # NW (polnocno-zachodni)
        (hw, -hd),   # NE (polnocno-wschodni)
        (hw, hd),    # SE (poludniowo-wschodni)
        (-hw, hd),   # SW (poludniowo-zachodni)
    ]

    narozniki = []
    cos_a = math.cos(kat_rad)
    sin_a = math.sin(kat_rad)
    for lx, lz in lokalne:
        # Obrot wokol srodka (konwencja Three.js: obrot Y)
        gx = cx + lx * cos_a + lz * sin_a
        gz = cz + lx * (-sin_a) + lz * cos_a
        narozniki.append({"x": round(gx, 4), "z": round(gz, 4)})

    return narozniki


def oblicz_pozycje_obiektu(
    wierzcholki: List[Tuple[float, float]],
    typ_obiektu: str,
    odleglosc_poludniowa: float,
    odleglosc_wschodnia: float,
    szerokosc: float,
    glebokosc: float,
    azymut: float
) -> Dict[str, Any]:
    """
    Oblicza pozycje srodka obiektu na podstawie odleglosci od granic.

    Dla budynku: odleglosc mierzona od SCIANY do granicy (dodaj pol wymiaru).
    Dla paneli: odleglosc mierzona od KRAWEDZI do granicy (dodaj pol wymiaru).

    Parametry:
        wierzcholki: lista krotek (x, z) - wierzcholki dzialki
        typ_obiektu: 'budynek' lub 'panele'
        odleglosc_poludniowa: odleglosc od granicy poludniowej [m]
        odleglosc_wschodnia: odleglosc od granicy wschodniej [m]
        szerokosc: wymiar X obiektu [m]
        glebokosc: wymiar Z obiektu [m]
        azymut: kat obrotu obiektu [stopnie od polnocy]

    Zwraca:
        Slownik z: x, z (srodek), narozniki, granica_poludniowa, granica_wschodnia
    """
    granice = identyfikuj_granice(wierzcholki)
    gr_pd = granice["poludniowa"]
    gr_ws = granice["wschodnia"]

    normalna_pd = gr_pd["normalna"]
    normalna_ws = gr_ws["normalna"]

    # Polwymiary wzdluz normalnych (offset od sciany/krawedzi do srodka)
    polwymiar_pd = _polwymiar_wzdluz_normalnej(szerokosc, glebokosc, azymut, normalna_pd)
    polwymiar_ws = _polwymiar_wzdluz_normalnej(szerokosc, glebokosc, azymut, normalna_ws)

    # Calkowite odleglosci od granicy do srodka obiektu
    # (odleglosc od sciany + pol wymiaru w kierunku normalnej)
    odl_srodek_pd = odleglosc_poludniowa + polwymiar_pd
    odl_srodek_ws = odleglosc_wschodnia + polwymiar_ws

    # Punkt na granicy poludniowej przesuniety o odl_srodek_pd w kierunku normalnej
    # Prosta rownlegla do granicy poludniowej w odleglosci odl_srodek_pd
    punkt_pd = (
        gr_pd["start"][0] + normalna_pd[0] * odl_srodek_pd,
        gr_pd["start"][1] + normalna_pd[1] * odl_srodek_pd,
    )
    kierunek_pd = _kierunek_boku_wektor(gr_pd["start"], gr_pd["end"])

    # Punkt na granicy wschodniej przesuniety o odl_srodek_ws w kierunku normalnej
    punkt_ws = (
        gr_ws["start"][0] + normalna_ws[0] * odl_srodek_ws,
        gr_ws["start"][1] + normalna_ws[1] * odl_srodek_ws,
    )
    kierunek_ws = _kierunek_boku_wektor(gr_ws["start"], gr_ws["end"])

    # Przeciecie dwoch prostych = pozycja srodka obiektu
    przeciecie = _przeciecie_prostych(punkt_pd, kierunek_pd, punkt_ws, kierunek_ws)

    if przeciecie is None:
        # Fallback: granice sa rownolegle - uzywamy punkt_pd
        przeciecie = punkt_pd

    cx, cz = przeciecie

    # Narozniki obiektu
    narozniki = _narozniki_obiektu(cx, cz, szerokosc, glebokosc, azymut)

    return {
        "x": round(cx, 4),
        "z": round(cz, 4),
        "narozniki": narozniki,
        "granica_poludniowa": {
            "start": {"x": gr_pd["start"][0], "z": gr_pd["start"][1]},
            "end": {"x": gr_pd["end"][0], "z": gr_pd["end"][1]},
            "dlugosc": round(gr_pd["dlugosc"], 2),
            "kierunek": round(gr_pd["kierunek"], 2),
        },
        "granica_wschodnia": {
            "start": {"x": gr_ws["start"][0], "z": gr_ws["start"][1]},
            "end": {"x": gr_ws["end"][0], "z": gr_ws["end"][1]},
            "dlugosc": round(gr_ws["dlugosc"], 2),
            "kierunek": round(gr_ws["kierunek"], 2),
        },
    }


def oblicz_odleglosc_od_granic(
    wierzcholki: List[Tuple[float, float]],
    x: float, z: float,
    szerokosc: float, glebokosc: float, azymut: float
) -> Dict[str, float]:
    """
    Oblicza odleglosci obiektu od granic dzialki (odwrotnosc oblicz_pozycje_obiektu).

    Dla budynku/paneli: odleglosc mierzona od SCIANY/KRAWEDZI do granicy.

    Parametry:
        wierzcholki: lista krotek (x, z) - wierzcholki dzialki
        x, z: pozycja srodka obiektu
        szerokosc: wymiar X obiektu [m]
        glebokosc: wymiar Z obiektu [m]
        azymut: kat obrotu obiektu [stopnie od polnocy]

    Zwraca:
        Slownik z: odleglosc_poludniowa, odleglosc_wschodnia
    """
    granice = identyfikuj_granice(wierzcholki)
    gr_pd = granice["poludniowa"]
    gr_ws = granice["wschodnia"]

    normalna_pd = gr_pd["normalna"]
    normalna_ws = gr_ws["normalna"]

    # Polwymiary wzdluz normalnych
    polwymiar_pd = _polwymiar_wzdluz_normalnej(szerokosc, glebokosc, azymut, normalna_pd)
    polwymiar_ws = _polwymiar_wzdluz_normalnej(szerokosc, glebokosc, azymut, normalna_ws)

    # Odleglosc srodka od granicy poludniowej (prostopadla do prostej granicy)
    odl_srodek_pd = _odleglosc_punkt_od_prostej((x, z), gr_pd["start"], normalna_pd)

    # Odleglosc srodka od granicy wschodniej
    odl_srodek_ws = _odleglosc_punkt_od_prostej((x, z), gr_ws["start"], normalna_ws)

    # Odleglosc sciany = odleglosc srodka - pol wymiaru
    odl_sciana_pd = odl_srodek_pd - polwymiar_pd
    odl_sciana_ws = odl_srodek_ws - polwymiar_ws

    return {
        "odleglosc_poludniowa": round(odl_sciana_pd, 4),
        "odleglosc_wschodnia": round(odl_sciana_ws, 4),
    }
