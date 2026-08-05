"""
Modele danych do symulacji PV (fotowoltaiki).

Uzywamy 'dataclass' - to sposob na tworzenie klas (szablonow) do przechowywania danych.
Zamiast pisac duzo kodu, Python sam tworzy konstruktor i inne metody.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SimulationInput:
    """
    Dane wejsciowe do symulacji - co uzytkownik podaje.

    Atrybuty:
        latitude: szerokosc geograficzna (np. 52.23 dla Warszawy)
            - mowi jak daleko na polnoc/poludnie jest lokalizacja
        longitude: dlugosc geograficzna (np. 21.01 dla Warszawy)
            - mowi jak daleko na wschod/zachod jest lokalizacja
        peak_power_kw: moc szczytowa paneli w kilowatach (kW)
            - ile maksymalnie pradu panele moga produkowac w idealnych warunkach
        system_loss_percent: straty systemowe w procentach (domyslnie 14%)
            - czesc energii zawsze sie traci na kablach, przetwornikach itp.
        tilt_angle: kat nachylenia paneli w stopniach (domyslnie 35)
            - jak bardzo panele sa pochylone wzgledem ziemi
        azimuth_angle: azymut - kierunek w ktory patrza panele (domyslnie 0 = poludnie)
            - 0 = poludnie, 90 = zachod, -90 = wschod, 180 = polnoc
        location_name: opcjonalna nazwa lokalizacji (np. "Warszawa")
    """
    latitude: float
    longitude: float
    peak_power_kw: float = 5.0
    system_loss_percent: float = 14.0
    tilt_angle: float = 35.0
    azimuth_angle: float = 0.0
    location_name: Optional[str] = None


@dataclass
class SimulationResult:
    """
    Wynik symulacji - co uzytkownik dostaje.

    Atrybuty:
        annual_energy_kwh: roczna produkcja energii w kilowatogodzinach (kWh)
            - ile pradu panele wyprodukuja przez caly rok
        monthly_energy_kwh: lista 12 wartosci - produkcja na kazdy miesiac
        peak_power_kw: moc szczytowa instalacji (ta sama co wejsciowa)
        location_name: nazwa lokalizacji (jesli podana)
        irradiation_kwh_m2: roczne naslonecznienie w kWh na metr kwadratowy
            - ile energii slonecznej pada na dany teren
        data_source: skad pochodza dane ("pvgis" lub "fallback")
            - "pvgis" = dane z europejskiej bazy danych
            - "fallback" = uproszczone obliczenia gdy baza niedostepna
    """
    annual_energy_kwh: float
    monthly_energy_kwh: List[float] = field(default_factory=list)
    peak_power_kw: float = 5.0
    location_name: Optional[str] = None
    irradiation_kwh_m2: float = 0.0
    data_source: str = "fallback"

    def to_dict(self) -> dict:
        """Zamienia wynik na slownik (dict) - potrzebne do wyslania jako JSON."""
        return {
            "annual_energy_kwh": round(self.annual_energy_kwh, 2),
            "monthly_energy_kwh": [round(m, 2) for m in self.monthly_energy_kwh],
            "peak_power_kw": self.peak_power_kw,
            "location_name": self.location_name,
            "irradiation_kwh_m2": round(self.irradiation_kwh_m2, 2),
            "data_source": self.data_source,
        }
