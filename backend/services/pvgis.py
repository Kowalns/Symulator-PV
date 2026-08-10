"""
Klient PVGIS API - pobiera dane o naslonecznieniu z europejskiej bazy danych.

PVGIS (Photovoltaic Geographical Information System) to darmowe narzedzie
Komisji Europejskiej, ktore dostarcza dane o promieniowaniu slonecznym
i pozwala oszacowac produkcje energii z paneli fotowoltaicznych.

Obsluguje dwa endpointy:
1. PVcalc - szacowanie produkcji PV (wersja v5_2)
2. TMY - dane Typical Meteorological Year z godzinowymi wartosciami
   GHI, DNI, DHI, temperatury i wiatru (wersja v5_3)

Strona: https://re.jrc.ec.europa.eu/pvg_tools/en/
"""

import json
import os
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, List


# Adres bazowy API PVGIS wersja 5.2
PVGIS_BASE_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"

# Adres API TMY (Typical Meteorological Year) wersja 5.3
PVGIS_TMY_URL = "https://re.jrc.ec.europa.eu/api/v5_3/tmy"

# Timeout (czas oczekiwania) na odpowiedz serwera w sekundach
REQUEST_TIMEOUT = 30

# Katalog cache dla danych TMY
_TMY_CACHE_DIR = Path(__file__).parent.parent / "data" / "tmy_cache"


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


def _klucz_cache_tmy(lat: float, lon: float) -> str:
    """
    Generuje nazwe pliku cache dla danych TMY na podstawie wspolrzednych.

    Zaokragla do 2 miejsc po przecinku zeby uniknac duplikatow
    dla nieznacznie roznych wspolrzednych.
    """
    lat_r = round(lat, 2)
    lon_r = round(lon, 2)
    # Zamien kropki na podkreslniki i minus na 'm' dla nazwy pliku
    lat_str = f"{lat_r}".replace(".", "_").replace("-", "m")
    lon_str = f"{lon_r}".replace(".", "_").replace("-", "m")
    return f"tmy_{lat_str}_{lon_str}.json"


def _wczytaj_cache_tmy(lat: float, lon: float) -> Optional[Dict]:
    """
    Probuje wczytac dane TMY z lokalnego cache.

    Zwraca:
        Slownik z danymi TMY lub None jesli cache nie istnieje.
    """
    klucz = _klucz_cache_tmy(lat, lon)
    sciezka = _TMY_CACHE_DIR / klucz

    if not sciezka.exists():
        return None

    try:
        with open(sciezka, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"[PVGIS TMY] Blad odczytu cache: {e}")
        return None


def _zapisz_cache_tmy(lat: float, lon: float, dane: Dict) -> None:
    """
    Zapisuje dane TMY do lokalnego cache.
    """
    _TMY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    klucz = _klucz_cache_tmy(lat, lon)
    sciezka = _TMY_CACHE_DIR / klucz

    try:
        with open(sciezka, "w", encoding="utf-8") as f:
            json.dump(dane, f, ensure_ascii=False)
    except IOError as e:
        print(f"[PVGIS TMY] Blad zapisu cache: {e}")


def pobierz_dane_tmy(lat: float, lon: float, uzyj_cache: bool = True) -> Optional[Dict]:
    """
    Pobiera dane TMY (Typical Meteorological Year) z PVGIS API.

    Dane TMY zawieraja godzinowe wartosci meteorologiczne dla typowego roku:
    - GHI (Global Horizontal Irradiance) [W/m2]
    - DNI (Direct Normal Irradiance) [W/m2]
    - DHI (Diffuse Horizontal Irradiance) [W/m2]
    - Temperatura powietrza [C]
    - Predkosc wiatru [m/s]

    Parametry:
        lat: szerokosc geograficzna (np. 54.0 dla Gdanska)
        lon: dlugosc geograficzna (np. 18.6 dla Gdanska)
        uzyj_cache: czy uzywac lokalnego cache (domyslnie True)

    Zwraca:
        Slownik z kluczami:
        - "ghi": lista 8760 wartosci GHI [W/m2]
        - "dni": lista 8760 wartosci DNI [W/m2]
        - "dhi": lista 8760 wartosci DHI [W/m2]
        - "temperatura": lista 8760 wartosci temperatury [C]
        - "wiatr": lista 8760 wartosci predkosci wiatru [m/s]
        - "roczne_ghi_kwh_m2": suma roczna GHI [kWh/m2]
        Lub None jesli pobieranie sie nie powiodlo.
    """
    # Sprawdz cache
    if uzyj_cache:
        dane_cache = _wczytaj_cache_tmy(lat, lon)
        if dane_cache is not None:
            return dane_cache

    # Przygotowanie zapytania do API
    params = {
        "lat": lat,
        "lon": lon,
        "outputformat": "json",
    }

    query_string = urllib.parse.urlencode(params)
    url = f"{PVGIS_TMY_URL}?{query_string}"

    try:
        request = urllib.request.Request(url)
        request.add_header("User-Agent", "PV-Simulator/1.0")

        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))

        # Parsowanie odpowiedzi TMY
        dane_tmy = _parsuj_odpowiedz_tmy(data)

        if dane_tmy is not None and uzyj_cache:
            _zapisz_cache_tmy(lat, lon, dane_tmy)

        return dane_tmy

    except urllib.error.HTTPError as e:
        print(f"[PVGIS TMY] Blad HTTP: {e.code} - {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"[PVGIS TMY] Blad polaczenia: {e.reason}")
        return None
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[PVGIS TMY] Blad przetwarzania odpowiedzi: {e}")
        return None
    except Exception as e:
        print(f"[PVGIS TMY] Nieoczekiwany blad: {e}")
        return None


def _parsuj_odpowiedz_tmy(data: dict) -> Optional[Dict]:
    """
    Parsuje surowa odpowiedz JSON z endpointu TMY PVGIS.

    Endpoint zwraca strukture:
    {
        "outputs": {
            "tmy_hourly": [
                {"G(h)": ..., "Gb(n)": ..., "Gd(h)": ..., "T2m": ..., "WS10m": ..., "time(UTC)": ...},
                ...
            ]
        }
    }

    Zwraca:
        Slownik z listami godzinowych wartosci lub None przy bledzie.
    """
    try:
        outputs = data.get("outputs", {})
        tmy_hourly = outputs.get("tmy_hourly", [])

        if not tmy_hourly:
            print("[PVGIS TMY] Brak danych godzinowych w odpowiedzi")
            return None

        ghi_lista = []
        dni_lista = []
        dhi_lista = []
        temp_lista = []
        wiatr_lista = []

        for rekord in tmy_hourly:
            ghi_lista.append(float(rekord.get("G(h)", 0.0)))
            dni_lista.append(float(rekord.get("Gb(n)", 0.0)))
            dhi_lista.append(float(rekord.get("Gd(h)", 0.0)))
            temp_lista.append(float(rekord.get("T2m", 0.0)))
            wiatr_lista.append(float(rekord.get("WS10m", 0.0)))

        # TMY zawiera 8760 godzin (rok niestepny)
        if len(ghi_lista) < 8760:
            print(f"[PVGIS TMY] Za malo danych: {len(ghi_lista)} (oczekiwano 8760)")
            return None

        # Przytnij do 8760 godzin (niektore odpowiedzi moga miec wiecej)
        ghi_lista = ghi_lista[:8760]
        dni_lista = dni_lista[:8760]
        dhi_lista = dhi_lista[:8760]
        temp_lista = temp_lista[:8760]
        wiatr_lista = wiatr_lista[:8760]

        # Oblicz roczne naslonecznienie GHI [kWh/m2]
        roczne_ghi = sum(ghi_lista) / 1000.0  # W/m2 * 1h = Wh/m2 -> /1000 = kWh/m2

        return {
            "ghi": ghi_lista,
            "dni": dni_lista,
            "dhi": dhi_lista,
            "temperatura": temp_lista,
            "wiatr": wiatr_lista,
            "roczne_ghi_kwh_m2": round(roczne_ghi, 2),
        }

    except (KeyError, TypeError, ValueError) as e:
        print(f"[PVGIS TMY] Blad parsowania danych TMY: {e}")
        return None
