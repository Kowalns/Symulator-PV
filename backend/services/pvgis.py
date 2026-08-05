"""
Klient PVGIS API - pobiera dane o naslonecznieniu z europejskiej bazy danych.

PVGIS (Photovoltaic Geographical Information System) to darmowe narzedzie
Komisji Europejskiej, ktore dostarcza dane o promieniowaniu slonecznym
i pozwala oszacowac produkcje energii z paneli fotowoltaicznych.

Strona: https://re.jrc.ec.europa.eu/pvg_tools/en/
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional


# Adres bazowy API PVGIS wersja 5.2
PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"

# Timeout (czas oczekiwania) na odpowiedz serwera w sekundach
REQUEST_TIMEOUT = 30


def get_pv_estimation(
    lat: float,
    lon: float,
    peak_power: float = 5.0,
    loss: float = 14.0,
    tilt: float = 35.0,
    azimuth: float = 0.0,
) -> Optional[dict]:
    """
    Pobiera oszacowanie produkcji PV z PVGIS API.

    Parametry:
        lat: szerokosc geograficzna (np. 52.23 dla Warszawy)
        lon: dlugosc geograficzna (np. 21.01 dla Warszawy)
        peak_power: moc szczytowa instalacji w kW
        loss: straty systemowe w procentach
        tilt: kat nachylenia paneli w stopniach
        azimuth: azymut (kierunek) paneli w stopniach

    Zwraca:
        Slownik z danymi z PVGIS lub None jesli cos poszlo nie tak.
        Slownik zawiera m.in.:
        - "annual_energy_kwh": roczna produkcja energii
        - "monthly_energy_kwh": lista 12 wartosci miesiecznych
        - "irradiation_kwh_m2": roczne naslonecznienie
    """
    # Przygotowanie parametrow zapytania do API
    params = {
        "lat": lat,
        "lon": lon,
        "peakpower": peak_power,
        "loss": loss,
        "angle": tilt,
        "aspect": azimuth,
        "outputformat": "json",
    }

    # Budowanie pelnego adresu URL z parametrami
    query_string = urllib.parse.urlencode(params)
    url = f"{PVGIS_BASE_URL}?{query_string}"

    try:
        # Wysylanie zapytania do serwera PVGIS
        request = urllib.request.Request(url)
        request.add_header("User-Agent", "PV-Simulator/1.0")

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            # Odczytanie i przetworzenie odpowiedzi JSON
            data = json.loads(response.read().decode("utf-8"))

        # Wyciaganie potrzebnych danych z odpowiedzi PVGIS
        return _parse_pvgis_response(data)

    except urllib.error.HTTPError as e:
        # Blad HTTP - serwer zwrocil blad (np. 404, 500)
        print(f"[PVGIS] Blad HTTP: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        # Blad polaczenia - nie mozna polaczyc sie z serwerem
        print(f"[PVGIS] Blad polaczenia: {e.reason}")
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        # Blad przetwarzania danych - odpowiedz ma nieoczekiwany format
        print(f"[PVGIS] Blad przetwarzania odpowiedzi: {e}")
        return None
    except Exception as e:
        # Inny nieoczekiwany blad
        print(f"[PVGIS] Nieoczekiwany blad: {e}")
        return None


def _parse_pvgis_response(data: dict) -> Optional[dict]:
    """
    Przetwarza surowa odpowiedz z PVGIS API na prosty slownik.

    PVGIS zwraca skomplikowana strukture JSON - ta funkcja wyciaga
    tylko to co potrzebujemy.
    """
    try:
        outputs = data.get("outputs", {})
        totals = outputs.get("totals", {})
        fixed = totals.get("fixed", {})
        monthly = outputs.get("monthly", {}).get("fixed", [])

        # Roczna produkcja energii w kWh
        annual_energy = fixed.get("E_y", 0.0)

        # Roczne naslonecznienie na plaszczyzne paneli
        irradiation = fixed.get("H(i)_y", 0.0)

        # Miesieczna produkcja - lista 12 wartosci
        monthly_energy = []
        for month_data in monthly:
            monthly_energy.append(month_data.get("E_m", 0.0))

        # Jesli nie mamy 12 miesiecy, cos poszlo nie tak
        if len(monthly_energy) != 12:
            print(f"[PVGIS] Nieoczekiwana liczba miesiecy: {len(monthly_energy)}")
            return None

        return {
            "annual_energy_kwh": annual_energy,
            "monthly_energy_kwh": monthly_energy,
            "irradiation_kwh_m2": irradiation,
        }

    except (KeyError, TypeError, IndexError) as e:
        print(f"[PVGIS] Blad parsowania danych: {e}")
        return None
