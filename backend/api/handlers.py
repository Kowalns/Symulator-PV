"""
Handlery API - obsluguja zapytania HTTP przychodzace od frontendu.

Handler to funkcja, ktora:
1. Odbiera zapytanie od uzytkownika (np. dane lokalizacji)
2. Przetwarza je (wywoluje obliczenia)
3. Odsyla odpowiedz (wynik symulacji jako JSON)
"""

import json
from typing import Tuple, Optional

from backend.models.simulation import SimulationInput
from backend.models.installation import InstallationConfig
from backend.services.calculator import calculate_annual_production
from backend.services.installation_layout import (
    wczytaj_baze_paneli,
    wczytaj_baze_falownikow,
    wczytaj_baze_baterii,
    waliduj_konfiguracje,
    oblicz_rozmieszczenie,
)


def handle_health() -> Tuple[int, dict]:
    """
    Endpoint zdrowia serwera (health check).

    Sluzy do sprawdzania czy serwer dziala poprawnie.
    Zwraca prosty komunikat "ok".

    Zwraca:
        Tuple (kod_http, slownik_odpowiedzi)
    """
    return 200, {"status": "ok", "message": "Serwer dziala poprawnie"}


def handle_simulate(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint symulacji PV - glowna funkcjonalnosc aplikacji.

    Przyjmuje dane lokalizacji w formacie JSON, przeprowadza obliczenia
    i zwraca wynik symulacji.

    Parametry:
        body: cialo zapytania HTTP (bajty z JSON-em)

    Oczekiwany format JSON:
        {
            "latitude": 52.23,       (wymagane) szerokosc geograficzna
            "longitude": 21.01,      (wymagane) dlugosc geograficzna
            "peak_power_kw": 5.0,    (opcjonalne) moc paneli w kW
            "system_loss_percent": 14, (opcjonalne) straty w %
            "tilt_angle": 35,        (opcjonalne) kat nachylenia
            "azimuth_angle": 0,      (opcjonalne) azymut
            "location_name": "Warszawa" (opcjonalne) nazwa miejscowosci
        }

    Zwraca:
        Tuple (kod_http, slownik_odpowiedzi)
    """
    # Sprawdzenie czy otrzymalismy jakiekolwiek dane
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane lokalizacji w formacie JSON",
        }

    # Proba odczytania JSON z ciala zapytania
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych pol
    validation_error = _validate_input(data)
    if validation_error:
        return 400, {"error": "Blad walidacji", "message": validation_error}

    # Tworzenie obiektu danych wejsciowych
    try:
        input_data = SimulationInput(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            peak_power_kw=float(data.get("peak_power_kw", 5.0)),
            system_loss_percent=float(data.get("system_loss_percent", 14.0)),
            tilt_angle=float(data.get("tilt_angle", 35.0)),
            azimuth_angle=float(data.get("azimuth_angle", 0.0)),
            location_name=data.get("location_name"),
        )
    except (ValueError, TypeError) as e:
        return 400, {
            "error": "Nieprawidlowe dane",
            "message": f"Nie mozna przetworzyc danych: {e}",
        }

    # Przeprowadzenie obliczen
    try:
        result = calculate_annual_production(input_data)
        return 200, result.to_dict()
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Wystapil blad podczas obliczen: {e}",
        }


def _validate_input(data: dict) -> Optional[str]:
    """
    Sprawdza czy dane wejsciowe sa poprawne.

    Zwraca komunikat bledu lub None jesli wszystko jest ok.
    """
    # Sprawdzenie wymaganych pol
    if "latitude" not in data:
        return "Brak pola 'latitude' (szerokosc geograficzna)"
    if "longitude" not in data:
        return "Brak pola 'longitude' (dlugosc geograficzna)"

    # Sprawdzenie zakresow wartosci
    try:
        lat = float(data["latitude"])
        lon = float(data["longitude"])
    except (ValueError, TypeError):
        return "Szerokosc i dlugosc geograficzna musza byc liczbami"

    if not (-90 <= lat <= 90):
        return "Szerokosc geograficzna musi byc miedzy -90 a 90 stopni"
    if not (-180 <= lon <= 180):
        return "Dlugosc geograficzna musi byc miedzy -180 a 180 stopni"

    # Sprawdzenie opcjonalnych pol (jesli podane)
    if "peak_power_kw" in data:
        try:
            power = float(data["peak_power_kw"])
            if power <= 0:
                return "Moc paneli musi byc wieksza od 0"
            if power > 10000:
                return "Moc paneli nie moze przekraczac 10000 kW"
        except (ValueError, TypeError):
            return "Moc paneli musi byc liczba"

    if "system_loss_percent" in data:
        try:
            loss = float(data["system_loss_percent"])
            if not (0 <= loss <= 100):
                return "Straty systemowe musza byc miedzy 0 a 100%"
        except (ValueError, TypeError):
            return "Straty systemowe musza byc liczba"

    if "tilt_angle" in data:
        try:
            tilt = float(data["tilt_angle"])
            if not (0 <= tilt <= 90):
                return "Kat nachylenia musi byc miedzy 0 a 90 stopni"
        except (ValueError, TypeError):
            return "Kat nachylenia musi byc liczba"

    if "azimuth_angle" in data:
        try:
            azimuth = float(data["azimuth_angle"])
            if not (-180 <= azimuth <= 180):
                return "Azymut musi byc miedzy -180 a 180 stopni"
        except (ValueError, TypeError):
            return "Azymut musi byc liczba"

    return None


def handle_get_panels() -> Tuple[int, dict]:
    """
    Endpoint GET /api/panels - zwraca liste dostepnych modeli paneli PV.

    Zwraca:
        Tuple (kod_http, slownik z lista paneli)
    """
    try:
        panele = wczytaj_baze_paneli()
        return 200, {"panele": panele, "liczba": len(panele)}
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Nie udalo sie wczytac bazy paneli: {e}",
        }


def handle_get_inverters() -> Tuple[int, dict]:
    """
    Endpoint GET /api/inverters - zwraca liste dostepnych falownikow.

    Zwraca:
        Tuple (kod_http, slownik z lista falownikow)
    """
    try:
        falowniki = wczytaj_baze_falownikow()
        return 200, {"falowniki": falowniki, "liczba": len(falowniki)}
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Nie udalo sie wczytac bazy falownikow: {e}",
        }


def handle_get_batteries() -> Tuple[int, dict]:
    """
    Endpoint GET /api/batteries - zwraca liste dostepnych magazynow energii.

    Zwraca:
        Tuple (kod_http, slownik z lista baterii)
    """
    try:
        baterie = wczytaj_baze_baterii()
        return 200, {"baterie": baterie, "liczba": len(baterie)}
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Nie udalo sie wczytac bazy baterii: {e}",
        }


def handle_installation_configure(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/installation/configure - konfiguruje instalacje PV.

    Przyjmuje konfiguracje w formacie JSON, waliduje ja, oblicza
    rozmieszczenie paneli i zwraca pozycje 3D.

    Oczekiwany format JSON:
        {
            "panel_id": "ja_solar_jam72s30_550mr",  (wymagane)
            "orientacja": "pion",                    (opcjonalne, domyslnie "pion")
            "kat_nachylenia": 30,                    (opcjonalne, 15-60)
            "azymut": 0,                             (opcjonalne, 0=poludnie)
            "przeswit_nad_gruntem_cm": 50,          (opcjonalne, 20-100)
            "odstep_miedzy_rzedami_cm": 150,        (opcjonalne, 50-300)
            "odstep_boczny_cm": 3,                   (opcjonalne, 2-20)
            "liczba_paneli": 10,                     (wymagane)
            "liczba_kolumn": 5,                      (wymagane)
            "liczba_rzedow": 2                       (wymagane)
        }

    Zwraca:
        Tuple (kod_http, slownik z pozycjami paneli i parametrami)
    """
    # Sprawdzenie czy otrzymalismy dane
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij konfiguracje instalacji w formacie JSON",
        }

    # Parsowanie JSON
    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Sprawdzenie wymaganych pol
    if "panel_id" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'panel_id' jest wymagane",
        }
    if "liczba_paneli" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'liczba_paneli' jest wymagane",
        }
    if "liczba_kolumn" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'liczba_kolumn' jest wymagane",
        }
    if "liczba_rzedow" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'liczba_rzedow' jest wymagane",
        }

    # Tworzenie obiektu konfiguracji
    try:
        config = InstallationConfig(
            panel_id=str(data["panel_id"]),
            orientacja=str(data.get("orientacja", "pion")),
            kat_nachylenia=float(data.get("kat_nachylenia", 30.0)),
            azymut=float(data.get("azymut", 0.0)),
            przeswit_nad_gruntem_cm=float(data.get("przeswit_nad_gruntem_cm", 50.0)),
            odstep_miedzy_rzedami_cm=float(data.get("odstep_miedzy_rzedami_cm", 150.0)),
            odstep_boczny_cm=float(data.get("odstep_boczny_cm", 3.0)),
            liczba_paneli=int(data["liczba_paneli"]),
            liczba_kolumn=int(data["liczba_kolumn"]),
            liczba_rzedow=int(data["liczba_rzedow"]),
        )
    except (ValueError, TypeError) as e:
        return 400, {
            "error": "Nieprawidlowe dane",
            "message": f"Nie mozna przetworzyc konfiguracji: {e}",
        }

    # Walidacja konfiguracji
    blad = waliduj_konfiguracje(config)
    if blad:
        return 400, {"error": "Blad walidacji", "message": blad}

    # Obliczenie rozmieszczenia paneli
    try:
        layout = oblicz_rozmieszczenie(config)
        return 200, layout.to_dict()
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Wystapil blad podczas obliczen rozmieszczenia: {e}",
        }
