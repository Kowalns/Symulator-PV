"""
Testy endpointu GET /api/solar-position.

Testuje:
- Poprawne wywolanie z kompletnymi parametrami
- Brak wymaganych parametrow
- Nieprawidlowe wartosci parametrow
- Odpowiedz dla nocy (ujemna elewacja)
"""

import unittest
from backend.api.handlers import handle_solar_position


class TestHandleSolarPosition(unittest.TestCase):
    """Testy handlera handle_solar_position."""

    def test_valid_request_returns_200_with_azymut_and_elewacja(self):
        """Poprawne zapytanie zwraca 200 z polami azymut i elewacja."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 200)
        self.assertIn("azymut", response)
        self.assertIn("elewacja", response)
        self.assertIsInstance(response["azymut"], float)
        self.assertIsInstance(response["elewacja"], float)
        # W poludnie w czerwcu elewacja powinna byc dodatnia
        self.assertGreater(response["elewacja"], 0)

    def test_valid_request_morning(self):
        """Poprawne zapytanie dla godziny porannej."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["8"],
            "minuta": ["30"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 200)
        self.assertIn("azymut", response)
        self.assertIn("elewacja", response)
        # Rano elewacja powinna byc dodatnia w czerwcu
        self.assertGreater(response["elewacja"], 0)
        # Azymut rano powinien byc < 180 (wschodnia czesc nieba)
        self.assertLess(response["azymut"], 180)

    def test_missing_params_returns_400(self):
        """Brak wymaganych parametrow zwraca 400."""
        # Brak parametru 'lat'
        query_params = {
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_missing_multiple_params_returns_400(self):
        """Brak wielu parametrow zwraca 400 z lista brakujacych."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)
        self.assertIn("message", response)

    def test_empty_params_returns_400(self):
        """Puste parametry zwracaja 400."""
        query_params = {}
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_invalid_lat_value_returns_400(self):
        """Nieprawidlowa wartosc lat (poza zakresem) zwraca 400."""
        query_params = {
            "lat": ["100.0"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_invalid_lon_value_returns_400(self):
        """Nieprawidlowa wartosc lon (poza zakresem) zwraca 400."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["200.0"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_invalid_non_numeric_param_returns_400(self):
        """Parametr nieliczbowy zwraca 400."""
        query_params = {
            "lat": ["abc"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_invalid_month_returns_400(self):
        """Nieprawidlowy miesiac (13) zwraca 400."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["13"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_invalid_hour_returns_400(self):
        """Nieprawidlowa godzina (25) zwraca 400."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["25"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_nighttime_returns_negative_elevation(self):
        """Zapytanie o noc (godzina 2) zwraca ujemna elewacje."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["12"],
            "dzien": ["15"],
            "godzina": ["2"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 200)
        self.assertIn("elewacja", response)
        # O 2:00 w grudniu elewacja powinna byc ujemna (noc)
        self.assertLess(response["elewacja"], 0)

    def test_invalid_minute_returns_400(self):
        """Nieprawidlowa minuta (60) zwraca 400."""
        query_params = {
            "lat": ["52.23"],
            "lon": ["21.01"],
            "rok": ["2025"],
            "miesiac": ["6"],
            "dzien": ["15"],
            "godzina": ["12"],
            "minuta": ["60"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 400)
        self.assertIn("error", response)

    def test_boundary_values_valid(self):
        """Wartosci graniczne (poprawne) zwracaja 200."""
        query_params = {
            "lat": ["0.0"],
            "lon": ["0.0"],
            "rok": ["2025"],
            "miesiac": ["1"],
            "dzien": ["1"],
            "godzina": ["0"],
            "minuta": ["0"],
        }
        status_code, response = handle_solar_position(query_params)
        self.assertEqual(status_code, 200)
        self.assertIn("azymut", response)
        self.assertIn("elewacja", response)


if __name__ == "__main__":
    unittest.main()
