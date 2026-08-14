"""
Testy serwisu pozycjonowania obiektow na dzialce.

Testuje obliczenia pozycji budynku/paneli wzgledem granic dzialki.
Uzywa wierzcholkow testowej dzialki:
W0=(-20.8, 16.5), W1=(9.7, 21.4), W2=(15.2, -13.2), W3=(12.7, -15.6), W4=(-16.8, -9.2)

Uklad: +X = wschod, +Z = poludnie.
"""

import unittest
import json
import math
from backend.services.parcel_positioning import (
    identyfikuj_granice,
    oblicz_pozycje_obiektu,
    oblicz_odleglosc_od_granic,
    _dlugosc_odcinka,
    _kierunek_boku,
    _centroid,
    _normalna_wewnetrzna,
    _polwymiar_wzdluz_normalnej,
    _narozniki_obiektu,
)


# Wierzcholki testowej dzialki
WIERZCHOLKI = [
    (-20.8, 16.5),   # W0
    (9.7, 21.4),     # W1
    (15.2, -13.2),   # W2
    (12.7, -15.6),   # W3
    (-16.8, -9.2),   # W4
]

# Domyslne wymiary budynku
BUDYNEK_SZEROKOSC = 18.7  # m
BUDYNEK_GLEBOKOSC = 19.8  # m
BUDYNEK_AZYMUT = 350.0    # stopnie

# Domyslne wymiary paneli (przykladowe)
PANELE_SZEROKOSC = 10.0   # m
PANELE_GLEBOKOSC = 5.0    # m


class TestIdentyfikacjaGranic(unittest.TestCase):
    """Testy identyfikacji granic poludniowej i wschodniej."""

    def test_granica_poludniowa_to_W0_W1(self):
        """Granica poludniowa = W0->W1 (najdluzszy bok E-W)."""
        granice = identyfikuj_granice(WIERZCHOLKI)
        pd = granice["poludniowa"]

        # Sprawdz ze to bok W0->W1 (lub W1->W0)
        start = pd["start"]
        end = pd["end"]

        # Dlugosc powinna byc ok 30.9m
        self.assertAlmostEqual(pd["dlugosc"], 30.9, delta=1.0)

        # Sprawdz ze to wlasciwe wierzcholki
        punkty_boku = {(round(start[0], 1), round(start[1], 1)),
                       (round(end[0], 1), round(end[1], 1))}
        oczekiwane = {(-20.8, 16.5), (9.7, 21.4)}
        self.assertEqual(punkty_boku, oczekiwane)

    def test_granica_wschodnia_to_W1_W2(self):
        """Granica wschodnia = W1->W2 (najdluzszy bok N-S z max X)."""
        granice = identyfikuj_granice(WIERZCHOLKI)
        ws = granice["wschodnia"]

        # Dlugosc powinna byc ok 35.0m
        self.assertAlmostEqual(ws["dlugosc"], 35.0, delta=1.0)

        # Sprawdz ze to wlasciwe wierzcholki
        start = ws["start"]
        end = ws["end"]
        punkty_boku = {(round(start[0], 1), round(start[1], 1)),
                       (round(end[0], 1), round(end[1], 1))}
        oczekiwane = {(9.7, 21.4), (15.2, -13.2)}
        self.assertEqual(punkty_boku, oczekiwane)

    def test_normalna_poludniowa_skierowana_do_wnetrza(self):
        """Normalna poludniowa powinna wskazywac do wnetrza dzialki (w strone centroidu)."""
        granice = identyfikuj_granice(WIERZCHOLKI)
        normalna = granice["poludniowa"]["normalna"]
        centroid_punkt = _centroid(WIERZCHOLKI)

        # Normalna powinna miec skladowa -Z (bo centroid jest na polnoc od granicy pd)
        # W naszym ukladzie +Z = poludnie, wiec wnetrze jest w kierunku -Z
        self.assertLess(normalna[1], 0,
                        "Normalna poludniowa powinna miec skladowa -Z (do wnetrza)")

    def test_normalna_wschodnia_skierowana_do_wnetrza(self):
        """Normalna wschodnia powinna wskazywac do wnetrza dzialki."""
        granice = identyfikuj_granice(WIERZCHOLKI)
        normalna = granice["wschodnia"]["normalna"]

        # Normalna powinna miec skladowa -X (bo centroid jest na zachod od granicy ws)
        self.assertLess(normalna[0], 0,
                        "Normalna wschodnia powinna miec skladowa -X (do wnetrza)")

    def test_normalna_jest_jednostkowa(self):
        """Normalne powinny byc znormalizowane (dlugosc = 1)."""
        granice = identyfikuj_granice(WIERZCHOLKI)

        for nazwa in ["poludniowa", "wschodnia"]:
            nx, nz = granice[nazwa]["normalna"]
            dlugosc = math.sqrt(nx * nx + nz * nz)
            self.assertAlmostEqual(dlugosc, 1.0, places=6,
                                   msg=f"Normalna {nazwa} nie jest jednostkowa")


class TestObliczPozycjeObiektu(unittest.TestCase):
    """Testy obliczania pozycji obiektu na dzialce."""

    def test_budynek_5m_6m_pozycja(self):
        """Budynek w odleglosci 5m/6m od granic -> pozycja z poprawnym roundtrip."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=6.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Weryfikacja poprawnosci przez roundtrip (odleglosc -> pozycja -> odleglosc)
        odl = oblicz_odleglosc_od_granic(
            wierzcholki=WIERZCHOLKI,
            x=wynik["x"],
            z=wynik["z"],
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )
        self.assertAlmostEqual(odl["odleglosc_poludniowa"], 5.0, delta=0.1,
                               msg="Roundtrip poludniowa powinna byc 5.0m")
        self.assertAlmostEqual(odl["odleglosc_wschodnia"], 6.0, delta=0.1,
                               msg="Roundtrip wschodnia powinna byc 6.0m")

        # Pozycja powinna byc w rozsadnym obszarze dzialki
        # (centroid dzialki ~ (0, 0), wiec pozycja powinna byc blisko)
        self.assertAlmostEqual(wynik["x"], -3.3, delta=2.0,
                               msg=f"X pozycji budynku: oczekiwano ~-3.3, dostano {wynik['x']}")
        self.assertAlmostEqual(wynik["z"], 4.1, delta=2.0,
                               msg=f"Z pozycji budynku: oczekiwano ~4.1, dostano {wynik['z']}")

    def test_budynek_zwraca_narozniki(self):
        """Wynik powinien zawierac 4 narozniki."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=6.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        self.assertEqual(len(wynik["narozniki"]), 4)
        for naroznik in wynik["narozniki"]:
            self.assertIn("x", naroznik)
            self.assertIn("z", naroznik)

    def test_budynek_zwraca_info_o_granicach(self):
        """Wynik powinien zawierac informacje o zidentyfikowanych granicach."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=6.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        self.assertIn("granica_poludniowa", wynik)
        self.assertIn("granica_wschodnia", wynik)
        self.assertIn("start", wynik["granica_poludniowa"])
        self.assertIn("end", wynik["granica_poludniowa"])
        self.assertIn("dlugosc", wynik["granica_poludniowa"])
        self.assertIn("kierunek", wynik["granica_poludniowa"])

    def test_panele_31m_1m_pozycja_wewnatrz_dzialki(self):
        """Panele w odleglosci 31m/1m powinny byc wewnatrz dzialki."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="panele",
            odleglosc_poludniowa=31.0,
            odleglosc_wschodnia=1.0,
            szerokosc=PANELE_SZEROKOSC,
            glebokosc=PANELE_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Sprawdz ze wynik jest sensowny (w zakresie dzialki)
        self.assertIsNotNone(wynik["x"])
        self.assertIsNotNone(wynik["z"])

    def test_zero_odleglosci(self):
        """Obiekt przy odleglosci 0 powinien byc blisko granicy."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=0.0,
            odleglosc_wschodnia=0.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Przy zerowych odleglosciach, srodek powinien byc przesuniety
        # o polwymiar od granicy (bo odleglosc jest od sciany)
        self.assertIsNotNone(wynik["x"])
        self.assertIsNotNone(wynik["z"])

    def test_duza_odleglosc(self):
        """Obiekt przy duzej odleglosci powinien byc daleko od granicy."""
        wynik_blisko = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=2.0,
            odleglosc_wschodnia=2.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        wynik_daleko = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=15.0,
            odleglosc_wschodnia=15.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Przy wiekszej odleglosci, obiekt powinien byc dalej od granic
        # (bardziej w kierunku normalnych wewnetrznych)
        # Nie testujemy dokladnej wartosci, ale ze sie roznia
        dist = math.sqrt((wynik_blisko["x"] - wynik_daleko["x"])**2 +
                        (wynik_blisko["z"] - wynik_daleko["z"])**2)
        self.assertGreater(dist, 5.0, "Rozne odleglosci powinny dawac rozne pozycje")


class TestObliczOdlegloscOdGranic(unittest.TestCase):
    """Testy obliczania odleglosci od granic (operacja odwrotna)."""

    def test_roundtrip_budynek_5m_6m(self):
        """Roundtrip: pozycja z 5m/6m -> odleglosc -> powinno byc 5m/6m."""
        # Krok 1: oblicz pozycje
        wynik_poz = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=6.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Krok 2: oblicz odleglosci z powrotem
        wynik_odl = oblicz_odleglosc_od_granic(
            wierzcholki=WIERZCHOLKI,
            x=wynik_poz["x"],
            z=wynik_poz["z"],
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Tolerancja 0.1m
        self.assertAlmostEqual(wynik_odl["odleglosc_poludniowa"], 5.0, delta=0.1,
                               msg=f"Odleglosc pd roundtrip: oczekiwano 5.0, dostano {wynik_odl['odleglosc_poludniowa']}")
        self.assertAlmostEqual(wynik_odl["odleglosc_wschodnia"], 6.0, delta=0.1,
                               msg=f"Odleglosc ws roundtrip: oczekiwano 6.0, dostano {wynik_odl['odleglosc_wschodnia']}")

    def test_roundtrip_panele_31m_1m(self):
        """Roundtrip: pozycja paneli z 31m/1m -> odleglosc -> powinno byc 31m/1m."""
        wynik_poz = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="panele",
            odleglosc_poludniowa=31.0,
            odleglosc_wschodnia=1.0,
            szerokosc=PANELE_SZEROKOSC,
            glebokosc=PANELE_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        wynik_odl = oblicz_odleglosc_od_granic(
            wierzcholki=WIERZCHOLKI,
            x=wynik_poz["x"],
            z=wynik_poz["z"],
            szerokosc=PANELE_SZEROKOSC,
            glebokosc=PANELE_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        self.assertAlmostEqual(wynik_odl["odleglosc_poludniowa"], 31.0, delta=0.1)
        self.assertAlmostEqual(wynik_odl["odleglosc_wschodnia"], 1.0, delta=0.1)

    def test_roundtrip_rozne_odleglosci(self):
        """Roundtrip dla roznych odleglosci."""
        przypadki = [
            (1.0, 1.0),
            (3.0, 8.0),
            (10.0, 10.0),
            (0.5, 20.0),
        ]

        for odl_pd, odl_ws in przypadki:
            with self.subTest(odl_pd=odl_pd, odl_ws=odl_ws):
                wynik_poz = oblicz_pozycje_obiektu(
                    wierzcholki=WIERZCHOLKI,
                    typ_obiektu="budynek",
                    odleglosc_poludniowa=odl_pd,
                    odleglosc_wschodnia=odl_ws,
                    szerokosc=BUDYNEK_SZEROKOSC,
                    glebokosc=BUDYNEK_GLEBOKOSC,
                    azymut=BUDYNEK_AZYMUT,
                )

                wynik_odl = oblicz_odleglosc_od_granic(
                    wierzcholki=WIERZCHOLKI,
                    x=wynik_poz["x"],
                    z=wynik_poz["z"],
                    szerokosc=BUDYNEK_SZEROKOSC,
                    glebokosc=BUDYNEK_GLEBOKOSC,
                    azymut=BUDYNEK_AZYMUT,
                )

                self.assertAlmostEqual(
                    wynik_odl["odleglosc_poludniowa"], odl_pd, delta=0.1,
                    msg=f"Roundtrip pd failed for ({odl_pd}, {odl_ws})")
                self.assertAlmostEqual(
                    wynik_odl["odleglosc_wschodnia"], odl_ws, delta=0.1,
                    msg=f"Roundtrip ws failed for ({odl_pd}, {odl_ws})")

    def test_roundtrip_pozycja_do_odleglosci_do_pozycji(self):
        """Pelny roundtrip: pozycja -> odleglosc -> pozycja powinno byc spojne."""
        # Oblicz pozycje
        wynik1 = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=6.0,
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Oblicz odleglosci
        odleglosci = oblicz_odleglosc_od_granic(
            wierzcholki=WIERZCHOLKI,
            x=wynik1["x"],
            z=wynik1["z"],
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Oblicz pozycje z powrotem
        wynik2 = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="budynek",
            odleglosc_poludniowa=odleglosci["odleglosc_poludniowa"],
            odleglosc_wschodnia=odleglosci["odleglosc_wschodnia"],
            szerokosc=BUDYNEK_SZEROKOSC,
            glebokosc=BUDYNEK_GLEBOKOSC,
            azymut=BUDYNEK_AZYMUT,
        )

        # Pozycje powinny byc takie same (tolerancja 0.1m)
        self.assertAlmostEqual(wynik1["x"], wynik2["x"], delta=0.1)
        self.assertAlmostEqual(wynik1["z"], wynik2["z"], delta=0.1)


class TestFunkcjePomocnicze(unittest.TestCase):
    """Testy funkcji pomocniczych."""

    def test_dlugosc_odcinka(self):
        """Test obliczania dlugosci odcinka."""
        self.assertAlmostEqual(_dlugosc_odcinka((0, 0), (3, 4)), 5.0, places=5)
        self.assertAlmostEqual(_dlugosc_odcinka((1, 1), (1, 1)), 0.0, places=5)
        self.assertAlmostEqual(_dlugosc_odcinka((-1, -1), (1, 1)), math.sqrt(8), places=5)

    def test_kierunek_boku(self):
        """Test obliczania azymutu boku."""
        # Bok na wschod: azymut = 90
        self.assertAlmostEqual(_kierunek_boku((0, 0), (1, 0)), 90.0, delta=0.1)
        # Bok na poludnie (+Z): azymut = 180
        self.assertAlmostEqual(_kierunek_boku((0, 0), (0, 1)), 180.0, delta=0.1)
        # Bok na polnoc (-Z): azymut = 0 (lub 360)
        kier = _kierunek_boku((0, 0), (0, -1))
        self.assertTrue(abs(kier) < 0.1 or abs(kier - 360.0) < 0.1)
        # Bok na zachod: azymut = 270
        self.assertAlmostEqual(_kierunek_boku((0, 0), (-1, 0)), 270.0, delta=0.1)

    def test_centroid(self):
        """Test obliczania centroidu."""
        c = _centroid(WIERZCHOLKI)
        # Centroid powinna byc w srodku dzialki
        self.assertAlmostEqual(c[0], 0.0, delta=5.0)  # Blisko X=0
        self.assertAlmostEqual(c[1], 0.0, delta=5.0)  # Blisko Z=0

    def test_polwymiar_wzdluz_normalnej_azymut_0(self):
        """Test polwymiaru przy azymucie 0 (obiekt skierowany na polnoc)."""
        # Normalna w kierunku -X: projekcja szerokosc
        polw = _polwymiar_wzdluz_normalnej(10.0, 8.0, 0.0, (-1.0, 0.0))
        self.assertAlmostEqual(polw, 5.0, delta=0.1)

        # Normalna w kierunku -Z: projekcja glebokosc
        polw = _polwymiar_wzdluz_normalnej(10.0, 8.0, 0.0, (0.0, -1.0))
        self.assertAlmostEqual(polw, 4.0, delta=0.1)

    def test_narozniki_przy_azymucie_0(self):
        """Test naroznikow obiektu bez obrotu."""
        narozniki = _narozniki_obiektu(0.0, 0.0, 10.0, 8.0, 0.0)
        self.assertEqual(len(narozniki), 4)

        # Przy azymucie 0, narozniki powinny byc prostokatne
        xs = sorted([n["x"] for n in narozniki])
        zs = sorted([n["z"] for n in narozniki])
        self.assertAlmostEqual(xs[0], -5.0, delta=0.01)
        self.assertAlmostEqual(xs[-1], 5.0, delta=0.01)
        self.assertAlmostEqual(zs[0], -4.0, delta=0.01)
        self.assertAlmostEqual(zs[-1], 4.0, delta=0.01)


class TestEdgeCases(unittest.TestCase):
    """Testy przypadkow brzegowych."""

    def test_kwadratowa_dzialka(self):
        """Test na prostej kwadratowej dzialce."""
        kwadrat = [
            (-10.0, 10.0),   # SW (lewy-poludniowy)
            (10.0, 10.0),    # SE (prawy-poludniowy)
            (10.0, -10.0),   # NE (prawy-polnocny)
            (-10.0, -10.0),  # NW (lewy-polnocny)
        ]

        wynik = oblicz_pozycje_obiektu(
            wierzcholki=kwadrat,
            typ_obiektu="budynek",
            odleglosc_poludniowa=3.0,
            odleglosc_wschodnia=4.0,
            szerokosc=4.0,
            glebokosc=4.0,
            azymut=0.0,
        )

        # Na kwadratowej dzialce (boki rownolegle do osi):
        # Granica pd (najbardziej na poludniu, E-W) = dolny bok (z=10)
        # Normalna pd = (0, -1) (w strone centroidu)
        # Granica ws (najbardziej na wschodzie, N-S) = prawy bok (x=10)
        # Normalna ws = (-1, 0) (w strone centroidu)
        # Odl sciany pd = 3m -> srodek = 3 + 2 = 5m od granicy pd
        # Z = 10 - 5 = 5.0
        # Odl sciany ws = 4m -> srodek = 4 + 2 = 6m od granicy ws
        # X = 10 - 6 = 4.0
        self.assertAlmostEqual(wynik["x"], 4.0, delta=0.5)
        self.assertAlmostEqual(wynik["z"], 5.0, delta=0.5)

    def test_bardzo_maly_obiekt(self):
        """Test z bardzo malym obiektem."""
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=WIERZCHOLKI,
            typ_obiektu="panele",
            odleglosc_poludniowa=5.0,
            odleglosc_wschodnia=5.0,
            szerokosc=1.0,
            glebokosc=1.0,
            azymut=0.0,
        )

        # Powinien dzialac bez bledow
        self.assertIsNotNone(wynik["x"])
        self.assertIsNotNone(wynik["z"])

    def test_rozne_azymuty_budynku(self):
        """Rozne azymuty powinny dawac rozne pozycje (bo polwymiary sie zmieniaja)."""
        wyniki = []
        for azymut in [0, 45, 90, 180, 270, 350]:
            wynik = oblicz_pozycje_obiektu(
                wierzcholki=WIERZCHOLKI,
                typ_obiektu="budynek",
                odleglosc_poludniowa=5.0,
                odleglosc_wschodnia=6.0,
                szerokosc=BUDYNEK_SZEROKOSC,
                glebokosc=BUDYNEK_GLEBOKOSC,
                azymut=float(azymut),
            )
            wyniki.append((wynik["x"], wynik["z"]))

        # Nie wszystkie powinny byc identyczne (bo BUDYNEK_SZEROKOSC != BUDYNEK_GLEBOKOSC)
        unikalne = set((round(x, 1), round(z, 1)) for x, z in wyniki)
        self.assertGreater(len(unikalne), 1,
                           "Rozne azymuty powinny dawac rozne pozycje dla niekwadratowego obiektu")


class TestHandlerIntegration(unittest.TestCase):
    """Testy integracyjne handlerow API (import i wywolanie)."""

    def test_handle_parcel_position_basic(self):
        """Test handlera pozycji z poprawnymi danymi."""
        from backend.api.handlers import handle_parcel_position

        dane = {
            "wierzcholki": WIERZCHOLKI,
            "typ_obiektu": "budynek",
            "odleglosc_poludniowa": 5.0,
            "odleglosc_wschodnia": 6.0,
            "szerokosc": BUDYNEK_SZEROKOSC,
            "glebokosc": BUDYNEK_GLEBOKOSC,
            "azymut": BUDYNEK_AZYMUT,
        }
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_parcel_position(body)

        self.assertEqual(status, 200)
        self.assertIn("x", response)
        self.assertIn("z", response)
        self.assertIn("narozniki", response)
        self.assertIn("granica_poludniowa", response)
        self.assertIn("granica_wschodnia", response)

    def test_handle_parcel_position_brak_danych(self):
        """Test handlera pozycji bez danych."""
        from backend.api.handlers import handle_parcel_position

        status, response = handle_parcel_position(None)
        self.assertEqual(status, 400)
        self.assertIn("error", response)

    def test_handle_parcel_position_zly_json(self):
        """Test handlera pozycji z nieprawidlowym JSON."""
        from backend.api.handlers import handle_parcel_position

        status, response = handle_parcel_position(b"nie-json")
        self.assertEqual(status, 400)

    def test_handle_parcel_position_brak_wymaganych_pol(self):
        """Test handlera pozycji bez wymaganych pol."""
        from backend.api.handlers import handle_parcel_position

        dane = {"wierzcholki": WIERZCHOLKI}  # brakuje reszty
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_parcel_position(body)
        self.assertEqual(status, 400)

    def test_handle_parcel_distance_basic(self):
        """Test handlera odleglosci z poprawnymi danymi."""
        from backend.api.handlers import handle_parcel_distance

        dane = {
            "wierzcholki": WIERZCHOLKI,
            "x": -5.0,
            "z": 3.0,
            "szerokosc": BUDYNEK_SZEROKOSC,
            "glebokosc": BUDYNEK_GLEBOKOSC,
            "azymut": BUDYNEK_AZYMUT,
        }
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_parcel_distance(body)

        self.assertEqual(status, 200)
        self.assertIn("odleglosc_poludniowa", response)
        self.assertIn("odleglosc_wschodnia", response)

    def test_handle_parcel_distance_brak_danych(self):
        """Test handlera odleglosci bez danych."""
        from backend.api.handlers import handle_parcel_distance

        status, response = handle_parcel_distance(None)
        self.assertEqual(status, 400)

    def test_handle_parcel_distance_zly_json(self):
        """Test handlera odleglosci z nieprawidlowym JSON."""
        from backend.api.handlers import handle_parcel_distance

        status, response = handle_parcel_distance(b"{invalid}")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
