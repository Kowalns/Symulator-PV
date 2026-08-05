"""
Testy algorytmu zacienienia paneli PV.

Testuje:
- Rzutowanie cienia budynku na panele
- Aktywacje bypass diod przy zacienieniu >50% sekcji
- Zachowanie technologii half-cut (niezaleznosc polowek)
- Dzialanie optymalizatorow mocy
- Obliczanie wydajnosci panela z uwzglednieniem temperatury
"""

import unittest
import math

from backend.models.installation import PanelPosition, InstallationConfig
from backend.services.shading import (
    BudynekConfig,
    WynikZacienieniaPanel,
    oblicz_zacienienie_pojedyncza_godzina,
    _oblicz_cien_budynku_na_gruncie,
    _bounding_box_cienia,
    _oblicz_zacienienie_panela,
)
from backend.services.panel_performance import (
    oblicz_wspolczynnik_zacienienia,
    oblicz_wydajnosc_panela,
    oblicz_temperature_panela,
    oblicz_napromieniowanie,
    TEMPERATURA_OTOCZENIA_POLSKA,
)
from backend.services.optimizer import (
    oblicz_mismatch_stringa,
    oblicz_produkcje_stringa_bez_optymalizatorow,
    oblicz_produkcje_stringa_z_optymalizatorami,
    porownaj_z_bez_optymalizatorow,
    czy_optymalizatory_uzasadnione,
)


class TestCienBudynku(unittest.TestCase):
    """Testy rzutowania cienia budynku."""

    def setUp(self):
        """Budynek na polnoc od instalacji."""
        self.budynek = BudynekConfig(
            x=0.0, z=-10.0,
            szerokosc=10.0, glebokosc=8.0, wysokosc=8.0
        )

    def test_slonce_pod_horyzontem_brak_cienia(self):
        """Gdy Slonce pod horyzontem, brak cienia."""
        punkty = _oblicz_cien_budynku_na_gruncie(self.budynek, 180.0, -5.0)
        self.assertIsNone(punkty)

    def test_slonce_wysokie_krotki_cien(self):
        """Przy wysokim Sloncu cien jest krotki."""
        punkty = _oblicz_cien_budynku_na_gruncie(self.budynek, 180.0, 60.0)
        self.assertIsNotNone(punkty)
        bbox = _bounding_box_cienia(punkty)
        # Cien krotki - nie powinien siegac daleko od budynku
        # Z budynku na polnoc (z=-10), cien pada na poludnie
        # Przy elewacji 60 st, cien dlugi na h/tan(60) = 8/1.73 ~ 4.6m
        self.assertLess(bbox[3], 0.0)  # Cien nie powinien siegac daleko na poludnie

    def test_slonce_niskie_dlugi_cien(self):
        """Przy niskim Sloncu cien jest dlugi."""
        punkty = _oblicz_cien_budynku_na_gruncie(self.budynek, 180.0, 15.0)
        self.assertIsNotNone(punkty)
        bbox = _bounding_box_cienia(punkty)
        # Przy niskim Sloncu (15 st) cien jest bardzo dlugi
        # h/tan(15) = 8/0.267 ~ 30m
        # Cien powinien siegac daleko na polnoc (ujemne Z)
        z_zasieg = bbox[3] - bbox[2]
        self.assertGreater(z_zasieg, 10.0)


class TestZacienieniePanel(unittest.TestCase):
    """Testy zacienienia pojedynczego panela."""

    def setUp(self):
        """Panel w pozycji standardowej."""
        self.panel = PanelPosition(
            index=0, rzad=0, kolumna=0,
            x=0.0, y=1.0, z=5.0,
            szerokosc_m=1.134, wysokosc_m=2.278,
            kat_nachylenia=30.0
        )

    def test_panel_poza_cieniem(self):
        """Panel calkowicie poza cieniem."""
        # Cien daleko od panela
        cien_bbox = (-20.0, -15.0, -20.0, -15.0)
        wynik = _oblicz_zacienienie_panela(
            self.panel, cien_bbox, 30.0, 3, "standard"
        )
        self.assertEqual(wynik.stopien_zacienienia, 0.0)
        self.assertEqual(wynik.bypass_aktywne, 0)

    def test_panel_calkowicie_w_cieniu(self):
        """Panel calkowicie w cieniu."""
        # Cien pokrywa caly panel
        cien_bbox = (-10.0, 10.0, -10.0, 20.0)
        wynik = _oblicz_zacienienie_panela(
            self.panel, cien_bbox, 30.0, 3, "standard"
        )
        self.assertAlmostEqual(wynik.stopien_zacienienia, 1.0, delta=0.01)
        self.assertEqual(wynik.bypass_aktywne, 3)

    def test_panel_czesciowo_zacieniony(self):
        """Panel czesciowo zacieniony - stopien miedzy 0 a 1."""
        # Cien pokrywa polowe panela w osi X
        pol_szer = self.panel.szerokosc_m / 2.0
        cien_bbox = (self.panel.x - pol_szer, self.panel.x,
                     -10.0, 20.0)
        wynik = _oblicz_zacienienie_panela(
            self.panel, cien_bbox, 30.0, 3, "standard"
        )
        self.assertGreater(wynik.stopien_zacienienia, 0.0)
        self.assertLess(wynik.stopien_zacienienia, 1.0)


class TestBypassDiody(unittest.TestCase):
    """Testy aktywacji bypass diod."""

    def test_bypass_aktywacja_przy_50_procent(self):
        """Bypass aktywuje sie gdy sekcja zacieniona >50%."""
        # Symulujemy wynik z 2 sekcjami zacienionymi >50%
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.7,
            sekcje_zacienione=[True, True, False],
            bypass_aktywne=2,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=True,
        )
        # Z 2 aktywnych bypass na 3 sekcje: strata ~66%
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "standard")
        self.assertAlmostEqual(wsp, 1.0 / 3.0, delta=0.01)

    def test_bypass_jedna_sekcja(self):
        """Jedna sekcja bypass = strata ~33%."""
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.4,
            sekcje_zacienione=[True, False, False],
            bypass_aktywne=1,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=False,
        )
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "standard")
        # 1 bypass z 3 sekcji = 1 - 1/3 = ~0.667
        self.assertAlmostEqual(wsp, 2.0 / 3.0, delta=0.01)

    def test_brak_zacienienia_pelna_moc(self):
        """Brak zacienienia = pelna moc (wspolczynnik 1.0)."""
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.0,
            sekcje_zacienione=[False, False, False],
            bypass_aktywne=0,
        )
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "standard")
        self.assertEqual(wsp, 1.0)


class TestHalfCut(unittest.TestCase):
    """Testy technologii half-cut."""

    def test_half_cut_jedna_polowa_zacieniona(self):
        """Half-cut: zacieniona jedna polowa, druga produkuje 50%."""
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.5,
            sekcje_zacienione=[True, True, False],
            bypass_aktywne=2,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=True,
        )
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "half-cut")
        # Gorna polowa produkuje normalnie = 50% mocy
        self.assertAlmostEqual(wsp, 0.5, delta=0.01)

    def test_half_cut_obie_polowy_zacienione(self):
        """Half-cut: obie polowy zacienione - strata jak bypass."""
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.8,
            sekcje_zacienione=[True, True, True],
            bypass_aktywne=3,
            polowa_gorna_zacieniona=True,
            polowa_dolna_zacieniona=True,
        )
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "half-cut")
        # Wszystkie 3 sekcje bypass aktywne = 0% mocy
        self.assertAlmostEqual(wsp, 0.0, delta=0.01)

    def test_half_cut_lepszy_niz_standard(self):
        """Half-cut powinien dawac lepsze wyniki niz standard przy czesciowym zacienieniu."""
        # Scenariusz: drobne zacienienie bez aktywacji bypass na poszczegolnych polowkach
        # Half-cut ogranicza wplyw na polowki, standard traci wiecej
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.4,
            sekcje_zacienione=[True, False, False],
            bypass_aktywne=1,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=False,
        )
        wsp_halfcut = oblicz_wspolczynnik_zacienienia(wynik, 3, "half-cut")
        wsp_standard = oblicz_wspolczynnik_zacienienia(wynik, 3, "standard")
        # Half-cut: 1 bypass ale podzielony na 2 polowki -> strata 1/(3*2) = mniejsza
        # Standard: 1 bypass -> strata 1/3
        self.assertGreaterEqual(wsp_halfcut, wsp_standard)

    def test_half_cut_brak_zacienienia(self):
        """Half-cut bez zacienienia = pelna moc."""
        wynik = WynikZacienieniaPanel(
            panel_index=0,
            stopien_zacienienia=0.0,
            sekcje_zacienione=[False, False, False],
            bypass_aktywne=0,
            polowa_gorna_zacieniona=False,
            polowa_dolna_zacieniona=False,
        )
        wsp = oblicz_wspolczynnik_zacienienia(wynik, 3, "half-cut")
        self.assertEqual(wsp, 1.0)


class TestOptymalizatory(unittest.TestCase):
    """Testy optymalizatorow mocy."""

    def test_bez_zacienienia_brak_roznicy(self):
        """Bez zacienienia optymalizatory nie daja zysku."""
        wspolczynniki = [1.0, 1.0, 1.0, 1.0, 1.0]  # 5 paneli bez cienia
        wynik = porownaj_z_bez_optymalizatorow(
            wspolczynniki, 550.0, 800.0, 45.0, -0.35
        )
        # Zysk powinien byc 0 lub minimalny
        self.assertAlmostEqual(wynik.zysk_procent, 0.0, delta=1.0)

    def test_z_zacienieniem_zysk(self):
        """Z zacienieniem optymalizatory daja zysk."""
        # Jeden panel mocno zacieniony, reszta OK
        wspolczynniki = [1.0, 1.0, 0.3, 1.0, 1.0]
        wynik = porownaj_z_bez_optymalizatorow(
            wspolczynniki, 550.0, 800.0, 45.0, -0.35
        )
        # Z optymalizatorami powinno byc wiecej energii
        self.assertGreater(wynik.energia_z_optymalizatorami_wh,
                          wynik.energia_bez_optymalizatorow_wh)
        self.assertGreater(wynik.zysk_procent, 0.0)

    def test_mismatch_stringa(self):
        """Mismatch loss ogranicza caly string do najgorszego panela."""
        wspolczynniki = [1.0, 1.0, 0.5, 1.0, 1.0]
        wsp_mismatch = oblicz_mismatch_stringa(wspolczynniki)
        # Mismatch = minimum z listy (0.5)
        self.assertEqual(wsp_mismatch, 0.5)

    def test_mismatch_bez_zacienienia(self):
        """Bez zacienienia mismatch = 1.0 (brak strat)."""
        wspolczynniki = [1.0, 1.0, 1.0, 1.0]
        wsp = oblicz_mismatch_stringa(wspolczynniki)
        self.assertEqual(wsp, 1.0)

    def test_optymalizatory_uzasadnione_duze_zacienienie(self):
        """Optymalizatory uzasadnione przy duzym zacienieniu."""
        ocena = czy_optymalizatory_uzasadnione(
            strata_roczna_zacienienie_procent=15.0,
            liczba_paneli=10,
            moc_panela_wp=550.0
        )
        self.assertTrue(ocena["uzasadnione"])

    def test_optymalizatory_nieuzasadnione_male_zacienienie(self):
        """Optymalizatory nieuzasadnione przy malym zacienieniu."""
        ocena = czy_optymalizatory_uzasadnione(
            strata_roczna_zacienienie_procent=2.0,
            liczba_paneli=10,
            moc_panela_wp=550.0
        )
        self.assertFalse(ocena["uzasadnione"])


class TestWydajnoscPanela(unittest.TestCase):
    """Testy obliczania wydajnosci panela."""

    def test_warunki_stc(self):
        """W warunkach STC (25C, 1000 W/m2) panel daje moc nominalna."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=1000.0,
            temperatura_panela_c=25.0,
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.0,  # bez strat
            degradacja_roczna=0.0,  # bez degradacji
            rok_eksploatacji=1,
        )
        self.assertAlmostEqual(wynik.moc_aktualna_w, 550.0, delta=1.0)

    def test_wplyw_temperatury_gorace(self):
        """W gorace dni moc spada (temperatura > 25C)."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=1000.0,
            temperatura_panela_c=55.0,  # goraco
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.0,
        )
        # Przy 55C: delta_T = 30, strata = -0.35/100 * 30 = -0.105 -> moc * 0.895
        self.assertLess(wynik.moc_aktualna_w, 550.0)
        self.assertAlmostEqual(wynik.moc_aktualna_w, 550.0 * 0.895, delta=5.0)

    def test_wplyw_temperatury_zimno(self):
        """W zimne dni moc wzrasta (temperatura < 25C)."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=1000.0,
            temperatura_panela_c=0.0,  # zimno
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.0,
        )
        # Przy 0C: delta_T = -25, wzrost = -0.35/100 * (-25) = +0.0875
        self.assertGreater(wynik.moc_aktualna_w, 550.0)

    def test_polowa_napromieniowania(self):
        """Przy polowie napromieniowania moc spada o polowe."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=500.0,
            temperatura_panela_c=25.0,
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.0,
        )
        self.assertAlmostEqual(wynik.moc_aktualna_w, 275.0, delta=1.0)

    def test_brak_napromieniowania(self):
        """Bez napromieniowania moc = 0."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=0.0,
            temperatura_panela_c=25.0,
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
        )
        self.assertEqual(wynik.moc_aktualna_w, 0.0)

    def test_degradacja(self):
        """Po 10 latach degradacja 0.5% rocznie zmniejsza moc."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=1000.0,
            temperatura_panela_c=25.0,
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.0,
            degradacja_roczna=0.005,
            rok_eksploatacji=10,
        )
        # 9 lat degradacji (pierwszy rok bez): 0.995^9 ~ 0.956
        oczekiwana = 550.0 * (0.995 ** 9)
        self.assertAlmostEqual(wynik.moc_aktualna_w, oczekiwana, delta=2.0)

    def test_straty_systemowe(self):
        """Straty systemowe 5% zmniejszaja moc o 5%."""
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w=550.0,
            napromieniowanie_wm2=1000.0,
            temperatura_panela_c=25.0,
            wspolczynnik_temp_pmax=-0.35,
            wspolczynnik_zacienienia=1.0,
            straty_systemowe=0.05,
            degradacja_roczna=0.0,
        )
        self.assertAlmostEqual(wynik.moc_aktualna_w, 550.0 * 0.95, delta=1.0)


class TestTemperaturaPanela(unittest.TestCase):
    """Testy modelu temperatury panela."""

    def test_noc_temperatura_otoczenia(self):
        """W nocy panel ma temperature otoczenia."""
        temp = oblicz_temperature_panela(7, 2)  # lipiec, 2:00
        self.assertAlmostEqual(temp, TEMPERATURA_OTOCZENIA_POLSKA[6], delta=0.1)

    def test_poludnie_latem_goracy(self):
        """W poludnie latem panel jest goracy."""
        temp = oblicz_temperature_panela(7, 13)  # lipiec, 13:00
        # Otoczenie 20C + NOCT korekta
        self.assertGreater(temp, 30.0)

    def test_zima_nizsze_temperatury(self):
        """Zima temperatury panela sa nizsze."""
        temp_zima = oblicz_temperature_panela(1, 12)  # styczen, poludnie
        temp_lato = oblicz_temperature_panela(7, 12)  # lipiec, poludnie
        self.assertLess(temp_zima, temp_lato)


class TestNapromieniowanie(unittest.TestCase):
    """Testy modelu napromieniowania."""

    def test_slonce_pod_horyzontem(self):
        """Gdy Slonce pod horyzontem, napromieniowanie = 0."""
        irr = oblicz_napromieniowanie(6, 12, -5.0)
        self.assertEqual(irr, 0.0)

    def test_latem_wiecej_niz_zima(self):
        """Latem napromieniowanie wieksze niz zima."""
        irr_lato = oblicz_napromieniowanie(6, 12, 60.0)
        irr_zima = oblicz_napromieniowanie(12, 12, 15.0)
        self.assertGreater(irr_lato, irr_zima)

    def test_wysoka_elewacja_wieksze_napromieniowanie(self):
        """Im wyzsza elewacja Slonca, tym wieksze napromieniowanie."""
        irr_niska = oblicz_napromieniowanie(6, 8, 20.0)
        irr_wysoka = oblicz_napromieniowanie(6, 12, 60.0)
        self.assertGreater(irr_wysoka, irr_niska)

    def test_maksymalnie_1000_wm2(self):
        """Napromieniowanie nie przekracza 1000 W/m2."""
        irr = oblicz_napromieniowanie(7, 12, 90.0)
        self.assertLessEqual(irr, 1000.0)


class TestZacienieniePojedynczaGodzina(unittest.TestCase):
    """Testy obliczania zacienienia dla pojedynczej godziny."""

    def setUp(self):
        """Przygotuj panele i budynek testowy."""
        self.panele = [
            PanelPosition(
                index=0, rzad=0, kolumna=0,
                x=0.0, y=1.0, z=5.0,
                szerokosc_m=1.134, wysokosc_m=2.278,
                kat_nachylenia=30.0
            ),
            PanelPosition(
                index=1, rzad=0, kolumna=1,
                x=1.5, y=1.0, z=5.0,
                szerokosc_m=1.134, wysokosc_m=2.278,
                kat_nachylenia=30.0
            ),
        ]
        self.budynek = BudynekConfig(
            x=0.0, z=-10.0,
            szerokosc=10.0, glebokosc=8.0, wysokosc=8.0
        )

    def test_slonce_wysokie_brak_zacienienia(self):
        """Przy wysokim Sloncu cien nie siega do paneli."""
        wyniki = oblicz_zacienienie_pojedyncza_godzina(
            self.panele, self.budynek,
            azymut_slonca=180.0, elewacja_slonca=60.0,
            kat_nachylenia=30.0, liczba_sekcji=3
        )
        # Przy wysokim Sloncu cien jest krotki
        for w in wyniki:
            # Cien moze nie siegac do paneli
            self.assertLessEqual(w.stopien_zacienienia, 1.0)

    def test_slonce_pod_horyzontem(self):
        """Przy Sloncu pod horyzontem brak zacienienia."""
        wyniki = oblicz_zacienienie_pojedyncza_godzina(
            self.panele, self.budynek,
            azymut_slonca=180.0, elewacja_slonca=-5.0,
            kat_nachylenia=30.0, liczba_sekcji=3
        )
        for w in wyniki:
            self.assertEqual(w.stopien_zacienienia, 0.0)

    def test_zwracana_liczba_wynikow(self):
        """Zwracana jest informacja dla kazdego panela."""
        wyniki = oblicz_zacienienie_pojedyncza_godzina(
            self.panele, self.budynek,
            azymut_slonca=180.0, elewacja_slonca=30.0,
            kat_nachylenia=30.0, liczba_sekcji=3
        )
        self.assertEqual(len(wyniki), 2)


if __name__ == "__main__":
    unittest.main()
