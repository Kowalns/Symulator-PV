"""
Kalkulator produkcji energii z paneli fotowoltaicznych.

Ten modul zawiera logike obliczen:
1. Probuje pobrac dane z PVGIS (dokladne dane dla konkretnej lokalizacji)
2. Jesli PVGIS jest niedostepny, uzywa uproszczonych obliczen (fallback)

Obliczenia fallback opieraja sie na sredniej irradiacji (naslonecznieniu)
dla Europy Srodkowej - okolo 1000-1100 kWh/m2 na rok.
"""

import math
from typing import Optional

from backend.models.simulation import SimulationInput, SimulationResult
from backend.services.pvgis import get_pv_estimation


# Srednia roczna irradiacja dla Europy Srodkowej (kWh/m2/rok)
# To ile energii slonecznej pada na 1 metr kwadratowy przez caly rok
AVERAGE_IRRADIATION_CENTRAL_EUROPE = 1050.0

# Typowy rozklad miesieczny irradiacji w Europie Srodkowej (w procentach)
# Zima ma mniej slonca, lato wiecej
MONTHLY_DISTRIBUTION = [
    0.04,  # Styczen - 4% rocznej energii
    0.05,  # Luty - 5%
    0.08,  # Marzec - 8%
    0.10,  # Kwiecien - 10%
    0.12,  # Maj - 12%
    0.13,  # Czerwiec - 13%
    0.13,  # Lipiec - 13%
    0.12,  # Sierpien - 12%
    0.09,  # Wrzesien - 9%
    0.07,  # Pazdziernik - 7%
    0.04,  # Listopad - 4%
    0.03,  # Grudzien - 3%
]

# Wspolczynnik wydajnosci systemu (Performance Ratio)
# Uwzglednia straty na inwertorze, kablach, temperaturze itp.
# Typowa wartosc: 0.75-0.85
DEFAULT_PERFORMANCE_RATIO = 0.80


def calculate_annual_production(input_data: SimulationInput) -> SimulationResult:
    """
    Glowna funkcja obliczeniowa - oblicza roczna produkcje energii.

    Najpierw probuje pobrac dane z PVGIS (dokladniejsze).
    Jesli PVGIS jest niedostepny, uzywa obliczen uproszczonych (fallback).

    Parametry:
        input_data: dane wejsciowe od uzytkownika (lokalizacja, moc paneli itp.)

    Zwraca:
        SimulationResult z wynikami obliczen
    """
    # Proba pobrania danych z PVGIS
    pvgis_data = get_pv_estimation(
        lat=input_data.latitude,
        lon=input_data.longitude,
        peak_power=input_data.peak_power_kw,
        loss=input_data.system_loss_percent,
        tilt=input_data.tilt_angle,
        azimuth=input_data.azimuth_angle,
    )

    if pvgis_data is not None:
        # Mamy dane z PVGIS - uzywamy ich
        return SimulationResult(
            annual_energy_kwh=pvgis_data["annual_energy_kwh"],
            monthly_energy_kwh=pvgis_data["monthly_energy_kwh"],
            peak_power_kw=input_data.peak_power_kw,
            location_name=input_data.location_name,
            irradiation_kwh_m2=pvgis_data["irradiation_kwh_m2"],
            data_source="pvgis",
        )
    else:
        # PVGIS niedostepny - uzywamy obliczen uproszczonych
        return _calculate_fallback(input_data)


def _calculate_fallback(input_data: SimulationInput) -> SimulationResult:
    """
    Uproszczone obliczenia produkcji energii (fallback).

    Uzywane gdy PVGIS API jest niedostepne.
    Oparte na srednich wartosciach dla Europy Srodkowej.

    Wzor: E = Ppeak * H * PR * (1 - loss/100) * tilt_factor
    Gdzie:
        E = roczna energia (kWh)
        Ppeak = moc szczytowa paneli (kW)
        H = roczne naslonecznienie (kWh/m2)
        PR = wspolczynnik wydajnosci (Performance Ratio)
        loss = straty systemowe (%)
        tilt_factor = korekta za kat nachylenia
    """
    # Korekta irradiacji w zaleznosci od szerokosci geograficznej
    # Im dalej na polnoc, tym mniej slonca
    latitude_factor = _get_latitude_factor(input_data.latitude)

    # Korekta za kat nachylenia paneli
    # Optymalny kat to mniej wiecej szerokosc geograficzna
    tilt_factor = _get_tilt_factor(input_data.tilt_angle, input_data.latitude)

    # Efektywne naslonecznienie dla tej lokalizacji
    effective_irradiation = AVERAGE_IRRADIATION_CENTRAL_EUROPE * latitude_factor * tilt_factor

    # Obliczenie rocznej produkcji energii
    # Wzor: moc_paneli * naslonecznienie * wydajnosc * (1 - straty)
    loss_factor = 1.0 - (input_data.system_loss_percent / 100.0)
    annual_energy = (
        input_data.peak_power_kw
        * effective_irradiation
        * DEFAULT_PERFORMANCE_RATIO
        * loss_factor
    )

    # Rozlozenie na miesiace wedlug typowego rozkladu
    monthly_energy = [annual_energy * ratio for ratio in MONTHLY_DISTRIBUTION]

    return SimulationResult(
        annual_energy_kwh=annual_energy,
        monthly_energy_kwh=monthly_energy,
        peak_power_kw=input_data.peak_power_kw,
        location_name=input_data.location_name,
        irradiation_kwh_m2=effective_irradiation,
        data_source="fallback",
    )


def _get_latitude_factor(latitude: float) -> float:
    """
    Oblicza wspolczynnik korekcji dla szerokosci geograficznej.

    Im blizej rownika (latitude = 0), tym wiecej slonca.
    Europa Srodkowa to okolice 50 stopni N - nasz punkt odniesienia.
    """
    # Punkt odniesienia: 50 stopni N (srodek Europy)
    reference_latitude = 50.0

    # Korekta: okolo 2% na kazdy stopien oddalenia od 50 N
    # (uproszczenie - w rzeczywistosci zalezy od pory roku)
    diff = abs(latitude) - reference_latitude
    factor = 1.0 - (diff * 0.02)

    # Ograniczamy do rozsadnego zakresu (0.5 - 1.5)
    return max(0.5, min(1.5, factor))


def _get_tilt_factor(tilt_angle: float, latitude: float) -> float:
    """
    Oblicza wspolczynnik korekcji za kat nachylenia paneli.

    Optymalny kat nachylenia paneli to w przyblizeniu szerokosc geograficzna
    pomniejszona o 10-15 stopni. Odchylenie od optymalnego kata zmniejsza
    wydajnosc.
    """
    # Optymalny kat nachylenia (w przyblizeniu)
    optimal_tilt = abs(latitude) - 10.0
    optimal_tilt = max(20.0, min(60.0, optimal_tilt))

    # Odchylenie od optymalnego kata
    deviation = abs(tilt_angle - optimal_tilt)

    # Kazdy stopien odchylenia zmniejsza wydajnosc o okolo 0.3%
    # (uproszczenie - w rzeczywistosci zalezy od wielu czynnikow)
    factor = 1.0 - (deviation * 0.003)

    # Ograniczamy do rozsadnego zakresu
    return max(0.7, min(1.1, factor))
