"""
Testy jednostkowe dla modulu calculator.py

Testy sprawdzaja czy obliczenia produkcji energii dzialaja poprawnie.
Uzywamy mock (atrapa/imitacja) zeby nie wykonywac prawdziwych zapytan
do internetu podczas testow.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Dodanie sciezki projektu zeby importy dzialaly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.models.simulation import SimulationInput, SimulationResult
from backend.services.calculator import (
    calculate_annual_production,
    _calculate_fallback,
    _get_latitude_factor,
    _get_tilt_factor,
    AVERAGE_IRRADIATION_CENTRAL_EUROPE,
    MONTHLY_DISTRIBUTION,
)


class TestCalculatorFallback(unittest.TestCase):
    """Testy dla obliczen uproszczonych (fallback) - gdy PVGIS niedostepny."""

    def setUp(self):
        """Przygotowanie danych testowych - wykonuje sie przed kazdym testem."""
        # Typowe dane wejsciowe - Warszawa, 5 kW, domyslne parametry
        self.default_input = SimulationInput(
            latitude=52.23,
            longitude=21.01,
            peak_power_kw=5.0,
            system_loss_percent=14.0,
            tilt_angle=35.0,
            azimuth_angle=0.0,
            location_name="Warszawa",
        )

    def test_fallback_returns_simulation_result(self):
        """Sprawdza czy fallback zwraca obiekt SimulationResult."""
        result = _calculate_fallback(self.default_input)
        self.assertIsInstance(result, SimulationResult)

    def test_fallback_annual_energy_positive(self):
        """Sprawdza czy roczna produkcja energii jest dodatnia."""
        result = _calculate_fallback(self.default_input)
        self.assertGreater(result.annual_energy_kwh, 0)

    def test_fallback_annual_energy_reasonable_range(self):
        """
        Sprawdza czy wynik jest w rozsadnym zakresie.
        Dla 5 kW w Polsce powinno byc 3500-6500 kWh/rok.
        """
        result = _calculate_fallback(self.default_input)
        self.assertGreater(result.annual_energy_kwh, 3000)
        self.assertLess(result.annual_energy_kwh, 7000)

    def test_fallback_has_12_months(self):
        """Sprawdza czy wynik zawiera dane dla 12 miesiecy."""
        result = _calculate_fallback(self.default_input)
        self.assertEqual(len(result.monthly_energy_kwh), 12)

    def test_fallback_monthly_sum_equals_annual(self):
        """Sprawdza czy suma miesieczna = roczna produkcja (z tolerancja zaokraglen)."""
        result = _calculate_fallback(self.default_input)
        monthly_sum = sum(result.monthly_energy_kwh)
        self.assertAlmostEqual(monthly_sum, result.annual_energy_kwh, places=1)

    def test_fallback_summer_more_than_winter(self):
        """Sprawdza czy latem jest wieksza produkcja niz zima."""
        result = _calculate_fallback(self.default_input)
        # Czerwiec (indeks 5) powinien miec wiecej niz grudzien (indeks 11)
        self.assertGreater(
            result.monthly_energy_kwh[5],
            result.monthly_energy_kwh[11],
        )

    def test_fallback_data_source_is_fallback(self):
        """Sprawdza czy zrodlo danych jest oznaczone jako 'fallback'."""
        result = _calculate_fallback(self.default_input)
        self.assertEqual(result.data_source, "fallback")

    def test_fallback_preserves_location_name(self):
        """Sprawdza czy nazwa lokalizacji jest zachowana w wyniku."""
        result = _calculate_fallback(self.default_input)
        self.assertEqual(result.location_name, "Warszawa")

    def test_fallback_preserves_peak_power(self):
        """Sprawdza czy moc szczytowa jest zachowana w wyniku."""
        result = _calculate_fallback(self.default_input)
        self.assertEqual(result.peak_power_kw, 5.0)

    def test_fallback_more_power_more_energy(self):
        """Sprawdza czy wieksza moc paneli = wiecej energii."""
        input_small = SimulationInput(latitude=52.0, longitude=21.0, peak_power_kw=3.0)
        input_large = SimulationInput(latitude=52.0, longitude=21.0, peak_power_kw=10.0)

        result_small = _calculate_fallback(input_small)
        result_large = _calculate_fallback(input_large)

        self.assertGreater(result_large.annual_energy_kwh, result_small.annual_energy_kwh)

    def test_fallback_more_losses_less_energy(self):
        """Sprawdza czy wieksze straty = mniej energii."""
        input_low_loss = SimulationInput(
            latitude=52.0, longitude=21.0, peak_power_kw=5.0, system_loss_percent=5.0
        )
        input_high_loss = SimulationInput(
            latitude=52.0, longitude=21.0, peak_power_kw=5.0, system_loss_percent=30.0
        )

        result_low = _calculate_fallback(input_low_loss)
        result_high = _calculate_fallback(input_high_loss)

        self.assertGreater(result_low.annual_energy_kwh, result_high.annual_energy_kwh)


class TestLatitudeFactor(unittest.TestCase):
    """Testy dla wspolczynnika szerokosci geograficznej."""

    def test_central_europe_factor_close_to_one(self):
        """Dla Europy Srodkowej (50N) wspolczynnik powinien byc bliski 1."""
        factor = _get_latitude_factor(50.0)
        self.assertAlmostEqual(factor, 1.0, places=1)

    def test_southern_europe_higher_factor(self):
        """Poludniowa Europa powinna miec wyzszy wspolczynnik (wiecej slonca)."""
        factor_south = _get_latitude_factor(40.0)
        factor_north = _get_latitude_factor(60.0)
        self.assertGreater(factor_south, factor_north)

    def test_factor_never_negative(self):
        """Wspolczynnik nigdy nie moze byc ujemny."""
        for lat in [-90, -45, 0, 45, 90]:
            factor = _get_latitude_factor(lat)
            self.assertGreater(factor, 0)


class TestTiltFactor(unittest.TestCase):
    """Testy dla wspolczynnika kata nachylenia."""

    def test_optimal_tilt_factor_close_to_one(self):
        """Optymalny kat nachylenia powinien dawac wspolczynnik bliski 1."""
        # Dla 50N optymalny kat to okolo 40 stopni
        factor = _get_tilt_factor(40.0, 50.0)
        self.assertGreater(factor, 0.9)

    def test_flat_panels_lower_factor(self):
        """Panele plaskie (0 stopni) powinny miec nizszy wspolczynnik."""
        factor_flat = _get_tilt_factor(0.0, 50.0)
        factor_optimal = _get_tilt_factor(40.0, 50.0)
        self.assertLess(factor_flat, factor_optimal)

    def test_factor_always_positive(self):
        """Wspolczynnik kata zawsze musi byc dodatni."""
        for tilt in [0, 15, 30, 45, 60, 75, 90]:
            factor = _get_tilt_factor(tilt, 50.0)
            self.assertGreater(factor, 0)


class TestCalculateAnnualProduction(unittest.TestCase):
    """Testy dla glownej funkcji obliczeniowej."""

    @patch('backend.services.calculator.get_pv_estimation')
    def test_uses_pvgis_when_available(self, mock_pvgis):
        """Sprawdza czy uzywa danych PVGIS gdy sa dostepne."""
        # Przygotowanie atrap danych PVGIS
        mock_pvgis.return_value = {
            "annual_energy_kwh": 5200.0,
            "monthly_energy_kwh": [200, 250, 400, 500, 600, 650, 670, 620, 480, 350, 250, 180],
            "irradiation_kwh_m2": 1150.0,
        }

        input_data = SimulationInput(latitude=52.23, longitude=21.01, peak_power_kw=5.0)
        result = calculate_annual_production(input_data)

        self.assertEqual(result.annual_energy_kwh, 5200.0)
        self.assertEqual(result.data_source, "pvgis")

    @patch('backend.services.calculator.get_pv_estimation')
    def test_uses_fallback_when_pvgis_unavailable(self, mock_pvgis):
        """Sprawdza czy uzywa fallback gdy PVGIS nie odpowiada."""
        mock_pvgis.return_value = None

        input_data = SimulationInput(latitude=52.23, longitude=21.01, peak_power_kw=5.0)
        result = calculate_annual_production(input_data)

        self.assertGreater(result.annual_energy_kwh, 0)
        self.assertEqual(result.data_source, "fallback")


class TestMonthlyDistribution(unittest.TestCase):
    """Testy dla rozkladu miesiecznego."""

    def test_distribution_sums_to_one(self):
        """Sprawdza czy procenty miesieczne sumuja sie do 100%."""
        total = sum(MONTHLY_DISTRIBUTION)
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_distribution_has_12_months(self):
        """Sprawdza czy mamy 12 miesiecy."""
        self.assertEqual(len(MONTHLY_DISTRIBUTION), 12)

    def test_all_months_positive(self):
        """Sprawdza czy kazdy miesiac ma wartosc dodatnia."""
        for ratio in MONTHLY_DISTRIBUTION:
            self.assertGreater(ratio, 0)


class TestSimulationResultToDict(unittest.TestCase):
    """Testy dla metody to_dict() modelu wynikow."""

    def test_to_dict_has_required_fields(self):
        """Sprawdza czy slownik wynikowy zawiera wszystkie pola."""
        result = SimulationResult(
            annual_energy_kwh=5000.0,
            monthly_energy_kwh=[400] * 12,
            peak_power_kw=5.0,
            location_name="Test",
            irradiation_kwh_m2=1100.0,
            data_source="fallback",
        )
        d = result.to_dict()

        self.assertIn("annual_energy_kwh", d)
        self.assertIn("monthly_energy_kwh", d)
        self.assertIn("peak_power_kw", d)
        self.assertIn("location_name", d)
        self.assertIn("irradiation_kwh_m2", d)
        self.assertIn("data_source", d)

    def test_to_dict_rounds_values(self):
        """Sprawdza czy wartosci sa zaokraglone."""
        result = SimulationResult(
            annual_energy_kwh=5123.456789,
            monthly_energy_kwh=[410.123456] * 12,
            peak_power_kw=5.0,
            irradiation_kwh_m2=1100.789,
        )
        d = result.to_dict()

        self.assertEqual(d["annual_energy_kwh"], 5123.46)
        self.assertEqual(d["irradiation_kwh_m2"], 1100.79)


if __name__ == "__main__":
    unittest.main()
