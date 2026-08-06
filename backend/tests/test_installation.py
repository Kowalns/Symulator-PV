"""
Testy modulu konfiguracji i rozmieszczenia instalacji PV.

Testuje:
- Walidacje konfiguracji (zakresy, limity mocy)
- Obliczenia rozmieszczenia paneli
- Poprawnosc pozycji paneli w 3D
- Wczytywanie baz danych urzadzen
- Handler API /api/installation/configure
"""

import json
import math
import unittest
from unittest.mock import patch

from backend.models.installation import (
    InstallationConfig,
    PanelPosition,
    InstallationLayout,
)
from backend.services.installation_layout import (
    wczytaj_baze_paneli,
    wczytaj_baze_falownikow,
    wczytaj_baze_baterii,
    znajdz_panel,
    waliduj_konfiguracje,
    oblicz_wymiary_panela_w_orientacji,
    oblicz_rozmieszczenie,
    MIN_MOC_KWP,
    MAX_MOC_KWP,
)
from backend.api.handlers import (
    handle_get_panels,
    handle_get_inverters,
    handle_get_batteries,
    handle_installation_configure,
)


class TestBazyDanych(unittest.TestCase):
    """Testy wczytywania baz danych urzadzen."""

    def test_wczytaj_baze_paneli_niepusta(self):
        """Baza paneli powinna zawierac co najmniej 10 modeli."""
        panele = wczytaj_baze_paneli()
        self.assertGreaterEqual(len(panele), 10)

    def test_panel_ma_wymagane_pola(self):
        """Kazdy panel w bazie powinien miec wszystkie wymagane pola."""
        wymagane_pola = [
            "id", "producent", "model", "moc_wp", "wymiary_mm",
            "wydajnosc_procent", "wspolczynnik_temp_pmax", "technologia",
            "liczba_sekcji_bypass", "napiecie_mpp", "prad_mpp",
            "napiecie_oc", "prad_sc", "degradacja_roczna_procent",
            "waga_kg", "gwarancja_lata",
        ]
        panele = wczytaj_baze_paneli()
        for panel in panele:
            for pole in wymagane_pola:
                self.assertIn(pole, panel, f"Panel {panel.get('id', '?')} nie ma pola '{pole}'")

    def test_panel_wymiary_maja_szerokosc_i_wysokosc(self):
        """Wymiary panela powinny miec szerokosc i wysokosc."""
        panele = wczytaj_baze_paneli()
        for panel in panele:
            self.assertIn("szerokosc", panel["wymiary_mm"])
            self.assertIn("wysokosc", panel["wymiary_mm"])
            self.assertGreater(panel["wymiary_mm"]["szerokosc"], 0)
            self.assertGreater(panel["wymiary_mm"]["wysokosc"], 0)

    def test_wczytaj_baze_falownikow_niepusta(self):
        """Baza falownikow powinna zawierac co najmniej 5 modeli."""
        falowniki = wczytaj_baze_falownikow()
        self.assertGreaterEqual(len(falowniki), 5)

    def test_falownik_ma_wymagane_pola(self):
        """Kazdy falownik powinien miec wymagane pola."""
        wymagane_pola = [
            "id", "producent", "model", "moc_max_dc", "moc_wyjsciowa_ac",
            "zakres_mppt_v", "liczba_mppt", "max_prad_wejsciowy",
            "sprawnosc_procent", "czy_optymalizatory",
        ]
        falowniki = wczytaj_baze_falownikow()
        for falownik in falowniki:
            for pole in wymagane_pola:
                self.assertIn(pole, falownik, f"Falownik {falownik.get('id', '?')} nie ma pola '{pole}'")

    def test_wczytaj_baze_baterii_niepusta(self):
        """Baza baterii powinna zawierac co najmniej 5 modeli."""
        baterie = wczytaj_baze_baterii()
        self.assertGreaterEqual(len(baterie), 5)

    def test_bateria_ma_wymagane_pola(self):
        """Kazda bateria powinna miec wymagane pola."""
        wymagane_pola = [
            "id", "producent", "model", "pojemnosc_kwh",
            "moc_ladowania_kw", "moc_rozladowania_kw",
            "cykle_zycia", "dod_procent", "sprawnosc_roundtrip_procent",
        ]
        baterie = wczytaj_baze_baterii()
        for bateria in baterie:
            for pole in wymagane_pola:
                self.assertIn(pole, bateria, f"Bateria {bateria.get('id', '?')} nie ma pola '{pole}'")


class TestZnajdzPanel(unittest.TestCase):
    """Testy wyszukiwania paneli w bazie."""

    def test_znajdz_istniejacy_panel(self):
        """Szukanie panela ktory istnieje w bazie powinno zwrocic jego dane."""
        panel = znajdz_panel("ja_solar_jam72s30_550mr")
        self.assertIsNotNone(panel)
        self.assertEqual(panel["producent"], "JA Solar")
        self.assertEqual(panel["moc_wp"], 550)

    def test_znajdz_nieistniejacy_panel(self):
        """Szukanie panela ktory nie istnieje powinno zwrocic None."""
        panel = znajdz_panel("nieistniejacy_panel_xyz")
        self.assertIsNone(panel)


class TestWalidacjaKonfiguracji(unittest.TestCase):
    """Testy walidacji konfiguracji instalacji."""

    def _bazowa_konfiguracja(self) -> InstallationConfig:
        """Tworzy poprawna konfiguracje bazowa do testow."""
        return InstallationConfig(
            panel_id="ja_solar_jam72s30_550mr",
            orientacja="pion",
            kat_nachylenia=30.0,
            azymut=0.0,
            przeswit_nad_gruntem_cm=50.0,
            odstep_boczny_cm=3.0,
            liczba_paneli=10,
        )

    def test_poprawna_konfiguracja(self):
        """Poprawna konfiguracja nie powinna zwracac bledu."""
        config = self._bazowa_konfiguracja()
        blad = waliduj_konfiguracje(config)
        self.assertIsNone(blad)

    def test_niepoprawna_orientacja(self):
        """Niepoprawna orientacja powinna zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.orientacja = "ukos"
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Orientacja", blad)

    def test_kat_za_maly(self):
        """Kat mniejszy niz 15 powinien zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.kat_nachylenia = 10.0
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Kat nachylenia", blad)

    def test_kat_za_duzy(self):
        """Kat wiekszy niz 60 powinien zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.kat_nachylenia = 70.0
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Kat nachylenia", blad)

    def test_przeswit_za_maly(self):
        """Przeswit mniejszy niz 20cm powinien zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.przeswit_nad_gruntem_cm = 10.0
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Przeswit", blad)

    def test_przeswit_za_duzy(self):
        """Przeswit wiekszy niz 100cm powinien zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.przeswit_nad_gruntem_cm = 150.0
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Przeswit", blad)

    def test_odstep_boczny_za_maly(self):
        """Odstep boczny mniejszy niz 2cm powinien zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.odstep_boczny_cm = 1.0
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Odstep boczny", blad)

    def test_nieistniejacy_panel(self):
        """Konfiguracja z nieistniejacym panelem powinna zwrocic blad."""
        config = self._bazowa_konfiguracja()
        config.panel_id = "fałszywy_panel_123"
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("Nie znaleziono", blad)

    def test_moc_ponizej_minimum(self):
        """Instalacja ponizej 2kWp powinna zwrocic blad."""
        config = self._bazowa_konfiguracja()
        # 550W * 3 = 1.65 kWp < 2 kWp
        config.liczba_paneli = 3
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("ponizej minimum", blad)

    def test_moc_powyzej_maximum(self):
        """Instalacja powyzej 14kWp powinna zwrocic blad."""
        config = self._bazowa_konfiguracja()
        # 550W * 26 = 14.3 kWp > 14 kWp
        config.liczba_paneli = 26
        blad = waliduj_konfiguracje(config)
        self.assertIsNotNone(blad)
        self.assertIn("przekracza maksimum", blad)


class TestWymiaryPanela(unittest.TestCase):
    """Testy obliczania wymiarow panela w danej orientacji."""

    def setUp(self):
        """Przygotowanie danych testowych."""
        self.panel = {
            "wymiary_mm": {"szerokosc": 1134, "wysokosc": 2278}
        }

    def test_orientacja_pion(self):
        """W orientacji pion: szerokosc=1134mm, wysokosc=2278mm."""
        szer, wys = oblicz_wymiary_panela_w_orientacji(self.panel, "pion")
        self.assertAlmostEqual(szer, 1.134, places=3)
        self.assertAlmostEqual(wys, 2.278, places=3)

    def test_orientacja_poziom(self):
        """W orientacji poziom: szerokosc=2278mm, wysokosc=1134mm."""
        szer, wys = oblicz_wymiary_panela_w_orientacji(self.panel, "poziom")
        self.assertAlmostEqual(szer, 2.278, places=3)
        self.assertAlmostEqual(wys, 1.134, places=3)


class TestObliczRozmieszczenie(unittest.TestCase):
    """Testy obliczania rozmieszczenia paneli na stelazu."""

    def _bazowa_konfiguracja(self) -> InstallationConfig:
        """Tworzy poprawna konfiguracje bazowa."""
        return InstallationConfig(
            panel_id="ja_solar_jam72s30_550mr",
            orientacja="pion",
            kat_nachylenia=30.0,
            azymut=0.0,
            przeswit_nad_gruntem_cm=50.0,
            odstep_boczny_cm=3.0,
            liczba_paneli=10,
        )

    def test_liczba_paneli_w_wyniku(self):
        """Wynik powinien zawierac dokladna liczbe paneli."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        self.assertEqual(len(layout.panele), 10)
        self.assertEqual(layout.liczba_paneli, 10)

    def test_moc_calkowita(self):
        """Moc calkowita powinna byc poprawnie obliczona."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        # 10 paneli * 550W = 5500W = 5.5 kWp
        self.assertAlmostEqual(layout.moc_calkowita_kwp, 5.5, places=2)

    def test_pozycje_y_nad_gruntem(self):
        """Wszystkie panele powinny byc nad gruntem (y > 0)."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        for panel in layout.panele:
            self.assertGreater(panel.y, 0)

    def test_przeswit_poprawny(self):
        """Dolna krawedz panela powinna byc na wysokosci przeswitu."""
        config = self._bazowa_konfiguracja()
        config.kat_nachylenia = 30.0
        config.przeswit_nad_gruntem_cm = 50.0
        layout = oblicz_rozmieszczenie(config)

        # Dla panela o wys 2.278m nachylonego pod 30 st:
        # y_srodek = 0.5 + (2.278 * sin(30)) / 2 = 0.5 + 0.5695 = 1.0695
        # dolna krawedz = y_srodek - (wys * sin(kat)) / 2 = 1.0695 - 0.5695 = 0.5
        panel = layout.panele[0]
        wys_panela = panel.wysokosc_m
        kat_rad = math.radians(30.0)
        dolna_krawedz = panel.y - (wys_panela * math.sin(kat_rad)) / 2.0
        self.assertAlmostEqual(dolna_krawedz, 0.5, places=2)

    def test_kolumny_nie_nakladaja_sie(self):
        """Panele w rzedzie nie powinny nakladac sie na osi X."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)

        # Wszystkie panele sa w jednym rzedzie
        panele_posortowane = sorted(layout.panele, key=lambda p: p.x)

        for i in range(len(panele_posortowane) - 1):
            p1 = panele_posortowane[i]
            p2 = panele_posortowane[i + 1]
            # Prawa krawedz p1 powinna byc mniejsza niz lewa krawedz p2
            prawa_p1 = p1.x + p1.szerokosc_m / 2.0
            lewa_p2 = p2.x - p2.szerokosc_m / 2.0
            self.assertLess(prawa_p1, lewa_p2 + 0.001)

    def test_wszystkie_panele_w_jednym_rzedzie(self):
        """Wszystkie panele powinny miec rzad=0 (jedna tafla)."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        for panel in layout.panele:
            self.assertEqual(panel.rzad, 0)

    def test_orientacja_poziom_zmienia_wymiary(self):
        """W orientacji poziom panele powinny byc szersze i nizsze."""
        config_pion = self._bazowa_konfiguracja()
        config_pion.orientacja = "pion"
        layout_pion = oblicz_rozmieszczenie(config_pion)

        config_poziom = self._bazowa_konfiguracja()
        config_poziom.orientacja = "poziom"
        layout_poziom = oblicz_rozmieszczenie(config_poziom)

        p_pion = layout_pion.panele[0]
        p_poziom = layout_poziom.panele[0]

        # Pion: szerokosc < wysokosc
        self.assertLess(p_pion.szerokosc_m, p_pion.wysokosc_m)
        # Poziom: szerokosc > wysokosc
        self.assertGreater(p_poziom.szerokosc_m, p_poziom.wysokosc_m)

    def test_wymiary_instalacji_dodatnie(self):
        """Wymiary instalacji powinny byc wieksze od zera."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        self.assertGreater(layout.wymiary_instalacji_m["szerokosc"], 0)
        self.assertGreater(layout.wymiary_instalacji_m["glebokosc"], 0)
        self.assertGreater(layout.wymiary_instalacji_m["wysokosc"], 0)

    def test_to_dict_serializacja(self):
        """Wynik powinien byc serializowalny do JSON."""
        config = self._bazowa_konfiguracja()
        layout = oblicz_rozmieszczenie(config)
        wynik = layout.to_dict()
        # Powinno byc serializowalne do JSON bez bledow
        json_str = json.dumps(wynik, ensure_ascii=False)
        self.assertIn("panele", json_str)
        self.assertIn("moc_calkowita_kwp", json_str)

    def test_nieistniejacy_panel_wyrzuca_wyjatek(self):
        """Uzycie nieistniejacego panela powinno wyrzucic wyjatek."""
        config = self._bazowa_konfiguracja()
        config.panel_id = "nie_istnieje"
        with self.assertRaises(ValueError):
            oblicz_rozmieszczenie(config)


class TestHandleryAPI(unittest.TestCase):
    """Testy handlerow API dla instalacji."""

    def test_handle_get_panels(self):
        """GET /api/panels powinien zwrocic 200 i liste paneli."""
        status, resp = handle_get_panels()
        self.assertEqual(status, 200)
        self.assertIn("panele", resp)
        self.assertIn("liczba", resp)
        self.assertGreaterEqual(resp["liczba"], 10)

    def test_handle_get_inverters(self):
        """GET /api/inverters powinien zwrocic 200 i liste falownikow."""
        status, resp = handle_get_inverters()
        self.assertEqual(status, 200)
        self.assertIn("falowniki", resp)
        self.assertIn("liczba", resp)
        self.assertGreaterEqual(resp["liczba"], 5)

    def test_handle_get_batteries(self):
        """GET /api/batteries powinien zwrocic 200 i liste baterii."""
        status, resp = handle_get_batteries()
        self.assertEqual(status, 200)
        self.assertIn("baterie", resp)
        self.assertIn("liczba", resp)
        self.assertGreaterEqual(resp["liczba"], 5)

    def test_handle_installation_configure_poprawne_dane(self):
        """POST /api/installation/configure z poprawnymi danymi."""
        dane = json.dumps({
            "panel_id": "ja_solar_jam72s30_550mr",
            "orientacja": "pion",
            "kat_nachylenia": 30,
            "przeswit_nad_gruntem_cm": 50,
            "odstep_boczny_cm": 3,
            "liczba_paneli": 10,
        }).encode("utf-8")

        status, resp = handle_installation_configure(dane)
        self.assertEqual(status, 200)
        self.assertIn("panele", resp)
        self.assertIn("moc_calkowita_kwp", resp)
        self.assertEqual(len(resp["panele"]), 10)

    def test_handle_installation_configure_brak_danych(self):
        """POST /api/installation/configure bez danych powinien zwrocic 400."""
        status, resp = handle_installation_configure(None)
        self.assertEqual(status, 400)
        self.assertIn("error", resp)

    def test_handle_installation_configure_niepoprawny_json(self):
        """POST /api/installation/configure z niepoprawnym JSON powinien zwrocic 400."""
        status, resp = handle_installation_configure(b"nie-json")
        self.assertEqual(status, 400)
        self.assertIn("error", resp)

    def test_handle_installation_configure_brak_panel_id(self):
        """POST bez panel_id powinien zwrocic 400."""
        dane = json.dumps({
            "orientacja": "pion",
            "liczba_paneli": 10,
        }).encode("utf-8")
        status, resp = handle_installation_configure(dane)
        self.assertEqual(status, 400)

    def test_handle_installation_configure_za_mala_moc(self):
        """POST z za mala moca instalacji powinien zwrocic 400."""
        dane = json.dumps({
            "panel_id": "ja_solar_jam72s30_550mr",
            "liczba_paneli": 2,
        }).encode("utf-8")
        status, resp = handle_installation_configure(dane)
        self.assertEqual(status, 400)
        self.assertIn("ponizej minimum", resp["message"])


if __name__ == "__main__":
    unittest.main()
