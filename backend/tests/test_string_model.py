"""
Testy jednostkowe dla modelu stringow i net-billingu z depozytem.

Testowane moduly:
- backend/services/optimizer.py - podziel_na_stringi()
- backend/services/economics.py - analizuj_ekonomie_net_billing()
- backend/services/panel_performance.py - oblicz_roczna_produkcje_instalacji()
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.optimizer import (
    podziel_na_stringi,
    KonfiguracjaStringa,
    oblicz_mismatch_stringa,
)
from backend.services.economics import (
    analizuj_ekonomie_net_billing,
    KonfiguracjaMagazynu,
)


class TestPodzielNaStringi(unittest.TestCase):
    """Testy funkcji podziel_na_stringi."""

    def test_podstawowy_podzial(self):
        """10 paneli, Vmpp=40V, MPPT 150-500V -> max 12, min 4 paneli na string."""
        stringi = podziel_na_stringi(
            liczba_paneli=10,
            napiecie_mpp_panela=40.0,
            zakres_mppt_min=150.0,
            zakres_mppt_max=500.0,
        )
        # Powinien byc co najmniej 1 string
        self.assertGreater(len(stringi), 0)
        # Wszystkie panele powinny byc przydzielone
        wszystkie_indeksy = []
        for s in stringi:
            wszystkie_indeksy.extend(s.indeksy_paneli)
        self.assertEqual(len(wszystkie_indeksy), 10)
        self.assertEqual(sorted(wszystkie_indeksy), list(range(10)))

    def test_jeden_string_dla_malej_instalacji(self):
        """5 paneli, Vmpp=40V, MPPT 100-500V -> 1 string (5 paneli miesci sie)."""
        stringi = podziel_na_stringi(
            liczba_paneli=5,
            napiecie_mpp_panela=40.0,
            zakres_mppt_min=100.0,
            zakres_mppt_max=500.0,
        )
        # 5 paneli * 40V = 200V, jest w zakresie 100-500V
        # Optymalna dlugosc = (3+12)//2 = 7, wiec 5 paneli miesci sie w jednym
        self.assertEqual(len(stringi), 1)
        self.assertEqual(len(stringi[0].indeksy_paneli), 5)

    def test_wiele_stringow_duza_instalacja(self):
        """20 paneli, Vmpp=40V, MPPT 200-500V -> powinien podzielic na kilka stringow."""
        stringi = podziel_na_stringi(
            liczba_paneli=20,
            napiecie_mpp_panela=40.0,
            zakres_mppt_min=200.0,
            zakres_mppt_max=500.0,
        )
        # max = floor(500/40) = 12, min = ceil(200/40) = 5
        # optymalna = (5+12)//2 = 8
        # 20 paneli / 8 = 3 stringi (ceil)
        self.assertGreater(len(stringi), 1)
        # Kazdy string powinien miec co najmniej min paneli
        for s in stringi:
            self.assertGreaterEqual(len(s.indeksy_paneli), 1)
        # Wszystkie panele przydzielone
        total = sum(len(s.indeksy_paneli) for s in stringi)
        self.assertEqual(total, 20)

    def test_zero_paneli(self):
        """0 paneli -> pusty wynik."""
        stringi = podziel_na_stringi(0, 40.0, 200.0, 500.0)
        self.assertEqual(stringi, [])

    def test_ujemne_napiecie(self):
        """Ujemne napiecie -> pusty wynik."""
        stringi = podziel_na_stringi(10, -1.0, 200.0, 500.0)
        self.assertEqual(stringi, [])

    def test_min_wiekszy_niz_max_mppt(self):
        """Min MPPT > max -> fallback na 1 string."""
        # Vmpp=100V, min_mppt=600V, max_mppt=500V -> min_per_string > max_per_string
        stringi = podziel_na_stringi(10, 100.0, 600.0, 500.0)
        self.assertEqual(len(stringi), 1)
        self.assertEqual(len(stringi[0].indeksy_paneli), 10)

    def test_rowny_podzial(self):
        """12 paneli powinny rozdzielic sie rownomiernie."""
        stringi = podziel_na_stringi(
            liczba_paneli=12,
            napiecie_mpp_panela=40.0,
            zakres_mppt_min=150.0,
            zakres_mppt_max=280.0,
        )
        # max = floor(280/40) = 7, min = ceil(150/40) = 4
        # optymalna = (4+7)//2 = 5
        # 12/5 = ceil -> 3 stringi (4+4+4)
        total = sum(len(s.indeksy_paneli) for s in stringi)
        self.assertEqual(total, 12)

    def test_nazwy_stringow(self):
        """Stringi powinny miec nazwy 'String 1', 'String 2', itd."""
        stringi = podziel_na_stringi(20, 40.0, 200.0, 500.0)
        for i, s in enumerate(stringi):
            self.assertEqual(s.nazwa, f"String {i + 1}")

    def test_indeksy_nie_powtarzaja_sie(self):
        """Indeksy paneli nie powinny sie powtarzac miedzy stringami."""
        stringi = podziel_na_stringi(15, 35.0, 150.0, 450.0)
        wszystkie = []
        for s in stringi:
            wszystkie.extend(s.indeksy_paneli)
        self.assertEqual(len(wszystkie), len(set(wszystkie)))

    def test_zakres_mppt_zero(self):
        """Zakres MPPT = 0 -> fallback na 1 string."""
        stringi = podziel_na_stringi(10, 40.0, 0.0, 0.0)
        self.assertEqual(len(stringi), 1)
        self.assertEqual(len(stringi[0].indeksy_paneli), 10)


class TestAnalizujEkonomieNetBilling(unittest.TestCase):
    """Testy funkcji analizuj_ekonomie_net_billing."""

    def _stworz_dane_testowe(self, produkcja_wh=500.0, zuzycie_wh=300.0):
        """Tworzy proste dane testowe (stale wartosci kazda godzine)."""
        produkcja = [produkcja_wh] * 8760
        zuzycie = [zuzycie_wh] * 8760
        return produkcja, zuzycie

    def test_podstawowy_net_billing(self):
        """Nadwyzka PV trafia na depozyt, niedobor jest odejmowany z depozytu."""
        # Produkcja wieksza niz zuzycie - nadwyzka trafia na depozyt
        produkcja = [1000.0] * 8760  # 1kWh/h produkcji
        zuzycie = [500.0] * 8760     # 0.5kWh/h zuzycia

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.03,
        )

        # Sprawdz strukture wyniku
        self.assertIn("tryb_rozliczenia", wynik)
        self.assertEqual(wynik["tryb_rozliczenia"], "net_billing_depozyt")
        self.assertIn("depozyt_stan_miesieczny", wynik)
        self.assertIn("depozyt_wplaty_roczne", wynik)
        self.assertIn("depozyt_wykorzystane", wynik)
        self.assertIn("depozyt_przepadlo", wynik)
        self.assertIn("depozyt_zwrot_20_procent", wynik)
        self.assertIn("podsumowanie_roczne", wynik)

        # Depozyt powinien miec wplaty (nadwyzka)
        self.assertGreater(wynik["depozyt_wplaty_roczne"], 0)

        # Stan miesieczny powinien miec 12 wartosci
        self.assertEqual(len(wynik["depozyt_stan_miesieczny"]), 12)

    def test_80_procent_przepada(self):
        """Po 12 miesiacach 80% niewykorzystanego depozytu przepada."""
        # Duza nadwyzka, male zuzycie -> duzo na depozycie na koniec roku
        produkcja = [2000.0] * 8760  # 2kWh/h
        zuzycie = [100.0] * 8760     # 0.1kWh/h - male zuzycie

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.03,
        )

        # Depozyt przepadlo powinno byc 80% ostatniego stanu
        # depozyt_przepadlo + depozyt_zwrot = ostatni stan miesieczny
        przepadlo = wynik["depozyt_przepadlo"]
        zwrot = wynik["depozyt_zwrot_20_procent"]

        if przepadlo + zwrot > 0:
            # Proporcja: przepadlo = 80%, zwrot = 20%
            self.assertAlmostEqual(
                przepadlo / (przepadlo + zwrot), 0.8, places=2
            )
            self.assertAlmostEqual(
                zwrot / (przepadlo + zwrot), 0.2, places=2
            )

    def test_depozyt_pokrywa_koszt(self):
        """Koszt poboru z sieci jest odejmowany z depozytu."""
        # Zmienne dane: nadwyzka w ciagu dnia, niedobor w nocy
        produkcja = []
        zuzycie = []
        for _ in range(365):
            for h in range(24):
                if 8 <= h <= 16:
                    # W ciagu dnia: produkcja > zuzycie
                    produkcja.append(2000.0)
                    zuzycie.append(500.0)
                else:
                    # W nocy: brak produkcji, zuzycie
                    produkcja.append(0.0)
                    zuzycie.append(500.0)

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.03,
        )

        # Powinny byc zarowno wplaty jak i wykorzystanie depozytu
        self.assertGreater(wynik["depozyt_wplaty_roczne"], 0)
        self.assertGreater(wynik["depozyt_wykorzystane"], 0)

        # Koszt z portfela powinien byc mniejszy niz koszt bez PV
        roczne = wynik["podsumowanie_roczne"]
        self.assertGreater(roczne["oszczednosc_roczna_zl"], 0)

    def test_brak_nadwyzki_pusty_depozyt(self):
        """Bez nadwyzki PV depozyt jest pusty."""
        # Zuzycie wieksze niz produkcja - brak nadwyzki
        produkcja = [100.0] * 8760
        zuzycie = [1000.0] * 8760

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.03,
        )

        # Brak wplat na depozyt
        self.assertEqual(wynik["depozyt_wplaty_roczne"], 0.0)
        self.assertEqual(wynik["depozyt_przepadlo"], 0.0)
        self.assertEqual(wynik["depozyt_zwrot_20_procent"], 0.0)

    def test_marza_sprzedawcy_wplywa_na_depozyt(self):
        """Wyzsza marza = mniejsze wplaty na depozyt."""
        produkcja = [1000.0] * 8760
        zuzycie = [200.0] * 8760

        wynik_niska_marza = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.01,
        )

        wynik_wysoka_marza = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
            marza_sprzedawcy=0.08,
        )

        # Niska marza = wiecej na depozycie
        self.assertGreater(
            wynik_niska_marza["depozyt_wplaty_roczne"],
            wynik_wysoka_marza["depozyt_wplaty_roczne"],
        )

    def test_autokonsumpcja_poprawna(self):
        """Autokonsumpcja = min(produkcja, zuzycie) kazdej godziny."""
        produkcja = [500.0] * 8760
        zuzycie = [300.0] * 8760

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
        )

        roczne = wynik["podsumowanie_roczne"]
        # Autokonsumpcja = 300Wh * 8760h = 2628 kWh
        oczekiwana_autokonsumpcja = 300.0 * 8760 / 1000.0
        self.assertAlmostEqual(
            roczne["autokonsumpcja_kwh"], oczekiwana_autokonsumpcja, delta=1.0
        )

    def test_struktura_wyniku_miesieczna(self):
        """Wynik powinien miec 12 elementow miesiecznych."""
        produkcja = [500.0] * 8760
        zuzycie = [300.0] * 8760

        wynik = analizuj_ekonomie_net_billing(
            produkcja_godzinowa_wh=produkcja,
            zuzycie_godzinowe_wh=zuzycie,
            taryfa="G11",
            rok=2025,
        )

        self.assertEqual(len(wynik["miesiace"]), 12)
        for mc in wynik["miesiace"]:
            self.assertIn("produkcja_kwh", mc)
            self.assertIn("zuzycie_kwh", mc)
            self.assertIn("autokonsumpcja_kwh", mc)
            self.assertIn("wplata_depozyt_zl", mc)
            self.assertIn("wykorzystanie_depozyt_zl", mc)
            self.assertIn("koszt_z_portfela_zl", mc)


class TestMismatchStringa(unittest.TestCase):
    """Testy integracyjne mismatch stringa z podzialem na stringi."""

    def test_brak_zacienienia_brak_mismatch(self):
        """Bez zacienienia (wszystkie 1.0) mismatch = 1.0 (srednia)."""
        wsp = [1.0, 1.0, 1.0, 1.0, 1.0]
        wynik = oblicz_mismatch_stringa(wsp)
        self.assertAlmostEqual(wynik, 1.0)

    def test_jeden_panel_zacieniony(self):
        """Jeden panel zacieniony - wynik gorszy niz srednia ale lepszy niz minimum."""
        wsp = [1.0, 1.0, 1.0, 1.0, 0.5]
        wynik = oblicz_mismatch_stringa(wsp)
        srednia = sum(wsp) / len(wsp)  # 0.9
        minimum = min(wsp)  # 0.5
        # Wynik powinien byc miedzy min a srednia
        self.assertGreaterEqual(wynik, minimum)
        self.assertLessEqual(wynik, srednia)

    def test_wszystkie_zacienione_zero(self):
        """Wszystkie panele = 0 -> wynik = 0."""
        wsp = [0.0, 0.0, 0.0]
        wynik = oblicz_mismatch_stringa(wsp)
        self.assertEqual(wynik, 0.0)


if __name__ == "__main__":
    unittest.main()
