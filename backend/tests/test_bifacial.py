"""
Testy jednostkowe dla obliczen paneli bifacjalnych.

Testuje:
- oblicz_zysk_bifacjalny - dodatkowa irradiancja z tylnej strony
- Interpolacja wspolczynnika wysokosci
- Integracja z oblicz_roczna_produkcje_panela
"""
import unittest
import json
import os

from backend.services.panel_performance import (
    oblicz_zysk_bifacjalny,
    oblicz_roczna_produkcje_panela,
    ALBEDO_DOMYSLNE,
)


class TestObliczZyskBifacjalny(unittest.TestCase):
    """Testy funkcji oblicz_zysk_bifacjalny."""

    def test_zerowe_ghi_zwraca_zero(self):
        """Brak naslonecznienia - brak zysku bifacjalnego."""
        wynik = oblicz_zysk_bifacjalny(0.0, 0.2, 0.70, 1.0)
        self.assertEqual(wynik, 0.0)

    def test_zerowe_albedo_zwraca_zero(self):
        """Zerowe albedo - brak odbicia od gruntu."""
        wynik = oblicz_zysk_bifacjalny(500.0, 0.0, 0.70, 1.0)
        self.assertEqual(wynik, 0.0)

    def test_zerowy_wspolczynnik_bifacjalny_zwraca_zero(self):
        """Zerowy wspolczynnik bifacjalny - brak zysku."""
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.0, 1.0)
        self.assertEqual(wynik, 0.0)

    def test_ujemne_ghi_zwraca_zero(self):
        """Ujemne GHI - brak zysku."""
        wynik = oblicz_zysk_bifacjalny(-100.0, 0.2, 0.70, 1.0)
        self.assertEqual(wynik, 0.0)

    def test_wysokosc_0_5m_wspolczynnik_0_6(self):
        """Wysokosc 0.5m - wspolczynnik wysokosci = 0.6."""
        # zysk = 500 * 0.2 * 0.70 * 0.6 = 42.0
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 0.5)
        self.assertAlmostEqual(wynik, 42.0, places=2)

    def test_wysokosc_1_0m_wspolczynnik_0_8(self):
        """Wysokosc 1.0m - wspolczynnik wysokosci = 0.8."""
        # zysk = 500 * 0.2 * 0.70 * 0.8 = 56.0
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.0)
        self.assertAlmostEqual(wynik, 56.0, places=2)

    def test_wysokosc_1_5m_wspolczynnik_0_95(self):
        """Wysokosc 1.5m - wspolczynnik wysokosci = 0.95."""
        # zysk = 500 * 0.2 * 0.70 * 0.95 = 66.5
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.5)
        self.assertAlmostEqual(wynik, 66.5, places=2)

    def test_wysokosc_powyzej_1_5m_cap_0_95(self):
        """Wysokosc powyzej 1.5m - cap na 0.95."""
        wynik_1_5 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.5)
        wynik_2_0 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 2.0)
        wynik_3_0 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 3.0)
        self.assertAlmostEqual(wynik_1_5, wynik_2_0, places=2)
        self.assertAlmostEqual(wynik_1_5, wynik_3_0, places=2)

    def test_interpolacja_0_75m(self):
        """Interpolacja liniowa miedzy 0.5m i 1.0m - srodek = 0.75m."""
        # wspolczynnik = 0.6 + 0.5 * (0.8 - 0.6) = 0.7
        # zysk = 500 * 0.2 * 0.70 * 0.7 = 49.0
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 0.75)
        self.assertAlmostEqual(wynik, 49.0, places=2)

    def test_interpolacja_1_25m(self):
        """Interpolacja liniowa miedzy 1.0m i 1.5m - srodek = 1.25m."""
        # wspolczynnik = 0.8 + 0.5 * (0.95 - 0.8) = 0.875
        # zysk = 500 * 0.2 * 0.70 * 0.875 = 61.25
        wynik = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.25)
        self.assertAlmostEqual(wynik, 61.25, places=2)

    def test_wysokosc_ponizej_0_5m_minimum_0_6(self):
        """Wysokosc ponizej 0.5m - minimum wspolczynnik = 0.6."""
        wynik_0_5 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 0.5)
        wynik_0_2 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 0.2)
        self.assertAlmostEqual(wynik_0_5, wynik_0_2, places=2)

    def test_albedo_snieg_wiekszy_zysk(self):
        """Albedo sniegu (0.6) daje wiekszy zysk niz trawa (0.2)."""
        zysk_trawa = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.0)
        zysk_snieg = oblicz_zysk_bifacjalny(500.0, 0.6, 0.70, 1.0)
        self.assertGreater(zysk_snieg, zysk_trawa)
        # Snieg powinien dawac 3x wiecej niz trawa (0.6/0.2 = 3)
        self.assertAlmostEqual(zysk_snieg / zysk_trawa, 3.0, places=2)

    def test_wynik_proporcjonalny_do_ghi(self):
        """Zysk bifacjalny jest proporcjonalny do GHI."""
        zysk_500 = oblicz_zysk_bifacjalny(500.0, 0.2, 0.70, 1.0)
        zysk_1000 = oblicz_zysk_bifacjalny(1000.0, 0.2, 0.70, 1.0)
        self.assertAlmostEqual(zysk_1000 / zysk_500, 2.0, places=2)

    def test_domyslne_albedo(self):
        """Weryfikacja domyslnego albedo = 0.2."""
        self.assertEqual(ALBEDO_DOMYSLNE, 0.2)


class TestBifacialIntegracjaProdukcja(unittest.TestCase):
    """Testy integracji bifacjalnej z oblicz_roczna_produkcje_panela."""

    def _stworz_minimalne_dane_tmy(self, godzin=8760):
        """Tworzy minimalne dane TMY dla testow."""
        return {
            "ghi": [500.0] * godzin,
            "dni": [400.0] * godzin,
            "dhi": [100.0] * godzin,
            "temperatura": [15.0] * godzin,
        }

    def _stworz_zacienienia_godzinowe(self, godzin=8760):
        """Tworzy minimalne dane zacienienia godzinowego."""
        from backend.services.shading import WynikZacienieniaGodzina, WynikZacienieniaPanel

        wyniki = []
        dzien_roku = 0
        for godzina_idx in range(godzin):
            godzina = godzina_idx % 24
            if godzina_idx > 0 and godzina == 0:
                dzien_roku += 1

            miesiac = min(12, dzien_roku // 30 + 1)
            dzien = (dzien_roku % 30) + 1

            # Elewacja - uproszczona: >0 tylko w godzinach 6-18
            if 6 <= godzina <= 18:
                elewacja = 30.0
            else:
                elewacja = -10.0

            panel_zac = WynikZacienieniaPanel(
                panel_index=0,
                stopien_zacienienia=0.0,
                sekcje_zacienione=[],
                bypass_aktywne=0,
                polowa_gorna_zacieniona=False,
                polowa_dolna_zacieniona=False,
            )

            wynik = WynikZacienieniaGodzina(
                miesiac=miesiac,
                dzien=dzien,
                godzina=godzina,
                elewacja_slonca=elewacja,
                azymut_slonca=180.0,
                panele=[panel_zac],
            )
            wyniki.append(wynik)
        return wyniki

    def test_bifacial_produkuje_wiecej_niz_monofacial(self):
        """Panel bifacjalny produkuje wiecej energii niz identyczny monofacjalny."""
        dane_tmy = self._stworz_minimalne_dane_tmy()
        zacienienia = self._stworz_zacienienia_godzinowe()

        # Panel monofacjalny
        wynik_mono = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
            bifacial=False,
        )

        # Panel bifacjalny
        wynik_bif = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
            bifacial=True,
            bifacial_wspolczynnik=0.70,
            przeswit_nad_gruntem_m=1.0,
            albedo=0.2,
        )

        self.assertGreater(
            wynik_bif["energia_roczna_kwh"],
            wynik_mono["energia_roczna_kwh"]
        )

    def test_bifacial_false_nie_zmienia_wyniku(self):
        """Gdy bifacial=False, wynik jest taki sam jak bez parametrow bifacjalnych."""
        dane_tmy = self._stworz_minimalne_dane_tmy()
        zacienienia = self._stworz_zacienienia_godzinowe()

        wynik_domyslny = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
        )

        wynik_explicit_false = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
            bifacial=False,
            bifacial_wspolczynnik=0.70,
        )

        self.assertAlmostEqual(
            wynik_domyslny["energia_roczna_kwh"],
            wynik_explicit_false["energia_roczna_kwh"],
            places=2
        )

    def test_wieksze_albedo_wiekszy_zysk_bifacjalny(self):
        """Wieksze albedo (np. snieg) daje wiekszy zysk bifacjalny."""
        dane_tmy = self._stworz_minimalne_dane_tmy()
        zacienienia = self._stworz_zacienienia_godzinowe()

        wynik_trawa = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
            bifacial=True,
            bifacial_wspolczynnik=0.70,
            przeswit_nad_gruntem_m=1.0,
            albedo=0.2,
        )

        wynik_snieg = oblicz_roczna_produkcje_panela(
            moc_stc_w=545.0,
            wspolczynnik_temp_pmax=-0.34,
            technologia="half-cut",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            dane_tmy=dane_tmy,
            bifacial=True,
            bifacial_wspolczynnik=0.70,
            przeswit_nad_gruntem_m=1.0,
            albedo=0.6,
        )

        self.assertGreater(
            wynik_snieg["energia_roczna_kwh"],
            wynik_trawa["energia_roczna_kwh"]
        )


class TestBifacialBazaDanych(unittest.TestCase):
    """Testy obecnosci paneli bifacjalnych w bazie danych."""

    def setUp(self):
        """Wczytaj baze danych paneli."""
        sciezka = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'panels_database.json'
        )
        with open(sciezka, 'r', encoding='utf-8') as f:
            self.panele = json.load(f)

    def test_sa_panele_bifacjalne_w_bazie(self):
        """Baza danych zawiera panele bifacjalne."""
        bifacjalne = [p for p in self.panele if p.get("bifacial", False)]
        self.assertGreaterEqual(len(bifacjalne), 2)

    def test_panele_bifacjalne_maja_wspolczynnik(self):
        """Panele bifacjalne maja pole bifacial_wspolczynnik."""
        bifacjalne = [p for p in self.panele if p.get("bifacial", False)]
        for panel in bifacjalne:
            self.assertIn("bifacial_wspolczynnik", panel)
            self.assertGreater(panel["bifacial_wspolczynnik"], 0.0)
            self.assertLessEqual(panel["bifacial_wspolczynnik"], 1.0)

    def test_panele_bifacjalne_wspolczynnik_070(self):
        """Panele bifacjalne maja wspolczynnik 0.70 (70% wydajnosci tylnej strony)."""
        bifacjalne = [p for p in self.panele if p.get("bifacial", False)]
        for panel in bifacjalne:
            self.assertAlmostEqual(panel["bifacial_wspolczynnik"], 0.70, places=2)

    def test_panele_niebifacjalne_nie_maja_pola(self):
        """Panele niebifacjalne nie maja pola bifacial lub maja False."""
        niebifacjalne = [p for p in self.panele if not p.get("bifacial", False)]
        self.assertGreater(len(niebifacjalne), 0)
        for panel in niebifacjalne:
            # Pole moze nie istniec lub byc False
            self.assertFalse(panel.get("bifacial", False))

    def test_struktura_paneli_bifacjalnych(self):
        """Panele bifacjalne maja wszystkie wymagane pola bazowe."""
        bifacjalne = [p for p in self.panele if p.get("bifacial", False)]
        wymagane_pola = [
            "id", "producent", "model", "moc_wp", "wymiary_mm",
            "wydajnosc_procent", "wspolczynnik_temp_pmax", "technologia",
            "liczba_sekcji_bypass", "napiecie_mpp", "prad_mpp",
            "napiecie_oc", "prad_sc", "degradacja_roczna_procent",
            "waga_kg", "gwarancja_lata"
        ]
        for panel in bifacjalne:
            for pole in wymagane_pola:
                self.assertIn(pole, panel, f"Brak pola '{pole}' w {panel['id']}")


if __name__ == '__main__':
    unittest.main()
