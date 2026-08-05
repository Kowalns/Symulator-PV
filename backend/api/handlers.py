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
from backend.services.solar_position import get_solar_position
from backend.services.shading import (
    BudynekConfig,
    oblicz_zacienienie_godzinowe,
)
from backend.services.panel_performance import (
    oblicz_roczna_produkcje_panela,
    oblicz_wspolczynnik_zacienienia,
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    oblicz_wydajnosc_panela,
)
from backend.services.optimizer import (
    porownaj_z_bez_optymalizatorow,
    czy_optymalizatory_uzasadnione,
)
from backend.services.energy_profile import (
    ProfilZuzycia,
    stworz_profil_z_danych,
    oblicz_profil_godzinowy,
    oblicz_zuzycie_miesieczne,
)
from backend.services.economics import (
    analizuj_ekonomie,
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
                "odstep_miedzy_rzedami_cm": 150,
                "odstep_boczny_cm": 3,
                "liczba_paneli": 10,
                "liczba_kolumn": 5,
                "liczba_rzedow": 2
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
    for pole in ["panel_id", "liczba_paneli", "liczba_kolumn", "liczba_rzedow"]:
        if pole not in inst:
            return 400, {
                "error": "Blad walidacji",
                "message": f"Pole 'instalacja.{pole}' jest wymagane",
            }

    # Konfiguracja instalacji
    try:
        config = InstallationConfig(
            panel_id=str(inst["panel_id"]),
            orientacja=str(inst.get("orientacja", "pion")),
            kat_nachylenia=float(inst.get("kat_nachylenia", 30.0)),
            azymut=float(inst.get("azymut", 0.0)),
            przeswit_nad_gruntem_cm=float(inst.get("przeswit_nad_gruntem_cm", 50.0)),
            odstep_miedzy_rzedami_cm=float(inst.get("odstep_miedzy_rzedami_cm", 150.0)),
            odstep_boczny_cm=float(inst.get("odstep_boczny_cm", 3.0)),
            liczba_paneli=int(inst["liczba_paneli"]),
            liczba_kolumn=int(inst["liczba_kolumn"]),
            liczba_rzedow=int(inst["liczba_rzedow"]),
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
    strefa_czasowa = float(lok.get("strefa_czasowa", 1.0))

    # Opcje
    opcje = data.get("opcje", {})
    rok = int(opcje.get("rok", 2025))
    z_optymalizatorami = bool(opcje.get("optymalizatory", False))
    rok_eksploatacji = int(opcje.get("rok_eksploatacji", 1))
    straty_systemowe = float(opcje.get("straty_systemowe", 0.03))

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
        wyniki_paneli = []
        for panel in layout.panele:
            wynik = oblicz_roczna_produkcje_panela(
                moc_stc, wsp_temp, technologia, liczba_sekcji,
                zacienienia, panel.index,
                szerokosc_geo, straty_systemowe, degradacja, rok_eksploatacji
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
        for w in wyniki_paneli:
            for i in range(12):
                energia_miesieczna[i] += w["energia_miesieczna_kwh"][i]

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
            },
            "energia_miesieczna_kwh": [round(e, 2) for e in energia_miesieczna],
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

        return 200, raport

    except Exception as e:
        return 500, {
            "error": "Blad serwera",
            "message": f"Blad obliczania produkcji: {e}",
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

    try:
        profil = stworz_profil_z_danych(data)
        profil_godzinowy = oblicz_profil_godzinowy(profil, rok)
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
            "taryfa": "G11",                   ("G11", "G11f", "dynamiczna")
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

    if taryfa not in ("G11", "G11f", "dynamiczna"):
        return 400, {
            "error": "Blad walidacji",
            "message": "Taryfa musi byc jedna z: G11, G11f, dynamiczna",
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
        zuzycie_godzinowe = oblicz_profil_godzinowy(profil, rok)

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

    try:
        wynik = analizuj_ekonomie(
            produkcja_godzinowa_wh=produkcja_godzinowa,
            zuzycie_godzinowe_wh=zuzycie_godzinowe,
            taryfa=taryfa,
            magazyn=magazyn,
            rok=rok,
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