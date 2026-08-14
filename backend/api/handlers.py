"""
Handlery API - obsluguja zapytania HTTP przychodzace od frontendu.

Handler to funkcja, ktora:
1. Odbiera zapytanie od uzytkownika (np. dane lokalizacji)
2. Przetwarza je (wywoluje obliczenia)
3. Odsyla odpowiedz (wynik symulacji jako JSON)
"""

import json
from typing import Tuple, Optional, List

from backend.models.simulation import SimulationInput
from backend.models.installation import InstallationConfig
from backend.services.calculator import calculate_annual_production
from backend.services.installation_layout import (
    wczytaj_baze_paneli,
    wczytaj_baze_falownikow,
    wczytaj_baze_baterii,
    waliduj_konfiguracje,
    oblicz_rozmieszczenie,
    znajdz_panel,
)
from backend.services.solar_position import get_solar_position, _dzien_roku
from backend.services.shading import (
    BudynekConfig,
    oblicz_zacienienie_godzinowe,
    oblicz_zacienienie_pojedyncza_godzina,
)
from backend.services.panel_performance import (
    oblicz_roczna_produkcje_panela,
    oblicz_roczna_produkcje_instalacji,
    oblicz_wspolczynnik_zacienienia,
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    oblicz_wydajnosc_panela,
    oblicz_poa_tmy,
    oblicz_temperature_panela_tmy,
)
from backend.services.optimizer import (
    porownaj_z_bez_optymalizatorow,
    czy_optymalizatory_uzasadnione,
    podziel_na_stringi,
)
from backend.services.energy_profile import (
    ProfilZuzycia,
    stworz_profil_z_danych,
    oblicz_profil_godzinowy,
    oblicz_zuzycie_miesieczne,
)
from backend.services.economics import (
    analizuj_ekonomie,
    analizuj_ekonomie_net_billing,
    KonfiguracjaMagazynu,
    wczytaj_taryfy,
)
from backend.services.rce_prices import pobierz_statystyki_rce
from backend.services.report_generator import (
    KonfiguracjaRaportu,
    generuj_raport,
)
from backend.services.battery_sizing import dobierz_magazyn
from backend.services.scenario_comparison import (
    porownaj_scenariusze,
    KonfiguracjaScenariusza,
    oblicz_scenariusz,
)
from backend.services.pvgis import pobierz_dane_tmy
from backend.services.parcel_positioning import (
    oblicz_pozycje_obiektu,
    oblicz_odleglosc_od_granic,
)


def handle_solar_position(query_params: dict) -> Tuple[int, dict]:
    """
    Endpoint GET /api/solar-position - oblicza pozycje Slonca.

    Przyjmuje parametry zapytania (lat, lon, rok, miesiac, dzien, godzina, minuta)
    i zwraca azymut oraz elewacje Slonca.

    Parametry:
        query_params: slownik z parametrami zapytania (parse_qs)

    Zwraca:
        Tuple (kod_http, slownik_odpowiedzi z azymut i elewacja)
    """
    # Lista wymaganych parametrow
    wymagane = ["lat", "lon", "rok", "miesiac", "dzien", "godzina", "minuta"]

    # Sprawdzenie czy wszystkie wymagane parametry sa obecne
    brakujace = [p for p in wymagane if p not in query_params]
    if brakujace:
        return 400, {
            "error": "Brak parametrow",
            "message": f"Brakujace parametry: {', '.join(brakujace)}",
        }

    # Parsowanie i walidacja parametrow
    try:
        lat = float(query_params["lat"][0])
        lon = float(query_params["lon"][0])
        rok = int(query_params["rok"][0])
        miesiac = int(query_params["miesiac"][0])
        dzien = int(query_params["dzien"][0])
        godzina = int(query_params["godzina"][0])
        minuta = int(query_params["minuta"][0])
    except (ValueError, TypeError, IndexError):
        return 400, {
            "error": "Nieprawidlowe parametry",
            "message": "Parametry lat, lon musza byc liczbami zmiennoprzecinkowymi; rok, miesiac, dzien, godzina, minuta musza byc liczbami calkowitymi",
        }

    # Walidacja zakresow
    if not (-90 <= lat <= 90):
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Szerokosc geograficzna (lat) musi byc miedzy -90 a 90",
        }
    if not (-180 <= lon <= 180):
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Dlugosc geograficzna (lon) musi byc miedzy -180 a 180",
        }
    if miesiac < 1 or miesiac > 12:
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Miesiac musi byc miedzy 1 a 12",
        }
    if dzien < 1 or dzien > 31:
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Dzien musi byc miedzy 1 a 31",
        }
    if godzina < 0 or godzina > 23:
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Godzina musi byc miedzy 0 a 23",
        }
    if minuta < 0 or minuta > 59:
        return 400, {
            "error": "Nieprawidlowa wartosc",
            "message": "Minuta musi byc miedzy 0 a 59",
        }

    # Oblicz pozycje Slonca
    try:
        azymut, elewacja = get_solar_position(
            lat, lon, rok, miesiac, dzien, godzina, minuta
        )
        return 200, {
            "azymut": round(azymut, 2),
            "elewacja": round(elewacja, 2),
        }
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania pozycji slonca: {e}",
        }


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
            "odstep_boczny_cm": 3,                   (opcjonalne, 2-20)
            "liczba_paneli": 10                      (wymagane)
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

    # Tworzenie obiektu konfiguracji (jedna tafla - wszystkie panele w jednym rzedzie)
    try:
        liczba_paneli = int(data["liczba_paneli"])
        config = InstallationConfig(
            panel_id=str(data["panel_id"]),
            orientacja=str(data.get("orientacja", "pion")),
            kat_nachylenia=float(data.get("kat_nachylenia", 30.0)),
            azymut=float(data.get("azymut", 0.0)),
            przeswit_nad_gruntem_cm=float(data.get("przeswit_nad_gruntem_cm", 50.0)),
            odstep_boczny_cm=float(data.get("odstep_boczny_cm", 3.0)),
            liczba_paneli=liczba_paneli,
            liczba_rzedow=int(data.get("liczba_rzedow", 1)),
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


def handle_shading_simulate(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/shading/simulate - symulacja zacienienia i produkcji rocznej.

    Przyjmuje konfiguracje instalacji, pozycje budynku i lokalizacje,
    oblicza zacienienie godzinowe przez caly rok i zwraca raport.

    Oczekiwany format JSON:
        {
            "instalacja": {
                "panel_id": "ja_solar_jam72s30_550mr",
                "orientacja": "pion",
                "kat_nachylenia": 30,
                "azymut": 0,
                "przeswit_nad_gruntem_cm": 50,
                "odstep_boczny_cm": 3,
                "liczba_paneli": 10
            },
            "budynek": {
                "x": 0.0,
                "z": -10.0,
                "szerokosc": 10.0,
                "glebokosc": 8.0,
                "wysokosc": 8.0
            },
            "lokalizacja": {
                "szerokosc_geo": 52.23,
                "dlugosc_geo": 21.01,
                "strefa_czasowa": 1.0
            },
            "opcje": {
                "rok": 2025,
                "optymalizatory": false,
                "rok_eksploatacji": 1,
                "straty_systemowe": 0.03
            }
        }

    Zwraca:
        Raport z produkcja roczna, miesieczna, stratami i rekomendacja optymalizatorow.
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij konfiguracje symulacji zacienienia w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych sekcji
    if "instalacja" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Sekcja 'instalacja' jest wymagana",
        }

    inst = data["instalacja"]
    for pole in ["panel_id", "liczba_paneli"]:
        if pole not in inst:
            return 400, {
                "error": "Blad walidacji",
                "message": f"Pole 'instalacja.{pole}' jest wymagane",
            }

    # Konfiguracja instalacji (jedna tafla - wszystkie panele w jednym rzedzie)
    try:
        liczba_paneli = int(inst["liczba_paneli"])
        config = InstallationConfig(
            panel_id=str(inst["panel_id"]),
            orientacja=str(inst.get("orientacja", "pion")),
            kat_nachylenia=float(inst.get("kat_nachylenia", 30.0)),
            azymut=float(inst.get("azymut", 0.0)),
            przeswit_nad_gruntem_cm=float(inst.get("przeswit_nad_gruntem_cm", 50.0)),
            odstep_boczny_cm=float(inst.get("odstep_boczny_cm", 3.0)),
            liczba_paneli=liczba_paneli,
            liczba_rzedow=int(inst.get("liczba_rzedow", 1)),
        )
    except (ValueError, TypeError) as e:
        return 400, {
            "error": "Nieprawidlowe dane",
            "message": f"Nie mozna przetworzyc konfiguracji instalacji: {e}",
        }

    # Walidacja konfiguracji
    blad = waliduj_konfiguracje(config)
    if blad:
        return 400, {"error": "Blad walidacji", "message": blad}

    # Konfiguracja budynku
    bud = data.get("budynek", {})
    budynek = BudynekConfig(
        x=float(bud.get("x", 0.0)),
        z=float(bud.get("z", -10.0)),
        szerokosc=float(bud.get("szerokosc", 10.0)),
        glebokosc=float(bud.get("glebokosc", 8.0)),
        wysokosc=float(bud.get("wysokosc", 8.0)),
    )

    # Lokalizacja
    lok = data.get("lokalizacja", {})
    szerokosc_geo = float(lok.get("szerokosc_geo", 52.23))
    dlugosc_geo = float(lok.get("dlugosc_geo", 21.01))
    strefa_czasowa = float(lok["strefa_czasowa"]) if "strefa_czasowa" in lok else None

    # Opcje
    opcje = data.get("opcje", {})
    rok = int(opcje.get("rok", 2025))
    z_optymalizatorami = bool(opcje.get("optymalizatory", False))
    rok_eksploatacji = int(opcje.get("rok_eksploatacji", 1))
    straty_systemowe = float(opcje.get("straty_systemowe", 0.03))
    falownik_id = opcje.get("falownik_id", None)

    # Oblicz rozmieszczenie paneli
    try:
        layout = oblicz_rozmieszczenie(config)
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad rozmieszczenia paneli: {e}",
        }

    # Pobierz dane panela z bazy
    panel_dane = znajdz_panel(config.panel_id)
    if panel_dane is None:
        return 400, {
            "error": "Blad walidacji",
            "message": f"Nie znaleziono panela '{config.panel_id}'",
        }

    technologia = panel_dane.get("technologia", "standard")
    liczba_sekcji = panel_dane.get("liczba_sekcji_bypass", 3)
    moc_stc = panel_dane["moc_wp"]
    wsp_temp = panel_dane["wspolczynnik_temp_pmax"]
    degradacja = panel_dane.get("degradacja_roczna_procent", 0.5) / 100.0

    # Oblicz zacienienie godzinowe (pelny rok)
    try:
        zacienienia = oblicz_zacienienie_godzinowe(
            layout.panele, budynek,
            szerokosc_geo, dlugosc_geo, rok,
            config.kat_nachylenia, liczba_sekcji, technologia,
            strefa_czasowa
        )
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania zacienienia: {e}",
        }

    # Oblicz roczna produkcje kazdego panela
    try:
        # Probuj zaladowac dane TMY z cache (jesli wczesniej pobrano)
        dane_tmy = pobierz_dane_tmy(szerokosc_geo, dlugosc_geo, uzyj_cache=True)
        ostrzezenie_tmy = None
        if dane_tmy is None:
            ostrzezenie_tmy = "Brak danych TMY - uzywam przyblizonego modelu. Pobierz dane pogodowe dla dokladniejszych wynikow."

        # Konfiguracja stringow na podstawie falownika
        stringi = None
        falownik_info = None
        moc_nom_falownika = None

        if falownik_id:
            # Wczytaj dane falownika z bazy
            falowniki = wczytaj_baze_falownikow()
            falownik_dane = None
            for f in falowniki:
                if f.get("id") == falownik_id:
                    falownik_dane = f
                    break

            if falownik_dane:
                zakres_mppt = falownik_dane.get("zakres_mppt_v", {})
                mppt_min = float(zakres_mppt.get("min", 0))
                mppt_max = float(zakres_mppt.get("max", 0))
                napiecie_mpp = panel_dane.get("napiecie_mpp", 0)
                moc_nom_falownika = float(falownik_dane.get("moc_wyjsciowa_ac", 0))

                if napiecie_mpp > 0 and mppt_min > 0 and mppt_max > 0:
                    stringi = podziel_na_stringi(
                        config.liczba_paneli,
                        napiecie_mpp,
                        mppt_min,
                        mppt_max,
                    )
                    falownik_info = {
                        "id": falownik_id,
                        "nazwa": falownik_dane.get("nazwa", falownik_id),
                        "zakres_mppt_min_v": mppt_min,
                        "zakres_mppt_max_v": mppt_max,
                        "moc_wyjsciowa_ac_w": moc_nom_falownika,
                        "napiecie_mpp_panela_v": napiecie_mpp,
                    }

        # Jesli mamy stringi (falownik podany) - uzywamy modelu instalacji
        if stringi:
            wynik_instalacji = oblicz_roczna_produkcje_instalacji(
                panele_wyniki_zacienienia=zacienienia,
                moc_stc=moc_stc,
                wsp_temp=wsp_temp,
                technologia=technologia,
                liczba_sekcji=liczba_sekcji,
                dane_tmy=dane_tmy,
                kat_nachylenia=config.kat_nachylenia,
                azymut_panela=config.azymut,
                straty_systemowe=straty_systemowe,
                degradacja=degradacja,
                rok_eksploatacji=rok_eksploatacji,
                stringi=stringi,
                z_optymalizatorami=z_optymalizatorami,
                moc_nominalna_falownika_w=moc_nom_falownika,
                noct=panel_dane.get("noct", 45.0),
                bifacial=panel_dane.get("bifacial", False),
                bifacial_wspolczynnik=panel_dane.get("bifacial_wspolczynnik", 0.0),
                przeswit_nad_gruntem_m=config.przeswit_nad_gruntem_cm / 100.0,
            )

            energia_roczna_total = wynik_instalacji["roczna_kwh"]
            energia_miesieczna = wynik_instalacji["miesieczna_kwh"]
            energia_bez_zacien_total = wynik_instalacji.get("energia_bez_zacienienia_kwh", energia_roczna_total)
            energia_bez_zacien_miesieczna = wynik_instalacji.get("energia_bez_zacienienia_miesieczna_kwh", energia_miesieczna)
            strata_total = wynik_instalacji.get("strata_zacienienie_mismatch_procent", 0.0)

            # Ocena optymalizatorow
            ocena_optymalizatorow = czy_optymalizatory_uzasadnione(
                strata_total, config.liczba_paneli, moc_stc
            )

            raport = {
                "podsumowanie": {
                    "energia_roczna_kwh": round(energia_roczna_total, 2),
                    "energia_bez_zacienienia_kwh": round(energia_bez_zacien_total, 2),
                    "strata_zacienienie_procent": round(strata_total, 2),
                    "moc_instalacji_kwp": layout.moc_calkowita_kwp,
                    "liczba_paneli": config.liczba_paneli,
                    "rok": rok,
                    "rok_eksploatacji": rok_eksploatacji,
                    "zrodlo_danych": "tmy" if dane_tmy else "fallback",
                    "z_optymalizatorami": z_optymalizatorami,
                },
                "energia_miesieczna_kwh": [round(e, 2) for e in energia_miesieczna],
                "energia_bez_zacienienia_miesieczna_kwh": [round(e, 2) for e in energia_bez_zacien_miesieczna],
                "stringi": wynik_instalacji.get("stringi_info", []),
                "optymalizatory": ocena_optymalizatorow,
                "falownik": falownik_info,
                "parametry": {
                    "panel_id": config.panel_id,
                    "technologia": technologia,
                    "liczba_sekcji_bypass": liczba_sekcji,
                    "straty_systemowe_procent": straty_systemowe * 100,
                    "degradacja_roczna_procent": degradacja * 100,
                    "lokalizacja": {
                        "szerokosc_geo": szerokosc_geo,
                        "dlugosc_geo": dlugosc_geo,
                    },
                },
            }

            if ostrzezenie_tmy:
                raport["ostrzezenie"] = ostrzezenie_tmy

            return 200, raport

        # Brak falownika - standardowy model per-panel (kazdy niezaleznie)
        wyniki_paneli = []
        for panel in layout.panele:
            wynik = oblicz_roczna_produkcje_panela(
                moc_stc, wsp_temp, technologia, liczba_sekcji,
                zacienienia, panel.index,
                szerokosc_geo, straty_systemowe, degradacja, rok_eksploatacji,
                kat_nachylenia=config.kat_nachylenia,
                azymut_panela=config.azymut,
                dane_tmy=dane_tmy,
                bifacial=panel_dane.get("bifacial", False),
                bifacial_wspolczynnik=panel_dane.get("bifacial_wspolczynnik", 0.0),
                przeswit_nad_gruntem_m=config.przeswit_nad_gruntem_cm / 100.0,
            )
            wyniki_paneli.append(wynik)

        # Sumaryczne wyniki
        energia_roczna_total = sum(w["energia_roczna_kwh"] for w in wyniki_paneli)
        energia_bez_zacien_total = sum(w["energia_bez_zacienienia_kwh"] for w in wyniki_paneli)
        strata_total = 0.0
        if energia_bez_zacien_total > 0:
            strata_total = (1.0 - energia_roczna_total / energia_bez_zacien_total) * 100.0

        # Energia miesieczna sumaryczna
        energia_miesieczna = [0.0] * 12
        energia_bez_zacien_miesieczna = [0.0] * 12
        for w in wyniki_paneli:
            for i in range(12):
                energia_miesieczna[i] += w["energia_miesieczna_kwh"][i]
                if "energia_bez_zacienienia_miesieczna_kwh" in w:
                    energia_bez_zacien_miesieczna[i] += w["energia_bez_zacienienia_miesieczna_kwh"][i]

        # Ocena optymalizatorow
        ocena_optymalizatorow = czy_optymalizatory_uzasadnione(
            strata_total, config.liczba_paneli, moc_stc
        )

        raport = {
            "podsumowanie": {
                "energia_roczna_kwh": round(energia_roczna_total, 2),
                "energia_bez_zacienienia_kwh": round(energia_bez_zacien_total, 2),
                "strata_zacienienie_procent": round(strata_total, 2),
                "moc_instalacji_kwp": layout.moc_calkowita_kwp,
                "liczba_paneli": config.liczba_paneli,
                "rok": rok,
                "rok_eksploatacji": rok_eksploatacji,
                "zrodlo_danych": "tmy" if dane_tmy else "fallback",
            },
            "energia_miesieczna_kwh": [round(e, 2) for e in energia_miesieczna],
            "energia_bez_zacienienia_miesieczna_kwh": [round(e, 2) for e in energia_bez_zacien_miesieczna],
            "panele": wyniki_paneli,
            "optymalizatory": ocena_optymalizatorow,
            "parametry": {
                "panel_id": config.panel_id,
                "technologia": technologia,
                "liczba_sekcji_bypass": liczba_sekcji,
                "straty_systemowe_procent": straty_systemowe * 100,
                "degradacja_roczna_procent": degradacja * 100,
                "lokalizacja": {
                    "szerokosc_geo": szerokosc_geo,
                    "dlugosc_geo": dlugosc_geo,
                },
            },
        }

        # Dodaj ostrzezenie jesli brak danych TMY
        if ostrzezenie_tmy:
            raport["ostrzezenie"] = ostrzezenie_tmy

        return 200, raport

    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania produkcji: {e}",
        }


def handle_tmy_fetch(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/tmy/fetch - pobiera dane TMY z PVGIS.

    Pobiera dane Typical Meteorological Year dla podanych wspolrzednych
    i cache'uje je lokalnie do wykorzystania w symulacji.

    Oczekiwany format JSON:
        {
            "latitude": 52.23,
            "longitude": 21.01
        }

    Zwraca:
        Podsumowanie danych TMY (roczne GHI, status)
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij wspolrzedne w formacie JSON (latitude, longitude)",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wspolrzednych
    if "latitude" not in data or "longitude" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Wymagane pola: 'latitude' i 'longitude'",
        }

    try:
        lat = float(data["latitude"])
        lon = float(data["longitude"])
    except (ValueError, TypeError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Szerokosc i dlugosc geograficzna musza byc liczbami",
        }

    if not (-90 <= lat <= 90):
        return 400, {
            "error": "Blad walidacji",
            "message": "Szerokosc geograficzna musi byc miedzy -90 a 90",
        }
    if not (-180 <= lon <= 180):
        return 400, {
            "error": "Blad walidacji",
            "message": "Dlugosc geograficzna musi byc miedzy -180 a 180",
        }

    # Pobierz dane TMY
    try:
        dane_tmy = pobierz_dane_tmy(lat, lon, uzyj_cache=True)
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad pobierania danych TMY: {e}",
        }

    if dane_tmy is None:
        return 502, {
            "error": "Blad PVGIS",
            "message": "Nie udalo sie pobrac danych TMY z PVGIS. Sprawdz polaczenie internetowe.",
        }

    return 200, {
        "status": "ok",
        "message": "Dane TMY pobrane pomyslnie",
        "roczne_ghi_kwh_m2": dane_tmy["roczne_ghi_kwh_m2"],
        "lokalizacja": {
            "latitude": lat,
            "longitude": lon,
        },
    }


def handle_energy_profile(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/energy-profile - generuje profil zuzycia energii.

    Przyjmuje dane profilu zuzycia uzytkownika i zwraca godzinowe zuzycie
    na caly rok (8760 wartosci) oraz podsumowanie miesieczne.

    Oczekiwany format JSON:
        {
            "zuzycie_bazowe_w": 200,
            "zuzycie_godzinowe_roboczy": [0, 0, ..., 500, 800, ...],  (24 wartosci Wh)
            "zuzycie_godzinowe_wolny": [0, 0, ..., 300, 600, ...],    (24 wartosci Wh)
            "pompa_ciepla_co": true,
            "zuzycie_co_roczne_kwh": 8000,
            "pompa_ciepla_cwu": true,
            "zuzycie_cwu_roczne_kwh": 2500,
            "rok": 2025
        }

    Zwraca:
        Profil godzinowy (8760 wartosci Wh) i zuzycie miesieczne (kWh)
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane profilu zuzycia w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    rok = int(data.get("rok", 2025))
    taryfa = str(data.get("taryfa", "G11"))

    try:
        profil = stworz_profil_z_danych(data)
        profil_godzinowy = oblicz_profil_godzinowy(profil, rok, taryfa=taryfa)
        zuzycie_miesieczne = oblicz_zuzycie_miesieczne(profil_godzinowy, rok)
        zuzycie_roczne = sum(zuzycie_miesieczne)

        return 200, {
            "profil_godzinowy_wh": profil_godzinowy,
            "zuzycie_miesieczne_kwh": zuzycie_miesieczne,
            "zuzycie_roczne_kwh": round(zuzycie_roczne, 2),
            "rok": rok,
            "parametry": {
                "zuzycie_bazowe_w": profil.zuzycie_bazowe_w,
                "pompa_ciepla_co": profil.pompa_ciepla_co,
                "zuzycie_co_roczne_kwh": profil.zuzycie_co_roczne_kwh,
                "pompa_ciepla_cwu": profil.pompa_ciepla_cwu,
                "zuzycie_cwu_roczne_kwh": profil.zuzycie_cwu_roczne_kwh,
                "moc_pompy_ciepla_kw": profil.moc_pompy_ciepla_kw,
                "taryfa": taryfa,
            },
        }
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania profilu zuzycia: {e}",
        }


def handle_economics_analyze(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/economics/analyze - analiza ekonomiczna instalacji PV.

    Przyjmuje profil zuzycia, produkcje PV, taryfe i konfiguracje magazynu.
    Zwraca pena analize kosztow, oszczednosci i przychodow ze sprzedazy.

    UWAGA: Magazyn moze byc ladowany TYLKO z PV. Arbitraz cenowy niemozliwy.

    Oczekiwany format JSON:
        {
            "produkcja_godzinowa_wh": [...],   (8760 wartosci lub energia_miesieczna_kwh)
            "energia_miesieczna_kwh": [100, 150, ...],  (12 wartosci - alternatywa)
            "zuzycie_godzinowe_wh": [...],     (8760 wartosci lub profil_zuzycia)
            "profil_zuzycia": { ... },         (dane profilu - alternatywa)
            "taryfa": "G11",                   ("G11", "G11f_dynamiczna", "G11_dynamiczna")
            "magazyn": {
                "pojemnosc_kwh": 10.0,
                "moc_ladowania_kw": 5.0,
                "moc_rozladowania_kw": 5.0,
                "sprawnosc_procent": 95.0,
                "godzina_sprzedazy": 18,
                "priorytet": "autokonsumpcja"
            },
            "rok": 2025
        }

    Zwraca:
        Wyniki analizy ekonomicznej (bilans miesieczny i roczny)
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane do analizy ekonomicznej w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    rok = int(data.get("rok", 2025))
    taryfa = str(data.get("taryfa", "G11"))

    if taryfa not in ("G11", "G11f_dynamiczna", "G11_dynamiczna"):
        return 400, {
            "error": "Blad walidacji",
            "message": "Taryfa musi byc jedna z: G11, G11f_dynamiczna, G11_dynamiczna",
        }

    # Produkcja PV - albo godzinowa (8760) albo miesieczna (12)
    produkcja_godzinowa = data.get("produkcja_godzinowa_wh")
    if produkcja_godzinowa is None:
        energia_miesieczna = data.get("energia_miesieczna_kwh")
        if energia_miesieczna is None:
            return 400, {
                "error": "Blad walidacji",
                "message": "Wymagane pole 'produkcja_godzinowa_wh' lub 'energia_miesieczna_kwh'",
            }
        # Rozloz energie miesieczna na godziny (uproszczony profil solarny)
        produkcja_godzinowa = _rozloz_produkcje_na_godziny(energia_miesieczna, rok)

    # Zuzycie - albo godzinowe (8760) albo z profilu
    zuzycie_godzinowe = data.get("zuzycie_godzinowe_wh")
    if zuzycie_godzinowe is None:
        profil_dane = data.get("profil_zuzycia")
        if profil_dane is None:
            return 400, {
                "error": "Blad walidacji",
                "message": "Wymagane pole 'zuzycie_godzinowe_wh' lub 'profil_zuzycia'",
            }
        profil = stworz_profil_z_danych(profil_dane)
        zuzycie_godzinowe = oblicz_profil_godzinowy(profil, rok, taryfa=taryfa)

    # Konfiguracja magazynu
    magazyn = None
    magazyn_dane = data.get("magazyn")
    if magazyn_dane:
        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=float(magazyn_dane.get("pojemnosc_kwh", 0.0)),
            moc_ladowania_kw=float(magazyn_dane.get("moc_ladowania_kw", 0.0)),
            moc_rozladowania_kw=float(magazyn_dane.get("moc_rozladowania_kw", 0.0)),
            sprawnosc_procent=float(magazyn_dane.get("sprawnosc_procent", 95.0)),
            godzina_sprzedazy=int(magazyn_dane.get("godzina_sprzedazy", 18)),
            priorytet=str(magazyn_dane.get("priorytet", "autokonsumpcja")),
        )

    # Tryb rozliczenia i marza sprzedawcy
    tryb_rozliczenia = str(data.get("tryb_rozliczenia", "sprzedaz_bezposrednia"))
    marza_sprzedawcy = float(data.get("marza_sprzedawcy", 0.03))

    # Walidacja marzy
    if marza_sprzedawcy < 0 or marza_sprzedawcy > 0.10:
        return 400, {
            "error": "Blad walidacji",
            "message": "Marza sprzedawcy musi byc miedzy 0 a 0.10 PLN/kWh",
        }

    try:
        if tryb_rozliczenia == "net_billing_depozyt":
            wynik = analizuj_ekonomie_net_billing(
                produkcja_godzinowa_wh=produkcja_godzinowa,
                zuzycie_godzinowe_wh=zuzycie_godzinowe,
                taryfa=taryfa,
                magazyn=magazyn,
                rok=rok,
                marza_sprzedawcy=marza_sprzedawcy,
            )
        else:
            wynik = analizuj_ekonomie(
                produkcja_godzinowa_wh=produkcja_godzinowa,
                zuzycie_godzinowe_wh=zuzycie_godzinowe,
                taryfa=taryfa,
                magazyn=magazyn,
                rok=rok,
                marza_sprzedawcy=marza_sprzedawcy,
            )
        return 200, wynik
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad analizy ekonomicznej: {e}",
        }


def handle_get_tariffs() -> Tuple[int, dict]:
    """
    Endpoint GET /api/tariffs - zwraca dostepne taryfy energetyczne.

    Zwraca:
        Slownik z taryfami i statystykami RCE
    """
    try:
        taryfy = wczytaj_taryfy()
        statystyki_rce = pobierz_statystyki_rce()
        return 200, {"taryfy": taryfy, "ceny_rce": statystyki_rce}
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Nie udalo sie wczytac taryf: {e}",
        }


def handle_report_generate(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/report/generate - generuje kompletny raport instalacji PV.

    Przyjmuje pelna konfiguracje (instalacja + profil + taryfa + magazyn)
    i zwraca raport z produkcja, stratami, bilansem, rekomendacjami
    i projekcja degradacji na 25 lat.

    Oczekiwany format JSON:
        {
            "produkcja_miesieczna_kwh": [100, 150, ...],    (12 wartosci)
            "produkcja_bez_zacienienia_kwh": [110, 160, ...], (12 wartosci)
            "zuzycie_miesieczne_kwh": [400, 380, ...],      (12 wartosci)
            "pojemnosc_magazynu_kwh": 10.0,                 (opcjonalne)
            "sprawnosc_magazynu_procent": 95.0,             (opcjonalne)
            "kat_nachylenia": 30.0,                         (opcjonalne)
            "azymut": 0.0,                                  (opcjonalne)
            "moc_instalacji_kwp": 5.5,                      (opcjonalne)
            "degradacja_roczna_procent": 0.5,               (opcjonalne)
            "taryfa": "G11"                                 (opcjonalne)
        }

    Zwraca:
        Kompletny raport JSON
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane do generowania raportu w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych pol
    if "produkcja_miesieczna_kwh" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'produkcja_miesieczna_kwh' jest wymagane (12 wartosci)",
        }
    if "zuzycie_miesieczne_kwh" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'zuzycie_miesieczne_kwh' jest wymagane (12 wartosci)",
        }

    produkcja = data["produkcja_miesieczna_kwh"]
    if len(produkcja) != 12:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'produkcja_miesieczna_kwh' musi miec dokladnie 12 wartosci",
        }

    zuzycie = data["zuzycie_miesieczne_kwh"]
    if len(zuzycie) != 12:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'zuzycie_miesieczne_kwh' musi miec dokladnie 12 wartosci",
        }

    # Produkcja bez zacienienia - jesli nie podano, uzyj produkcji (brak strat)
    produkcja_bez = data.get("produkcja_bez_zacienienia_kwh", produkcja)
    if len(produkcja_bez) != 12:
        produkcja_bez = produkcja

    try:
        config = KonfiguracjaRaportu(
            produkcja_miesieczna_kwh=[float(x) for x in produkcja],
            produkcja_bez_zacienienia_kwh=[float(x) for x in produkcja_bez],
            zuzycie_miesieczne_kwh=[float(x) for x in zuzycie],
            pojemnosc_magazynu_kwh=float(data.get("pojemnosc_magazynu_kwh", 0.0)),
            sprawnosc_magazynu_procent=float(data.get("sprawnosc_magazynu_procent", 95.0)),
            kat_nachylenia=float(data.get("kat_nachylenia", 30.0)),
            azymut=float(data.get("azymut", 0.0)),
            moc_instalacji_kwp=float(data.get("moc_instalacji_kwp", 5.0)),
            degradacja_roczna_procent=float(data.get("degradacja_roczna_procent", 0.5)),
            taryfa=str(data.get("taryfa", "G11")),
        )

        # Dobor magazynu energii
        dobor_magazynu = dobierz_magazyn(
            config.produkcja_miesieczna_kwh,
            config.zuzycie_miesieczne_kwh,
        )

        # Generowanie raportu
        raport = generuj_raport(config)
        raport["dobor_magazynu"] = dobor_magazynu

        return 200, raport

    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad generowania raportu: {e}",
        }


def handle_scenarios_compare(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/scenarios/compare - porownuje scenariusze side-by-side.

    Przyjmuje dane produkcji i zuzycia, zwraca tabele porownawcza
    scenariuszy (bez PV, z PV, z magazynem, rozne katy, rozne taryfy).

    Oczekiwany format JSON:
        {
            "produkcja_miesieczna_kwh": [100, 150, ...],    (12 wartosci)
            "zuzycie_miesieczne_kwh": [400, 380, ...],      (12 wartosci)
            "kat_nachylenia": 30.0,                         (opcjonalne)
            "koszt_instalacji_zl": 30000,                   (opcjonalne)
            "koszt_magazynu_zl": 15000,                     (opcjonalne)
            "pojemnosc_magazynu_kwh": 10.0,                 (opcjonalne)
            "sprawnosc_magazynu_procent": 95.0,             (opcjonalne)
            "strata_zacienienia_procent": 5.0,              (opcjonalne)
            "rok": 2025                                     (opcjonalne)
        }

    Zwraca:
        Tabela porownawcza scenariuszy
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane do porownania scenariuszy w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja
    if "produkcja_miesieczna_kwh" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'produkcja_miesieczna_kwh' jest wymagane (12 wartosci)",
        }
    if "zuzycie_miesieczne_kwh" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'zuzycie_miesieczne_kwh' jest wymagane (12 wartosci)",
        }

    produkcja = data["produkcja_miesieczna_kwh"]
    zuzycie = data["zuzycie_miesieczne_kwh"]

    if len(produkcja) != 12 or len(zuzycie) != 12:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pola produkcji i zuzycia musza miec po 12 wartosci (miesiace)",
        }

    try:
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=[float(x) for x in produkcja],
            zuzycie_miesieczne_kwh=[float(x) for x in zuzycie],
            kat_nachylenia=float(data.get("kat_nachylenia", 30.0)),
            koszt_instalacji_zl=float(data.get("koszt_instalacji_zl", 30000.0)),
            koszt_magazynu_zl=float(data.get("koszt_magazynu_zl", 15000.0)),
            pojemnosc_magazynu_kwh=float(data.get("pojemnosc_magazynu_kwh", 10.0)),
            sprawnosc_magazynu_procent=float(data.get("sprawnosc_magazynu_procent", 95.0)),
            strata_zacienienia_procent=float(data.get("strata_zacienienia_procent", 5.0)),
            rok=int(data.get("rok", 2025)),
        )
        return 200, wynik
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad porownania scenariuszy: {e}",
        }


def _rozloz_produkcje_na_godziny(energia_miesieczna_kwh: List[float], rok: int = 2025) -> List[float]:
    """
    Rozklada miesieczna produkcje PV na godziny (uproszczony profil solarny).

    Profil solarny: produkcja glownie 6-20, szczyt 10-14.
    Rozklad proporcjonalny do typowego nasycenia promieniowaniem.

    Parametry:
        energia_miesieczna_kwh: 12 wartosci produkcji [kWh]
        rok: rok

    Zwraca:
        Lista 8760 wartosci produkcji w Wh
    """
    import calendar

    # Profil godzinowy produkcji solarnej (normalizowany do sumy 1.0)
    profil_solarny = [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.01, 0.03, 0.06, 0.09, 0.12,
        0.14, 0.15, 0.15, 0.14, 0.12, 0.09, 0.06, 0.03, 0.01, 0.0,
        0.0, 0.0, 0.0, 0.0
    ]
    suma_profilu = sum(profil_solarny)
    if suma_profilu > 0:
        profil_solarny = [p / suma_profilu for p in profil_solarny]

    wynik = []
    for miesiac in range(1, 13):
        energia_mc_kwh = energia_miesieczna_kwh[miesiac - 1] if miesiac - 1 < len(energia_miesieczna_kwh) else 0.0
        dni = calendar.monthrange(rok, miesiac)[1]
        energia_dzien_wh = (energia_mc_kwh * 1000.0) / dni

        for dzien in range(dni):
            for godzina in range(24):
                produkcja_wh = energia_dzien_wh * profil_solarny[godzina]
                wynik.append(round(produkcja_wh, 2))

    return wynik


def handle_shading_single_hour(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/shading/single-hour - oblicza zacienienie i produkcje
    dla pojedynczej godziny.

    Oczekiwany format JSON:
        {
            "data": "2025-06-15",
            "godzina": 12,
            "instalacja": { ... },
            "budynek": { ... },
            "lokalizacja": { "szerokosc_geo": 52.23, "dlugosc_geo": 21.01 }
        }

    Zwraca:
        JSON z pozycja slonca, zacienieniem per panel i produkcja.
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij konfiguracje w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych pol
    if "data" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'data' (data w formacie YYYY-MM-DD) jest wymagane",
        }
    if "godzina" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'godzina' (0-23) jest wymagane",
        }
    if "instalacja" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Sekcja 'instalacja' jest wymagana",
        }
    if "lokalizacja" not in data:
        return 400, {
            "error": "Blad walidacji",
            "message": "Sekcja 'lokalizacja' jest wymagana",
        }

    # Parsowanie daty
    data_str = str(data["data"])
    try:
        parts = data_str.split("-")
        rok = int(parts[0])
        miesiac = int(parts[1])
        dzien = int(parts[2])
    except (IndexError, ValueError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'data' musi byc w formacie YYYY-MM-DD",
        }

    # Walidacja godziny
    try:
        godzina = int(data["godzina"])
    except (ValueError, TypeError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'godzina' musi byc liczba calkowita 0-23",
        }
    if godzina < 0 or godzina > 23:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'godzina' musi byc miedzy 0 a 23",
        }

    # Walidacja miesiaca i dnia
    if miesiac < 1 or miesiac > 12:
        return 400, {
            "error": "Blad walidacji",
            "message": "Miesiac musi byc miedzy 1 a 12",
        }
    if dzien < 1 or dzien > 31:
        return 400, {
            "error": "Blad walidacji",
            "message": "Dzien musi byc miedzy 1 a 31",
        }

    # Parsowanie instalacji
    inst = data["instalacja"]
    if "panel_id" not in inst:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'instalacja.panel_id' jest wymagane",
        }
    if "liczba_paneli" not in inst:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'instalacja.liczba_paneli' jest wymagane",
        }

    try:
        config = InstallationConfig(
            panel_id=str(inst["panel_id"]),
            orientacja=str(inst.get("orientacja", "pion")),
            kat_nachylenia=float(inst.get("kat_nachylenia", 30.0)),
            azymut=float(inst.get("azymut", 0.0)),
            przeswit_nad_gruntem_cm=float(inst.get("przeswit_nad_gruntem_cm", 50.0)),
            odstep_boczny_cm=float(inst.get("odstep_boczny_cm", 3.0)),
            liczba_paneli=int(inst["liczba_paneli"]),
            liczba_rzedow=int(inst.get("liczba_rzedow", 1)),
        )
    except (ValueError, TypeError) as e:
        return 400, {
            "error": "Nieprawidlowe dane",
            "message": f"Nie mozna przetworzyc konfiguracji instalacji: {e}",
        }

    blad = waliduj_konfiguracje(config)
    if blad:
        return 400, {"error": "Blad walidacji", "message": blad}

    # Parsowanie budynku
    bud = data.get("budynek", {})
    budynek = BudynekConfig(
        x=float(bud.get("x", 0.0)),
        z=float(bud.get("z", -10.0)),
        szerokosc=float(bud.get("szerokosc", 10.0)),
        glebokosc=float(bud.get("glebokosc", 8.0)),
        wysokosc=float(bud.get("wysokosc", 8.0)),
    )

    # Parsowanie lokalizacji
    lok = data["lokalizacja"]
    try:
        szerokosc_geo = float(lok["szerokosc_geo"])
        dlugosc_geo = float(lok["dlugosc_geo"])
    except (KeyError, ValueError, TypeError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Lokalizacja musi zawierac pola 'szerokosc_geo' i 'dlugosc_geo' (liczby)",
        }

    try:
        # Oblicz rozmieszczenie paneli
        layout = oblicz_rozmieszczenie(config)

        # Pobierz dane panela z bazy
        panel_dane = znajdz_panel(config.panel_id)
        if panel_dane is None:
            return 400, {
                "error": "Blad walidacji",
                "message": f"Nie znaleziono panela '{config.panel_id}'",
            }

        technologia = panel_dane.get("technologia", "standard")
        liczba_sekcji = panel_dane.get("liczba_sekcji_bypass", 3)
        moc_stc = panel_dane["moc_wp"]
        wsp_temp = panel_dane["wspolczynnik_temp_pmax"]
        noct = panel_dane.get("noct", 45.0)

        # Oblicz pozycje slonca
        azymut_slonca, elewacja_slonca = get_solar_position(
            szerokosc_geo, dlugosc_geo, rok, miesiac, dzien, godzina
        )

        # Jesli noc (elewacja <= 0) - zwroc wynik zerowy z flaga 'noc'
        if elewacja_slonca <= 0:
            panele_wynik = []
            for i in range(config.liczba_paneli):
                panele_wynik.append({
                    "index": i,
                    "stopien_zacienienia": 0.0,
                    "sekcje_zacienione": [False] * liczba_sekcji,
                    "bypass_aktywne": 0,
                    "produkcja_wh": 0.0,
                    "produkcja_bez_cienia_wh": 0.0,
                })
            return 200, {
                "noc": True,
                "pozycja_slonca": {
                    "azymut": round(azymut_slonca, 2),
                    "elewacja": round(elewacja_slonca, 2),
                },
                "panele": panele_wynik,
                "podsumowanie": {
                    "produkcja_wh": 0.0,
                    "produkcja_bez_cienia_wh": 0.0,
                    "strata_procent": 0.0,
                },
            }

        # Oblicz zacienienie
        wyniki_zacienienia = oblicz_zacienienie_pojedyncza_godzina(
            layout.panele, budynek,
            azymut_slonca, elewacja_slonca,
            config.kat_nachylenia, liczba_sekcji, technologia,
            przeswit_nad_gruntem_m=config.przeswit_nad_gruntem_cm / 100.0,
        )

        # Pobierz dane TMY
        dane_tmy = pobierz_dane_tmy(szerokosc_geo, dlugosc_geo, uzyj_cache=True)

        # Oblicz indeks TMY: (dzien_roku - 1) * 24 + godzina
        dzien_roku = _dzien_roku(rok, miesiac, dzien)
        tmy_index = (dzien_roku - 1) * 24 + godzina

        # Pobierz dane pogodowe dla tej godziny
        if dane_tmy and tmy_index < len(dane_tmy.get("ghi", [])):
            ghi = dane_tmy["ghi"][tmy_index]
            dni_val = dane_tmy["dni"][tmy_index]
            dhi = dane_tmy["dhi"][tmy_index]
            t_ambient = dane_tmy["temperatura"][tmy_index]
        else:
            # Fallback - brak danych TMY
            ghi = 0.0
            dni_val = 0.0
            dhi = 0.0
            t_ambient = 15.0

        # Oblicz POA irradiance
        poa = oblicz_poa_tmy(
            ghi, dni_val, dhi,
            elewacja_slonca, azymut_slonca,
            config.kat_nachylenia, config.azymut,
        )
        g_poa = poa["total"]

        # Oblicz temperature panela
        temp_panela = oblicz_temperature_panela_tmy(t_ambient, g_poa, noct)

        # Oblicz produkcje per panel
        panele_wynik = []
        suma_produkcja = 0.0
        suma_bez_cienia = 0.0

        for wynik_zac in wyniki_zacienienia:
            # Wspolczynnik zacienienia
            wsp_zac = oblicz_wspolczynnik_zacienienia(
                wynik_zac, liczba_sekcji, technologia
            )

            # Produkcja z cieniem
            wynik_prod = oblicz_wydajnosc_panela(
                moc_stc, g_poa, temp_panela, wsp_temp, wsp_zac,
            )
            produkcja_wh = wynik_prod.energia_wh

            # Produkcja bez cienia (wspolczynnik = 1.0)
            wynik_bez = oblicz_wydajnosc_panela(
                moc_stc, g_poa, temp_panela, wsp_temp, 1.0,
            )
            produkcja_bez_wh = wynik_bez.energia_wh

            suma_produkcja += produkcja_wh
            suma_bez_cienia += produkcja_bez_wh

            panele_wynik.append({
                "index": wynik_zac.panel_index,
                "stopien_zacienienia": round(wynik_zac.stopien_zacienienia, 4),
                "sekcje_zacienione": wynik_zac.sekcje_zacienione,
                "bypass_aktywne": wynik_zac.bypass_aktywne,
                "produkcja_wh": round(produkcja_wh, 2),
                "produkcja_bez_cienia_wh": round(produkcja_bez_wh, 2),
            })

        # Oblicz strate procentowa
        strata_procent = 0.0
        if suma_bez_cienia > 0:
            strata_procent = (1.0 - suma_produkcja / suma_bez_cienia) * 100.0

        return 200, {
            "noc": False,
            "pozycja_slonca": {
                "azymut": round(azymut_slonca, 2),
                "elewacja": round(elewacja_slonca, 2),
            },
            "panele": panele_wynik,
            "podsumowanie": {
                "produkcja_wh": round(suma_produkcja, 2),
                "produkcja_bez_cienia_wh": round(suma_bez_cienia, 2),
                "strata_procent": round(strata_procent, 2),
            },
        }

    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania zacienienia: {e}",
        }


def handle_parcel_position(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/parcel/position - oblicza pozycje obiektu na dzialce.

    Przyjmuje wierzcholki dzialki, typ obiektu, odleglosci od granic,
    wymiary i azymut. Zwraca pozycje srodka i narozniki.

    Oczekiwany format JSON:
        {
            "wierzcholki": [[x, z], ...],
            "typ_obiektu": "budynek" | "panele",
            "odleglosc_poludniowa": 5.0,
            "odleglosc_wschodnia": 6.0,
            "szerokosc": 18.7,
            "glebokosc": 19.8,
            "azymut": 350.0
        }

    Zwraca:
        {x, z, narozniki: [{x, z}, ...], granica_poludniowa: {...}, granica_wschodnia: {...}}
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane pozycjonowania w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych pol
    wymagane = ["wierzcholki", "typ_obiektu", "odleglosc_poludniowa",
                "odleglosc_wschodnia", "szerokosc", "glebokosc", "azymut"]
    brakujace = [p for p in wymagane if p not in data]
    if brakujace:
        return 400, {
            "error": "Blad walidacji",
            "message": f"Brakujace pola: {', '.join(brakujace)}",
        }

    # Walidacja wierzcholkow
    wierzcholki_raw = data["wierzcholki"]
    if not isinstance(wierzcholki_raw, list) or len(wierzcholki_raw) < 3:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'wierzcholki' musi byc lista co najmniej 3 punktow [[x,z], ...]",
        }

    try:
        wierzcholki = [(float(w[0]), float(w[1])) for w in wierzcholki_raw]
    except (TypeError, IndexError, ValueError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Kazdy wierzcholek musi byc para liczb [x, z]",
        }

    # Walidacja typu obiektu
    typ_obiektu = str(data["typ_obiektu"])
    if typ_obiektu not in ("budynek", "panele"):
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'typ_obiektu' musi byc 'budynek' lub 'panele'",
        }

    # Parsowanie wartosci numerycznych
    try:
        odleglosc_poludniowa = float(data["odleglosc_poludniowa"])
        odleglosc_wschodnia = float(data["odleglosc_wschodnia"])
        szerokosc = float(data["szerokosc"])
        glebokosc = float(data["glebokosc"])
        azymut = float(data["azymut"])
    except (ValueError, TypeError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Pola numeryczne musza byc liczbami",
        }

    # Walidacja zakresow
    if szerokosc <= 0 or glebokosc <= 0:
        return 400, {
            "error": "Blad walidacji",
            "message": "Szerokosc i glebokosc musza byc wieksze od 0",
        }
    if odleglosc_poludniowa < 0 or odleglosc_wschodnia < 0:
        return 400, {
            "error": "Blad walidacji",
            "message": "Odleglosci nie moga byc ujemne",
        }

    # Obliczenie pozycji
    try:
        wynik = oblicz_pozycje_obiektu(
            wierzcholki=wierzcholki,
            typ_obiektu=typ_obiektu,
            odleglosc_poludniowa=odleglosc_poludniowa,
            odleglosc_wschodnia=odleglosc_wschodnia,
            szerokosc=szerokosc,
            glebokosc=glebokosc,
            azymut=azymut,
        )
        return 200, wynik
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania pozycji: {e}",
        }


def handle_parcel_distance(body: Optional[bytes]) -> Tuple[int, dict]:
    """
    Endpoint POST /api/parcel/distance - oblicza odleglosci od granic.

    Operacja odwrotna do handle_parcel_position. Na podstawie pozycji
    srodka obiektu oblicza odleglosci sciany/krawedzi od granic dzialki.

    Oczekiwany format JSON:
        {
            "wierzcholki": [[x, z], ...],
            "x": -5.0,
            "z": 3.0,
            "szerokosc": 18.7,
            "glebokosc": 19.8,
            "azymut": 350.0
        }

    Zwraca:
        {odleglosc_poludniowa: float, odleglosc_wschodnia: float}
    """
    if not body:
        return 400, {
            "error": "Brak danych",
            "message": "Wyslij dane pozycjonowania w formacie JSON",
        }

    try:
        data = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 400, {
            "error": "Nieprawidlowy format",
            "message": "Dane musza byc w formacie JSON",
        }

    # Walidacja wymaganych pol
    wymagane = ["wierzcholki", "x", "z", "szerokosc", "glebokosc", "azymut"]
    brakujace = [p for p in wymagane if p not in data]
    if brakujace:
        return 400, {
            "error": "Blad walidacji",
            "message": f"Brakujace pola: {', '.join(brakujace)}",
        }

    # Walidacja wierzcholkow
    wierzcholki_raw = data["wierzcholki"]
    if not isinstance(wierzcholki_raw, list) or len(wierzcholki_raw) < 3:
        return 400, {
            "error": "Blad walidacji",
            "message": "Pole 'wierzcholki' musi byc lista co najmniej 3 punktow [[x,z], ...]",
        }

    try:
        wierzcholki = [(float(w[0]), float(w[1])) for w in wierzcholki_raw]
    except (TypeError, IndexError, ValueError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Kazdy wierzcholek musi byc para liczb [x, z]",
        }

    # Parsowanie wartosci numerycznych
    try:
        x = float(data["x"])
        z = float(data["z"])
        szerokosc = float(data["szerokosc"])
        glebokosc = float(data["glebokosc"])
        azymut = float(data["azymut"])
    except (ValueError, TypeError):
        return 400, {
            "error": "Blad walidacji",
            "message": "Pola numeryczne musza byc liczbami",
        }

    if szerokosc <= 0 or glebokosc <= 0:
        return 400, {
            "error": "Blad walidacji",
            "message": "Szerokosc i glebokosc musza byc wieksze od 0",
        }

    # Obliczenie odleglosci
    try:
        wynik = oblicz_odleglosc_od_granic(
            wierzcholki=wierzcholki,
            x=x,
            z=z,
            szerokosc=szerokosc,
            glebokosc=glebokosc,
            azymut=azymut,
        )
        return 200, wynik
    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania odleglosci: {e}",
        }