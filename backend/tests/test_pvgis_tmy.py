"""
Testy integracji danych TMY z PVGIS API.

Testuje:
1. Pobieranie danych TMY z API PVGIS (test integracyjny)
2. Obliczenia POA (Plane of Array) z rozdzielem na beam/diffuse/ground
3. Zacienienie blokuje tylko beam (diffuse dociera niezaleznie)
4. Tryb fallback (bez danych TMY)
5. Walidacja: 54N, 30deg, azymut poludnie, 1kWp = 900-1050 kWh/rok
"""

import unittest
import math
import os
from unittest.mock import patch, MagicMock
from typing import Dict, Optional

from backend.services.pvgis import pobierz_dane_tmy, _klucz_cache_tmy, _parsuj_odpowiedz_tmy
from backend.services.panel_performance import (
    oblicz_poa_tmy,
    oblicz_temperature_panela_tmy,
    oblicz_roczna_produkcje_panela,
    oblicz_napromieniowanie,
    oblicz_temperature_panela,
    oblicz_wydajnosc_panela,
    NOCT_DOMYSLNY,
    ALBEDO_DOMYSLNE,
)
from backend.services.shading import (
    WynikZacienieniaPanel,
    WynikZacienieniaGodzina,
)


class TestPobierzDaneTMY(unittest.TestCase):
    """Testy pobierania danych TMY z PVGIS API (integracyjne)."""

    def test_pobierz_tmy_warszawa(self):
        """Pobiera dane TMY dla Warszawy (52.23, 21.01) z prawdziwego API."""
        dane = pobierz_dane_tmy(52.23, 21.01, uzyj_cache=True)

        self.assertIsNotNone(dane, "Nie udalo sie pobrac danych TMY z PVGIS")
        self.assertIn("ghi", dane)
        self.assertIn("dni", dane)
        self.assertIn("dhi", dane)
        self.assertIn("temperatura", dane)
        self.assertIn("wiatr", dane)
        self.assertIn("roczne_ghi_kwh_m2", dane)

        # Sprawdz ze mamy 8760 wartosci
        self.assertEqual(len(dane["ghi"]), 8760)
        self.assertEqual(len(dane["dni"]), 8760)
        self.assertEqual(len(dane["dhi"]), 8760)
        self.assertEqual(len(dane["temperatura"]), 8760)
        self.assertEqual(len(dane["wiatr"]), 8760)

        # Roczne GHI dla Polski powinno byc 900-1200 kWh/m2
        self.assertGreater(dane["roczne_ghi_kwh_m2"], 900)
        self.assertLess(dane["roczne_ghi_kwh_m2"], 1200)

    def test_klucz_cache_tmy(self):
        """Test generowania klucza cache."""
        klucz = _klucz_cache_tmy(52.23, 21.01)
        self.assertIn("52_23", klucz)
        self.assertIn("21_01", klucz)
        self.assertTrue(klucz.endswith(".json"))

    def test_klucz_cache_ujemne_wspolrzedne(self):
        """Test klucza cache dla ujemnych wspolrzednych."""
        klucz = _klucz_cache_tmy(-33.87, -18.42)
        self.assertIn("m33_87", klucz)
        self.assertIn("m18_42", klucz)

    def test_parsuj_odpowiedz_tmy_poprawna(self):
        """Test parsowania poprawnej odpowiedzi TMY."""
        # Symuluj minimalna odpowiedz z PVGIS
        dane_testowe = {
            "outputs": {
                "tmy_hourly": [
                    {"G(h)": 0, "Gb(n)": 0, "Gd(h)": 0, "T2m": -2.5, "WS10m": 3.1}
                ] * 8760
            }
        }

        wynik = _parsuj_odpowiedz_tmy(dane_testowe)
        self.assertIsNotNone(wynik)
        self.assertEqual(len(wynik["ghi"]), 8760)
        self.assertEqual(len(wynik["temperatura"]), 8760)

    def test_parsuj_odpowiedz_tmy_za_malo_danych(self):
        """Test parsowania odpowiedzi z za mala iloscia danych."""
        dane_testowe = {
            "outputs": {
                "tmy_hourly": [
                    {"G(h)": 100, "Gb(n)": 50, "Gd(h)": 50, "T2m": 15, "WS10m": 2}
                ] * 100  # Za malo
            }
        }

        wynik = _parsuj_odpowiedz_tmy(dane_testowe)
        self.assertIsNone(wynik)


class TestObliczPoaTMY(unittest.TestCase):
    """Testy obliczen POA (Plane of Array) z danymi TMY."""

    def test_poa_brak_naslonecznienia(self):
        """POA = 0 gdy brak naslonecznienia (noc)."""
        poa = oblicz_poa_tmy(0, 0, 0, -10, 180)
        self.assertEqual(poa["beam"], 0.0)
        self.assertEqual(poa["diffuse"], 0.0)
        self.assertEqual(poa["ground"], 0.0)
        self.assertEqual(poa["total"], 0.0)

    def test_poa_slonce_pod_horyzontem(self):
        """POA = 0 gdy slonce pod horyzontem."""
        poa = oblicz_poa_tmy(100, 50, 50, -5, 180)
        self.assertEqual(poa["total"], 0.0)

    def test_poa_panel_skierowany_na_poludnie_poludnie(self):
        """Panel 30deg na poludnie, slonce na poludniu - duzy beam."""
        # Elewacja 45deg, azymut 180 (poludnie), panel 30deg na poludnie
        poa = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=150,
            elewacja_slonca=45.0, azymut_slonca=180.0,
            kat_nachylenia=30.0, azymut_panela=0.0
        )

        # Beam powinien byc znaczacy
        self.assertGreater(poa["beam"], 0)
        # Diffuse powinien byc dodatni
        self.assertGreater(poa["diffuse"], 0)
        # Ground powinien byc maly ale dodatni
        self.assertGreater(poa["ground"], 0)
        # Total = suma skladnikow
        self.assertAlmostEqual(
            poa["total"], poa["beam"] + poa["diffuse"] + poa["ground"], places=1
        )

    def test_poa_panel_odwrocony_od_slonca(self):
        """Panel skierowany na polnoc, slonce na poludniu - beam = 0."""
        # Panel azymut 180 (polnoc w konwencji instalacji)
        poa = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=150,
            elewacja_slonca=45.0, azymut_slonca=180.0,
            kat_nachylenia=60.0, azymut_panela=180.0  # panel na polnoc
        )

        # Beam powinien byc 0 (panel odwrocony)
        self.assertEqual(poa["beam"], 0.0)
        # Ale diffuse i ground wciaz docieraja
        self.assertGreater(poa["diffuse"], 0)

    def test_poa_panel_poziomy(self):
        """Panel poziomy (tilt=0) - diffuse = dhi/2 * (1+cos(0)) = dhi."""
        poa = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=150,
            elewacja_slonca=45.0, azymut_slonca=180.0,
            kat_nachylenia=0.0, azymut_panela=0.0
        )

        # Dla panela poziomego: diffuse = DHI * (1 + cos(0)) / 2 = DHI
        self.assertAlmostEqual(poa["diffuse"], 150.0, places=0)
        # Ground = GHI * 0.2 * (1 - cos(0)) / 2 = 0
        self.assertAlmostEqual(poa["ground"], 0.0, places=1)

    def test_poa_roznica_azymutow(self):
        """POA beam zmniejsza sie gdy panel nie jest skierowany na slonce."""
        # Panel na poludnie, slonce na poludniu
        poa_poludnie = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=100,
            elewacja_slonca=45, azymut_slonca=180,
            kat_nachylenia=30, azymut_panela=0  # na poludnie
        )

        # Panel na wschod, slonce na poludniu
        poa_wschod = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=100,
            elewacja_slonca=45, azymut_slonca=180,
            kat_nachylenia=30, azymut_panela=-90  # na wschod
        )

        # Beam powinien byc wiekszy gdy panel jest skierowany na slonce
        self.assertGreater(poa_poludnie["beam"], poa_wschod["beam"])

    def test_poa_albedo_wplywa_na_ground(self):
        """Wyzsze albedo = wiecej odbic od gruntu."""
        poa_trawa = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=100,
            elewacja_slonca=45, azymut_slonca=180,
            kat_nachylenia=30, azymut_panela=0,
            albedo=0.2  # trawa
        )

        poa_snieg = oblicz_poa_tmy(
            ghi=500, dni=600, dhi=100,
            elewacja_slonca=45, azymut_slonca=180,
            kat_nachylenia=30, azymut_panela=0,
            albedo=0.8  # snieg
        )

        self.assertGreater(poa_snieg["ground"], poa_trawa["ground"])


class TestTemperaturaPanelaTMY(unittest.TestCase):
    """Testy modelu temperatury NOCT z danymi TMY."""

    def test_noc_temperatura_otoczenia(self):
        """W nocy (G=0) temperatura panela = temperatura otoczenia."""
        t_cell = oblicz_temperature_panela_tmy(15.0, 0.0)
        self.assertEqual(t_cell, 15.0)

    def test_dzien_panel_cieplejszy(self):
        """W dzien panel jest cieplejszy niz otoczenie."""
        t_cell = oblicz_temperature_panela_tmy(20.0, 800.0)
        # T_cell = 20 + (45-20) * 800/800 = 20 + 25 = 45
        self.assertAlmostEqual(t_cell, 45.0, places=1)

    def test_noct_formula(self):
        """Sprawdzenie formuly NOCT: T_cell = T_amb + (NOCT-20)*G/800."""
        t_amb = 25.0
        g_poa = 400.0
        noct = 45.0

        t_cell = oblicz_temperature_panela_tmy(t_amb, g_poa, noct)
        oczekiwane = 25.0 + (45.0 - 20.0) * 400.0 / 800.0  # = 25 + 12.5 = 37.5
        self.assertAlmostEqual(t_cell, oczekiwane, places=1)

    def test_rozne_noct(self):
        """Wyzsze NOCT = wyzsza temperatura panela."""
        t_cell_45 = oblicz_temperature_panela_tmy(20.0, 800.0, noct=45.0)
        t_cell_48 = oblicz_temperature_panela_tmy(20.0, 800.0, noct=48.0)
        self.assertGreater(t_cell_48, t_cell_45)


class TestZacienienieTylkoBeam(unittest.TestCase):
    """Testy: zacienienie blokuje tylko beam, diffuse dociera niezaleznie."""

    def test_zacieniony_panel_ma_diffuse(self):
        """Panel zacieniony wciaz produkuje energie z diffuse i ground."""
        # Tworzymy dane TMY z duza iloscia diffuse
        dane_tmy = _stworz_dane_tmy_testowe(
            ghi=500, dni=300, dhi=200, temperatura=20.0
        )

        # Zacienienie 100% - powinno byc wciaz cos z diffuse
        zacienienia = _stworz_zacienienia_testowe(
            stopien_zacienienia=1.0, liczba_godzin=8760
        )

        wynik = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0,  # 1 kWp
            wspolczynnik_temp_pmax=-0.35,
            technologia="standard",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            panel_index=0,
            kat_nachylenia=30.0,
            azymut_panela=0.0,
            dane_tmy=dane_tmy,
        )

        # Panel calkowicie zacieniony wciaz produkuje cos z diffuse+ground
        self.assertGreater(wynik["energia_roczna_kwh"], 0)

    def test_niezacieniony_panel_wiecej_niz_zacieniony(self):
        """Panel bez zacienienia produkuje wiecej niz zacieniony."""
        dane_tmy = _stworz_dane_tmy_testowe(
            ghi=500, dni=400, dhi=150, temperatura=15.0
        )

        # Bez zacienienia
        zacienienia_brak = _stworz_zacienienia_testowe(
            stopien_zacienienia=0.0, liczba_godzin=8760
        )
        wynik_brak = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0, wspolczynnik_temp_pmax=-0.35,
            technologia="standard", liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia_brak, panel_index=0,
            kat_nachylenia=30.0, azymut_panela=0.0, dane_tmy=dane_tmy,
        )

        # Z zacienieniem 50%
        zacienienia_50 = _stworz_zacienienia_testowe(
            stopien_zacienienia=0.5, liczba_godzin=8760
        )
        wynik_50 = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0, wspolczynnik_temp_pmax=-0.35,
            technologia="standard", liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia_50, panel_index=0,
            kat_nachylenia=30.0, azymut_panela=0.0, dane_tmy=dane_tmy,
        )

        self.assertGreater(
            wynik_brak["energia_roczna_kwh"],
            wynik_50["energia_roczna_kwh"]
        )


class TestFallback(unittest.TestCase):
    """Testy trybu fallback (bez danych TMY)."""

    def test_fallback_bez_tmy(self):
        """Bez danych TMY uzywany jest stary model (fallback)."""
        # Stworz minimalne zacienienia dla testu
        zacienienia = _stworz_zacienienia_testowe(
            stopien_zacienienia=0.0, liczba_godzin=8760
        )

        wynik = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0,
            wspolczynnik_temp_pmax=-0.35,
            technologia="standard",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            panel_index=0,
            szerokosc_geo=52.23,
            kat_nachylenia=30.0,
            azymut_panela=0.0,
            dane_tmy=None,  # Brak TMY = fallback
        )

        # Fallback powinien dac jakis wynik
        self.assertGreater(wynik["energia_roczna_kwh"], 0)
        self.assertEqual(wynik["zrodlo_danych"], "fallback")

    def test_tmy_mode_indicator(self):
        """Z danymi TMY wynik wskazuje zrodlo 'tmy'."""
        dane_tmy = _stworz_dane_tmy_testowe(
            ghi=500, dni=300, dhi=200, temperatura=15.0
        )
        zacienienia = _stworz_zacienienia_testowe(
            stopien_zacienienia=0.0, liczba_godzin=8760
        )

        wynik = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0, wspolczynnik_temp_pmax=-0.35,
            technologia="standard", liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia, panel_index=0,
            kat_nachylenia=30.0, azymut_panela=0.0, dane_tmy=dane_tmy,
        )

        self.assertEqual(wynik["zrodlo_danych"], "tmy")


class TestWalidacjaProdukcji(unittest.TestCase):
    """
    Test walidacyjny: 54N, 30deg nachylenia, azymut poludnie, 1kWp.
    Oczekiwana roczna produkcja: 900-1050 kWh/rok.

    Uzywa prawdziwych danych TMY z PVGIS API.
    """

    def test_produkcja_54n_30deg_poludnie_1kwp(self):
        """
        Walidacja: 54N, 30deg, poludnie, 1kWp produkuje 900-1050 kWh/rok.

        Test integracyjny - wymaga dostepu do PVGIS API.
        """
        # Pobierz dane TMY dla 54N, 18E (okolice Gdanska)
        dane_tmy = pobierz_dane_tmy(54.0, 18.0, uzyj_cache=True)

        if dane_tmy is None:
            self.skipTest("Brak dostepu do PVGIS API")

        # Stworz zacienienia bez cienia (otwarte pole)
        from backend.services.solar_position import get_solar_position

        dni_w_miesiacach = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        zacienienia = []

        for miesiac_idx in range(12):
            miesiac = miesiac_idx + 1
            for dzien in range(1, dni_w_miesiacach[miesiac_idx] + 1):
                for godzina in range(24):
                    azymut, elewacja = get_solar_position(
                        54.0, 18.0, 2025, miesiac, dzien, godzina
                    )
                    wynik_godzina = WynikZacienieniaGodzina(
                        miesiac=miesiac, dzien=dzien, godzina=godzina,
                        azymut_slonca=azymut, elewacja_slonca=elewacja,
                        panele=[
                            WynikZacienieniaPanel(
                                panel_index=0, stopien_zacienienia=0.0,
                                sekcje_zacienione=[False, False, False],
                                bypass_aktywne=0,
                            )
                        ]
                    )
                    zacienienia.append(wynik_godzina)

        # Oblicz produkcje: 1kWp, 30deg, poludnie, wspolczynnik temp -0.35%/C
        wynik = oblicz_roczna_produkcje_panela(
            moc_stc_w=1000.0,  # 1 kWp
            wspolczynnik_temp_pmax=-0.35,
            technologia="standard",
            liczba_sekcji=3,
            zacienienia_godzinowe=zacienienia,
            panel_index=0,
            kat_nachylenia=30.0,
            azymut_panela=0.0,  # poludnie
            dane_tmy=dane_tmy,
            noct=45.0,
        )

        produkcja = wynik["energia_roczna_kwh"]

        # Oczekiwany zakres: 900-1050 kWh/rok dla 54N, 30deg, poludnie, 1kWp
        self.assertGreaterEqual(
            produkcja, 900.0,
            f"Produkcja {produkcja} kWh/rok jest za niska (min 900)"
        )
        self.assertLessEqual(
            produkcja, 1050.0,
            f"Produkcja {produkcja} kWh/rok jest za wysoka (max 1050)"
        )


class TestHandleTmyFetch(unittest.TestCase):
    """Testy handlera POST /api/tmy/fetch."""

    def test_brak_body(self):
        """Blad 400 gdy brak body."""
        from backend.api.handlers import handle_tmy_fetch
        status, resp = handle_tmy_fetch(None)
        self.assertEqual(status, 400)

    def test_brak_wspolrzednych(self):
        """Blad 400 gdy brak latitude/longitude."""
        from backend.api.handlers import handle_tmy_fetch
        import json
        body = json.dumps({"latitude": 52.23}).encode("utf-8")
        status, resp = handle_tmy_fetch(body)
        self.assertEqual(status, 400)

    def test_poprawne_zapytanie(self):
        """Poprawne zapytanie zwraca 200 i roczne GHI."""
        from backend.api.handlers import handle_tmy_fetch
        import json
        body = json.dumps({"latitude": 52.23, "longitude": 21.01}).encode("utf-8")
        status, resp = handle_tmy_fetch(body)

        # Moze byc 200 (sukces) lub 502 (brak sieci)
        if status == 200:
            self.assertIn("roczne_ghi_kwh_m2", resp)
            self.assertGreater(resp["roczne_ghi_kwh_m2"], 0)


# --- Funkcje pomocnicze do testow ---

def _stworz_dane_tmy_testowe(ghi: float = 0, dni: float = 0,
                              dhi: float = 0, temperatura: float = 15.0) -> Dict:
    """
    Tworzy sztuczne dane TMY do testow jednostkowych.

    Ustawia te same wartosci dla kazdej godziny - uproszczenie do testow.
    W rzeczywistosci TMY ma zmienne wartosci godzina po godzinie.
    """
    # Symuluj profil: 0 w nocy, podane wartosci w godzinach 6-18
    ghi_lista = []
    dni_lista = []
    dhi_lista = []
    temp_lista = []
    wiatr_lista = []

    for dzien in range(365):
        for godzina in range(24):
            if 6 <= godzina <= 18:
                ghi_lista.append(ghi)
                dni_lista.append(dni)
                dhi_lista.append(dhi)
            else:
                ghi_lista.append(0.0)
                dni_lista.append(0.0)
                dhi_lista.append(0.0)
            temp_lista.append(temperatura)
            wiatr_lista.append(3.0)

    return {
        "ghi": ghi_lista,
        "dni": dni_lista,
        "dhi": dhi_lista,
        "temperatura": temp_lista,
        "wiatr": wiatr_lista,
        "roczne_ghi_kwh_m2": sum(ghi_lista) / 1000.0,
    }


def _stworz_zacienienia_testowe(stopien_zacienienia: float = 0.0,
                                 liczba_godzin: int = 8760) -> list:
    """
    Tworzy sztuczne dane zacienienia do testow.

    Symuluje rok z prostym modelem pozycji slonca.
    """
    from backend.services.solar_position import get_solar_position

    dni_w_miesiacach = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    zacienienia = []

    for miesiac_idx in range(12):
        miesiac = miesiac_idx + 1
        for dzien in range(1, dni_w_miesiacach[miesiac_idx] + 1):
            for godzina in range(24):
                azymut, elewacja = get_solar_position(
                    52.23, 21.01, 2025, miesiac, dzien, godzina
                )

                panel_zac = WynikZacienieniaPanel(
                    panel_index=0,
                    stopien_zacienienia=stopien_zacienienia if elewacja > 0 else 0.0,
                    sekcje_zacienione=[stopien_zacienienia > 0.5] * 3,
                    bypass_aktywne=3 if stopien_zacienienia > 0.5 else 0,
                )

                wynik_godzina = WynikZacienieniaGodzina(
                    miesiac=miesiac, dzien=dzien, godzina=godzina,
                    azymut_slonca=azymut, elewacja_slonca=elewacja,
                    panele=[panel_zac]
                )
                zacienienia.append(wynik_godzina)

    return zacienienia


if __name__ == "__main__":
    unittest.main()
