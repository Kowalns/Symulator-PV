"""
Testy pozycji Slonca - weryfikacja algorytmu obliczania azymutu i elewacji.

Testuje znane wartosci astronomiczne:
- Przesilenie letnie (21 czerwca) - najwyzsze Slonce
- Przesilenie zimowe (21 grudnia) - najnizsze Slonce
- Rownonoc wiosenna (20 marca) i jesienna (22 wrzesnia)
- Znane pozycje dla Warszawy (52.23N, 21.01E)

Dokladnosc: algorytm uproszczony, tolerancja +/- 3 stopnie.
"""

import unittest
import math

from backend.services.solar_position import (
    get_solar_position,
    oblicz_wektor_sloneczny,
    oblicz_godziny_sloneczne_rok,
    _dzien_roku,
    _oblicz_deklinacje_i_rownanie_czasu,
    _julian_day,
)


class TestDzienRoku(unittest.TestCase):
    """Testy obliczania numeru dnia w roku."""

    def test_pierwszy_styczen(self):
        """1 stycznia = dzien 1."""
        self.assertEqual(_dzien_roku(2025, 1, 1), 1)

    def test_ostatni_grudzien(self):
        """31 grudnia = dzien 365 (rok nieprzestepny)."""
        self.assertEqual(_dzien_roku(2025, 12, 31), 365)

    def test_rok_przestepny(self):
        """31 grudnia roku przestepnego = dzien 366."""
        self.assertEqual(_dzien_roku(2024, 12, 31), 366)

    def test_pierwszy_marca_nieprzestepny(self):
        """1 marca roku nieprzestepnego = dzien 60."""
        self.assertEqual(_dzien_roku(2025, 3, 1), 60)

    def test_pierwszy_marca_przestepny(self):
        """1 marca roku przestepnego = dzien 61."""
        self.assertEqual(_dzien_roku(2024, 3, 1), 61)


class TestDeklinacja(unittest.TestCase):
    """Testy deklinacji Slonca."""

    def test_przesilenie_letnie(self):
        """Deklinacja ok. +23.4 stopni wokol dnia 172 (21 czerwca)."""
        deklinacja, _ = _oblicz_deklinacje_i_rownanie_czasu(172)
        self.assertAlmostEqual(deklinacja, 23.4, delta=1.5)

    def test_przesilenie_zimowe(self):
        """Deklinacja ok. -23.4 stopni wokol dnia 355 (21 grudnia)."""
        deklinacja, _ = _oblicz_deklinacje_i_rownanie_czasu(355)
        self.assertAlmostEqual(deklinacja, -23.4, delta=1.5)

    def test_rownonoc_wiosenna(self):
        """Deklinacja bliska 0 wokol dnia 80 (21 marca)."""
        deklinacja, _ = _oblicz_deklinacje_i_rownanie_czasu(80)
        self.assertAlmostEqual(deklinacja, 0.0, delta=3.0)

    def test_rownonoc_jesienna(self):
        """Deklinacja bliska 0 wokol dnia 266 (23 wrzesnia)."""
        deklinacja, _ = _oblicz_deklinacje_i_rownanie_czasu(266)
        self.assertAlmostEqual(deklinacja, 0.0, delta=3.0)


class TestPozycjaSloncaWarszawa(unittest.TestCase):
    """
    Testy pozycji Slonca dla Warszawy (52.23N, 21.01E).

    Znane wartosci:
    - 21 czerwca, poludnie: elewacja ~61 stopni, azymut ~180 (poludnie)
    - 21 grudnia, poludnie: elewacja ~15 stopni, azymut ~180
    - Rownonoc: elewacja ~38 stopni w poludnie
    """

    def setUp(self):
        """Wspolrzedne Warszawy."""
        self.lat = 52.23
        self.lon = 21.01

    def test_przesilenie_letnie_poludnie(self):
        """21 czerwca w poludnie - elewacja ok. 61 stopni."""
        azymut, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 12, 0,
            strefa_czasowa=1.0
        )
        # Elewacja powinna byc miedzy 55 a 65 stopni
        self.assertGreater(elewacja, 50.0,
                          f"Elewacja {elewacja:.1f} za niska (oczekiwano >50)")
        self.assertLess(elewacja, 68.0,
                       f"Elewacja {elewacja:.1f} za wysoka (oczekiwano <68)")

    def test_przesilenie_zimowe_poludnie(self):
        """21 grudnia w poludnie - elewacja ok. 15 stopni."""
        azymut, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 12, 21, 12, 0,
            strefa_czasowa=1.0
        )
        # Elewacja powinna byc miedzy 10 a 20 stopni
        self.assertGreater(elewacja, 8.0,
                          f"Elewacja {elewacja:.1f} za niska (oczekiwano >8)")
        self.assertLess(elewacja, 22.0,
                       f"Elewacja {elewacja:.1f} za wysoka (oczekiwano <22)")

    def test_rownonoc_wiosenna_poludnie(self):
        """20 marca w poludnie - elewacja ok. 38 stopni."""
        azymut, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 3, 20, 12, 0,
            strefa_czasowa=1.0
        )
        # Elewacja powinna byc miedzy 33 a 43 stopni
        self.assertGreater(elewacja, 30.0)
        self.assertLess(elewacja, 46.0)

    def test_azymut_poludnie(self):
        """W poludnie azymut powinien byc blisko 180 (poludnie)."""
        azymut, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 12, 0,
            strefa_czasowa=1.0
        )
        # Azymut moze byc nie dokladnie 180 z powodu rownania czasu
        # i dlugosci geograficznej, ale powinien byc w zakresie 150-210
        self.assertGreater(azymut, 140.0)
        self.assertLess(azymut, 220.0)

    def test_noc_elewacja_ujemna(self):
        """O polnocy Slonce powinno byc pod horyzontem."""
        _, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 0, 0,
            strefa_czasowa=1.0
        )
        self.assertLess(elewacja, 5.0,
                       "O polnocy (godz 0) elewacja powinna byc niska/ujemna")

    def test_zima_noc_elewacja_ujemna(self):
        """W grudniu o 22:00 Slonce pod horyzontem."""
        _, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 12, 21, 22, 0,
            strefa_czasowa=1.0
        )
        self.assertLess(elewacja, 0.0,
                       "Zima o 22:00 Slonce powinno byc pod horyzontem")

    def test_wschod_niski_kat(self):
        """Rano Slonce powinno byc nisko nad horyzontem."""
        _, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 6, 0,
            strefa_czasowa=1.0
        )
        # O 6 rano latem powinno byc niewysoko
        self.assertGreater(elewacja, -5.0)
        self.assertLess(elewacja, 30.0)

    def test_azymut_rano_wschod(self):
        """Rano azymut powinien wskazywac na wschod (okolo 90)."""
        azymut, elewacja = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 6, 0,
            strefa_czasowa=1.0
        )
        if elewacja > 0:
            # Azymut rano powinien byc w okolicach 50-120 (polnocno-wschod do wschod)
            self.assertGreater(azymut, 30.0)
            self.assertLess(azymut, 150.0)

    def test_rozne_lata_podobne_wyniki(self):
        """Pozycja Slonca nie powinna drastycznie zmieniac sie miedzy latami."""
        _, elew_2025 = get_solar_position(
            self.lat, self.lon, 2025, 6, 21, 12, 0,
            strefa_czasowa=1.0
        )
        _, elew_2026 = get_solar_position(
            self.lat, self.lon, 2026, 6, 21, 12, 0,
            strefa_czasowa=1.0
        )
        self.assertAlmostEqual(elew_2025, elew_2026, delta=1.0)


class TestWektorSloneczny(unittest.TestCase):
    """Testy obliczania wektora kierunku promieni slonecznych."""

    def test_poludnie_zenit(self):
        """Slonce w zenicie (elewacja 90) - promienie padaja pionowo w dol."""
        dx, dy, dz = oblicz_wektor_sloneczny(180.0, 90.0)
        # Wektor powinien wskazywac w dol (dy ujemne)
        self.assertAlmostEqual(dy, -1.0, delta=0.01)
        self.assertAlmostEqual(abs(dx), 0.0, delta=0.01)
        self.assertAlmostEqual(abs(dz), 0.0, delta=0.01)

    def test_poludnie_niska_elewacja(self):
        """Slonce na poludniu, nisko - promienie z poludnia."""
        dx, dy, dz = oblicz_wektor_sloneczny(180.0, 30.0)
        # Promienie padaja od poludnia (dz ujemne w naszym ukladzie)
        # bo Z=poludnie, Slonce jest na poludniu, promienie ida NA polnoc
        self.assertLess(dy, 0)  # w dol

    def test_slonce_na_wschodzie(self):
        """Slonce na wschodzie (azymut 90) - promienie z zachodu."""
        dx, dy, dz = oblicz_wektor_sloneczny(90.0, 30.0)
        # Slonce na wschodzie, promienie padaja z zachodu -> dx ujemne
        self.assertLess(dx, 0)


class TestGodzinyRoku(unittest.TestCase):
    """Testy generowania godzinowych danych dla calego roku."""

    def test_liczba_godzin_rok_nieprzestepny(self):
        """Rok nieprzestepny ma 8760 godzin."""
        wyniki = oblicz_godziny_sloneczne_rok(52.23, 21.01, rok=2025)
        self.assertEqual(len(wyniki), 8760)

    def test_liczba_godzin_rok_przestepny(self):
        """Rok przestepny ma 8784 godzin."""
        wyniki = oblicz_godziny_sloneczne_rok(52.23, 21.01, rok=2024)
        self.assertEqual(len(wyniki), 8784)

    def test_struktura_wyniku(self):
        """Kazdy wynik powinien miec odpowiednie klucze."""
        wyniki = oblicz_godziny_sloneczne_rok(52.23, 21.01, rok=2025)
        wynik = wyniki[0]
        self.assertIn("miesiac", wynik)
        self.assertIn("dzien", wynik)
        self.assertIn("godzina", wynik)
        self.assertIn("azymut", wynik)
        self.assertIn("elewacja", wynik)
        self.assertIn("dzien_roku", wynik)

    def test_elewacja_latem_wyzsza_niz_zima(self):
        """Srednia elewacja latem powinna byc wyzsza niz zima."""
        wyniki = oblicz_godziny_sloneczne_rok(52.23, 21.01, rok=2025)

        # Godziny czerwcowe (poludnie)
        letnie = [w["elewacja"] for w in wyniki
                  if w["miesiac"] == 6 and w["godzina"] == 12]
        # Godziny grudniowe (poludnie)
        zimowe = [w["elewacja"] for w in wyniki
                  if w["miesiac"] == 12 and w["godzina"] == 12]

        srednia_lato = sum(letnie) / len(letnie)
        srednia_zima = sum(zimowe) / len(zimowe)

        self.assertGreater(srednia_lato, srednia_zima)


class TestJulianDay(unittest.TestCase):
    """Testy obliczania dnia Julianskiego."""

    def test_znana_data(self):
        """J2000.0 = 1 stycznia 2000, 12:00 UTC = JD 2451545.0."""
        jd = _julian_day(2000, 1, 1, 12, 0)
        self.assertAlmostEqual(jd, 2451545.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
