"""
Testy jednostkowe dla modulu handlers.py

Testy sprawdzaja czy endpointy API dzialaja poprawnie:
- czy poprawne zapytania zwracaja poprawne odpowiedzi
- czy bledne dane sa odrzucane z odpowiednim komunikatem
- czy health endpoint dziala
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Dodanie sciezki projektu zeby importy dzialaly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.api.handlers import handle_health, handle_simulate, _validate_input


class TestHealthEndpoint(unittest.TestCase):
    """Testy dla endpointu /api/health."""

    def test_health_returns_200(self):
        """Sprawdza czy health endpoint zwraca kod 200 (ok)."""
        status_code, response = handle_health()
        self.assertEqual(status_code, 200)

    def test_health_returns_ok_status(self):
        """Sprawdza czy odpowiedz zawiera status 'ok'."""
        status_code, response = handle_health()
        self.assertEqual(response["status"], "ok")

    def test_health_has_message(self):
        """Sprawdza czy odpowiedz zawiera komunikat."""
        status_code, response = handle_health()
        self.assertIn("message", response)


class TestSimulateEndpoint(unittest.TestCase):
    """Testy dla endpointu /api/simulate."""

    @patch('backend.services.calculator.get_pv_estimation')
    def test_valid_request_returns_200(self, mock_pvgis):
        """Sprawdza czy poprawne zapytanie zwraca kod 200."""
        mock_pvgis.return_value = None  # Wymuszamy fallback

        body = json.dumps({
            "latitude": 52.23,
            "longitude": 21.01,
            "peak_power_kw": 5.0,
        }).encode("utf-8")

        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 200)

    @patch('backend.services.calculator.get_pv_estimation')
    def test_valid_request_returns_annual_energy(self, mock_pvgis):
        """Sprawdza czy odpowiedz zawiera roczna energie."""
        mock_pvgis.return_value = None

        body = json.dumps({
            "latitude": 52.23,
            "longitude": 21.01,
            "peak_power_kw": 5.0,
        }).encode("utf-8")

        status_code, response = handle_simulate(body)
        self.assertIn("annual_energy_kwh", response)
        self.assertGreater(response["annual_energy_kwh"], 0)

    @patch('backend.services.calculator.get_pv_estimation')
    def test_valid_request_returns_monthly_data(self, mock_pvgis):
        """Sprawdza czy odpowiedz zawiera 12 miesiecy."""
        mock_pvgis.return_value = None

        body = json.dumps({
            "latitude": 52.23,
            "longitude": 21.01,
        }).encode("utf-8")

        status_code, response = handle_simulate(body)
        self.assertIn("monthly_energy_kwh", response)
        self.assertEqual(len(response["monthly_energy_kwh"]), 12)

    def test_empty_body_returns_400(self):
        """Sprawdza czy brak danych zwraca blad 400."""
        status_code, response = handle_simulate(None)
        self.assertEqual(status_code, 400)

    def test_invalid_json_returns_400(self):
        """Sprawdza czy niepoprawny JSON zwraca blad 400."""
        body = b"to nie jest json"
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    def test_missing_latitude_returns_400(self):
        """Sprawdza czy brak szerokosci geogr. zwraca blad 400."""
        body = json.dumps({"longitude": 21.01}).encode("utf-8")
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    def test_missing_longitude_returns_400(self):
        """Sprawdza czy brak dlugosci geogr. zwraca blad 400."""
        body = json.dumps({"latitude": 52.23}).encode("utf-8")
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    def test_invalid_latitude_range_returns_400(self):
        """Sprawdza czy szerokosc poza zakresem zwraca blad 400."""
        body = json.dumps({
            "latitude": 100.0,  # Niepoprawne - max 90
            "longitude": 21.01,
        }).encode("utf-8")
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    def test_invalid_longitude_range_returns_400(self):
        """Sprawdza czy dlugosc poza zakresem zwraca blad 400."""
        body = json.dumps({
            "latitude": 52.23,
            "longitude": 200.0,  # Niepoprawne - max 180
        }).encode("utf-8")
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    def test_negative_power_returns_400(self):
        """Sprawdza czy ujemna moc zwraca blad 400."""
        body = json.dumps({
            "latitude": 52.23,
            "longitude": 21.01,
            "peak_power_kw": -5.0,
        }).encode("utf-8")
        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 400)

    @patch('backend.services.calculator.get_pv_estimation')
    def test_minimal_valid_request(self, mock_pvgis):
        """Sprawdza czy minimalne poprawne zapytanie (tylko lat/lon) dziala."""
        mock_pvgis.return_value = None

        body = json.dumps({
            "latitude": 50.0,
            "longitude": 20.0,
        }).encode("utf-8")

        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 200)

    @patch('backend.services.calculator.get_pv_estimation')
    def test_all_optional_fields(self, mock_pvgis):
        """Sprawdza czy wszystkie opcjonalne pola sa obslugiwane."""
        mock_pvgis.return_value = None

        body = json.dumps({
            "latitude": 52.23,
            "longitude": 21.01,
            "peak_power_kw": 8.0,
            "system_loss_percent": 10.0,
            "tilt_angle": 30.0,
            "azimuth_angle": -15.0,
            "location_name": "Warszawa",
        }).encode("utf-8")

        status_code, response = handle_simulate(body)
        self.assertEqual(status_code, 200)
        self.assertEqual(response["peak_power_kw"], 8.0)


class TestValidateInput(unittest.TestCase):
    """Testy dla funkcji walidacji danych wejsciowych."""

    def test_valid_data_returns_none(self):
        """Poprawne dane powinny zwracac None (brak bledu)."""
        data = {"latitude": 52.23, "longitude": 21.01}
        result = _validate_input(data)
        self.assertIsNone(result)

    def test_missing_latitude(self):
        """Brak latitude powinien zwracac komunikat bledu."""
        data = {"longitude": 21.01}
        result = _validate_input(data)
        self.assertIsNotNone(result)
        self.assertIn("latitude", result)

    def test_missing_longitude(self):
        """Brak longitude powinien zwracac komunikat bledu."""
        data = {"latitude": 52.23}
        result = _validate_input(data)
        self.assertIsNotNone(result)
        self.assertIn("longitude", result)

    def test_latitude_out_of_range(self):
        """Szerokosc poza zakresem powinno zwracac blad."""
        data = {"latitude": 95.0, "longitude": 21.01}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_longitude_out_of_range(self):
        """Dlugosc poza zakresem powinno zwracac blad."""
        data = {"latitude": 52.23, "longitude": 200.0}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_non_numeric_latitude(self):
        """Nieczesliczbowa szerokosc powinna zwracac blad."""
        data = {"latitude": "abc", "longitude": 21.01}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_zero_power_returns_error(self):
        """Moc rowna 0 powinna zwracac blad."""
        data = {"latitude": 52.23, "longitude": 21.01, "peak_power_kw": 0}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_loss_out_of_range(self):
        """Straty poza zakresem powinny zwracac blad."""
        data = {"latitude": 52.23, "longitude": 21.01, "system_loss_percent": 150}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_tilt_out_of_range(self):
        """Kat nachylenia poza zakresem powinien zwracac blad."""
        data = {"latitude": 52.23, "longitude": 21.01, "tilt_angle": 100}
        result = _validate_input(data)
        self.assertIsNotNone(result)

    def test_azimuth_out_of_range(self):
        """Azymut poza zakresem powinien zwracac blad."""
        data = {"latitude": 52.23, "longitude": 21.01, "azimuth_angle": 200}
        result = _validate_input(data)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
