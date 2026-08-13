"""
Testy jednostkowe dla endpointu POST /api/shading/single-hour.

Testuje handle_shading_single_hour() - podglad zacienienia dla jednej godziny.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.handlers import handle_shading_single_hour


class TestShadingSingleHourValidation(unittest.TestCase):
    """Testy walidacji danych wejsciowych."""

    def test_brak_body_zwraca_400(self):
        """Brak body -> 400."""
        status, resp = handle_shading_single_hour(None)
        self.assertEqual(status, 400)
        self.assertIn("error", resp)

    def test_pusty_body_zwraca_400(self):
        """Pusty body -> 400."""
        status, resp = handle_shading_single_hour(b"")
        self.assertEqual(status, 400)

    def test_nieprawidlowy_json_zwraca_400(self):
        """Nieprawidlowy JSON -> 400."""
        status, resp = handle_shading_single_hour(b"not json")
        self.assertEqual(status, 400)
        self.assertIn("JSON", resp["message"])

    def test_brak_pola_data_zwraca_400(self):
        """Brak pola 'data' -> 400."""
        body = json.dumps({
            "godzina": 12,
            "instalacja": {"panel_id": "x", "liczba_paneli": 2},
            "lokalizacja": {"szerokosc_geo": 52.0, "dlugosc_geo": 21.0},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)
        self.assertIn("data", resp["message"])

    def test_brak_pola_godzina_zwraca_400(self):
        """Brak pola 'godzina' -> 400."""
        body = json.dumps({
            "data": "2025-06-15",
            "instalacja": {"panel_id": "x", "liczba_paneli": 2},
            "lokalizacja": {"szerokosc_geo": 52.0, "dlugosc_geo": 21.0},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)
        self.assertIn("godzina", resp["message"])

    def test_brak_instalacji_zwraca_400(self):
        """Brak sekcji 'instalacja' -> 400."""
        body = json.dumps({
            "data": "2025-06-15",
            "godzina": 12,
            "lokalizacja": {"szerokosc_geo": 52.0, "dlugosc_geo": 21.0},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)
        self.assertIn("instalacja", resp["message"])

    def test_brak_lokalizacji_zwraca_400(self):
        """Brak sekcji 'lokalizacja' -> 400."""
        body = json.dumps({
            "data": "2025-06-15",
            "godzina": 12,
            "instalacja": {"panel_id": "x", "liczba_paneli": 2},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)
        self.assertIn("lokalizacja", resp["message"])

    def test_godzina_poza_zakresem_zwraca_400(self):
        """Godzina > 23 -> 400."""
        body = json.dumps({
            "data": "2025-06-15",
            "godzina": 25,
            "instalacja": {"panel_id": "x", "liczba_paneli": 2},
            "lokalizacja": {"szerokosc_geo": 52.0, "dlugosc_geo": 21.0},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)

    def test_nieprawidlowy_format_daty_zwraca_400(self):
        """Nieprawidlowy format daty -> 400."""
        body = json.dumps({
            "data": "15-06-2025",
            "godzina": 12,
            "instalacja": {"panel_id": "x", "liczba_paneli": 2},
            "lokalizacja": {"szerokosc_geo": 52.0, "dlugosc_geo": 21.0},
        }).encode()
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 400)


class TestShadingSingleHourNoc(unittest.TestCase):
    """Testy nocnej godziny (elewacja < 0)."""

    def _make_body(self, godzina=2):
        return json.dumps({
            "data": "2025-06-15",
            "godzina": godzina,
            "instalacja": {
                "panel_id": "ja_solar_jam72s30_550mr",
                "liczba_paneli": 4,
                "liczba_rzedow": 2,
                "kat_nachylenia": 30,
                "azymut": 0,
                "orientacja": "pion",
                "przeswit_nad_gruntem_cm": 50,
                "odstep_boczny_cm": 3,
            },
            "budynek": {
                "x": 0, "z": -10,
                "szerokosc": 10, "glebokosc": 8, "wysokosc": 8,
            },
            "lokalizacja": {"szerokosc_geo": 52.23, "dlugosc_geo": 21.01},
        }).encode()

    def test_noc_zwraca_200_z_flaga_noc(self):
        """Godzina 2 w nocy -> noc=True, produkcja=0."""
        body = self._make_body(godzina=2)
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 200)
        self.assertTrue(resp["noc"])
        self.assertEqual(resp["podsumowanie"]["produkcja_wh"], 0.0)
        self.assertEqual(resp["podsumowanie"]["produkcja_bez_cienia_wh"], 0.0)
        self.assertEqual(len(resp["panele"]), 4)


class TestShadingSingleHourDzien(unittest.TestCase):
    """Testy dziennej godziny (z danymi TMY zmockowanymi)."""

    def _make_body(self, godzina=12):
        return json.dumps({
            "data": "2025-06-15",
            "godzina": godzina,
            "instalacja": {
                "panel_id": "ja_solar_jam72s30_550mr",
                "liczba_paneli": 4,
                "liczba_rzedow": 2,
                "kat_nachylenia": 30,
                "azymut": 0,
                "orientacja": "pion",
                "przeswit_nad_gruntem_cm": 50,
                "odstep_boczny_cm": 3,
            },
            "budynek": {
                "x": 0, "z": -10,
                "szerokosc": 10, "glebokosc": 8, "wysokosc": 8,
            },
            "lokalizacja": {"szerokosc_geo": 52.23, "dlugosc_geo": 21.01},
        }).encode()

    @patch('backend.api.handlers.pobierz_dane_tmy')
    def test_dzien_z_tmy_zwraca_200(self, mock_tmy):
        """Godzina 12 z danymi TMY -> zwraca poprawna strukture."""
        # Przygotuj mock TMY (8760 godzin)
        mock_tmy.return_value = {
            "ghi": [500.0] * 8760,
            "dni": [300.0] * 8760,
            "dhi": [200.0] * 8760,
            "temperatura": [20.0] * 8760,
            "roczne_ghi_kwh_m2": 1100.0,
        }
        body = self._make_body(godzina=12)
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 200)
        self.assertFalse(resp["noc"])
        self.assertIn("pozycja_slonca", resp)
        self.assertIn("azymut", resp["pozycja_slonca"])
        self.assertIn("elewacja", resp["pozycja_slonca"])
        self.assertIn("panele", resp)
        self.assertEqual(len(resp["panele"]), 4)
        self.assertIn("podsumowanie", resp)
        self.assertIn("produkcja_wh", resp["podsumowanie"])
        self.assertIn("produkcja_bez_cienia_wh", resp["podsumowanie"])
        self.assertIn("strata_procent", resp["podsumowanie"])

    @patch('backend.api.handlers.pobierz_dane_tmy')
    def test_panele_maja_wymagane_pola(self, mock_tmy):
        """Kazdy panel w odpowiedzi ma wymagane pola."""
        mock_tmy.return_value = {
            "ghi": [500.0] * 8760,
            "dni": [300.0] * 8760,
            "dhi": [200.0] * 8760,
            "temperatura": [20.0] * 8760,
            "roczne_ghi_kwh_m2": 1100.0,
        }
        body = self._make_body(godzina=12)
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 200)
        for panel in resp["panele"]:
            self.assertIn("index", panel)
            self.assertIn("stopien_zacienienia", panel)
            self.assertIn("sekcje_zacienione", panel)
            self.assertIn("bypass_aktywne", panel)
            self.assertIn("produkcja_wh", panel)
            self.assertIn("produkcja_bez_cienia_wh", panel)

    @patch('backend.api.handlers.pobierz_dane_tmy')
    def test_bez_danych_tmy_zwraca_200(self, mock_tmy):
        """Brak danych TMY -> uzywamy fallback, dalej 200."""
        mock_tmy.return_value = None
        body = self._make_body(godzina=12)
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 200)
        self.assertFalse(resp["noc"])
        # Bez danych TMY ghi/dni/dhi = 0, wiec produkcja = 0
        self.assertEqual(resp["podsumowanie"]["produkcja_wh"], 0.0)

    @patch('backend.api.handlers.pobierz_dane_tmy')
    def test_pozycja_slonca_poprawna(self, mock_tmy):
        """Azymut i elewacja w rozsadnym zakresie dla poludnia w czerwcu."""
        mock_tmy.return_value = {
            "ghi": [500.0] * 8760,
            "dni": [300.0] * 8760,
            "dhi": [200.0] * 8760,
            "temperatura": [20.0] * 8760,
            "roczne_ghi_kwh_m2": 1100.0,
        }
        body = self._make_body(godzina=12)
        status, resp = handle_shading_single_hour(body)
        self.assertEqual(status, 200)
        pos = resp["pozycja_slonca"]
        # W czerwcu o 12:00 w Warszawie elewacja > 50 stopni
        self.assertGreater(pos["elewacja"], 40)
        # Azymut blisko poludnia (180 +/- 30)
        self.assertGreater(pos["azymut"], 140)
        self.assertLess(pos["azymut"], 220)


if __name__ == "__main__":
    unittest.main()
