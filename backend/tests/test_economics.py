"""
Testy jednostkowe dla modulow analizy ekonomicznej.

Testowane moduly:
- backend/services/economics.py - analiza ekonomiczna
- backend/services/energy_profile.py - profil zuzycia energii
- backend/services/rce_prices.py - ceny RCE

Kluczowe zasady testowane:
1. Taryfy G11, G11f i dynamiczna maja poprawne ceny
2. Profil zuzycia poprawnie rozbija zuzycie na godziny
3. Bilansowanie produkcja vs zuzycie jest prawidlowe
4. Magazyn NIE moze byc ladowany z sieci (arbitraz niemozliwy)
5. Sprzedaz nadwyzki po cenach RCE
6. Uzytkownik moze wybrac godzine sprzedazy z magazynu
"""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch

# Dodanie sciezki projektu
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.economics import (
    analizuj_ekonomie,
    oblicz_cene_kupna,
    oblicz_cene_sprzedazy,
    oblicz_oplaty_stale,
    wczytaj_taryfy,
    KonfiguracjaMagazynu,
)
from backend.services.energy_profile import (
    ProfilZuzycia,
    oblicz_profil_godzinowy,
    oblicz_zuzycie_miesieczne,
    stworz_profil_z_danych,
    czy_dzien_wolny,
)
from backend.services.rce_prices import (
    pobierz_cene_rce,
    pobierz_cene_rce_sprzedaz,
    pobierz_ceny_rce_miesiac,
    pobierz_srednia_rce_miesiac,
    pobierz_statystyki_rce,
)


class TestTaryfy(unittest.TestCase):
    """Testy wczytywania i poprawnosci taryf energetycznych."""

    def setUp(self):
        """Wczytaj taryfy przed kazdym testem."""
        self.taryfy = wczytaj_taryfy()

    def test_taryfy_zaladowane(self):
        """Sprawdza czy plik taryf jest poprawnie wczytany."""
        self.assertIn("G11", self.taryfy)
        self.assertIn("G11f", self.taryfy)
        self.assertIn("dynamiczna", self.taryfy)

    def test_g11_cena_calkowita(self):
        """G11 ma stala cene calkowita za kWh."""
        cena = self.taryfy["G11"]["cena_calkowita_zl_kwh"]
        self.assertGreater(cena, 0.5)
        self.assertLess(cena, 2.0)
        # Cena z faktury: ~1.14 zl/kWh
        self.assertAlmostEqual(cena, 1.1396, places=2)

    def test_g11f_tansza_od_g11(self):
        """G11f ma nizsza cene calkowita za kWh niz G11."""
        cena_g11 = self.taryfy["G11"]["cena_calkowita_zl_kwh"]
        cena_g11f = self.taryfy["G11f"]["cena_calkowita_zl_kwh"]
        self.assertLess(cena_g11f, cena_g11)

    def test_g11f_wyzsza_oplata_stala(self):
        """G11f ma wyzsza miesieczna oplate stala niz G11."""
        stala_g11 = sum(self.taryfy["G11"]["oplaty_stale_zl_mc"].values())
        stala_g11f = sum(self.taryfy["G11f"]["oplaty_stale_zl_mc"].values())
        self.assertGreater(stala_g11f, stala_g11)

    def test_dynamiczna_ma_narzut(self):
        """Taryfa dynamiczna ma narzut sprzedawcy."""
        narzut = self.taryfy["dynamiczna"]["skladniki"]["narzut_sprzedawcy_zl_kwh"]
        self.assertGreater(narzut, 0)
        self.assertLess(narzut, 0.2)

    def test_dynamiczna_typ(self):
        """Taryfa dynamiczna ma typ 'dynamiczna'."""
        self.assertEqual(self.taryfy["dynamiczna"]["typ"], "dynamiczna")

    def test_g11_ma_oplate_kogeneracyjna(self):
        """G11 zawiera oplate kogeneracyjna."""
        self.assertIn("oplata_kogeneracyjna_zl_kwh", self.taryfy["G11"]["skladniki"])
        kogeneracja = self.taryfy["G11"]["skladniki"]["oplata_kogeneracyjna_zl_kwh"]
        self.assertGreater(kogeneracja, 0)

    def test_cena_energii_czynnej(self):
        """Cena energii czynnej wynosi ok. 0.6172 zl/kWh (z faktury)."""
        cena = self.taryfy["G11"]["skladniki"]["energia_czynna_zl_kwh"]
        self.assertAlmostEqual(cena, 0.6172, places=3)


class TestCenyRCE(unittest.TestCase):
    """Testy cen RCE (Rynek Dnia Nastepnego)."""

    def test_cena_rce_dodatnia(self):
        """Wszystkie ceny RCE sa dodatnie."""
        for miesiac in range(1, 13):
            for godzina in range(24):
                cena = pobierz_cene_rce(miesiac, godzina)
                self.assertGreater(cena, 0, f"Cena RCE ujemna: miesiac={miesiac}, godzina={godzina}")

    def test_ceny_latem_w_poludnie_najnizsze(self):
        """Latem (czerwiec-lipiec) ceny w poludnie sa najnizsze w ciagu dnia."""
        for miesiac in [6, 7]:
            ceny = pobierz_ceny_rce_miesiac(miesiac)
            cena_poludnie = ceny[12]
            cena_wieczor = ceny[18]
            self.assertLess(cena_poludnie, cena_wieczor,
                          f"Miesiac {miesiac}: cena w poludnie powinna byc nizsza niz wieczorem")

    def test_cena_sprzedazy_nizsza_od_kupna(self):
        """Cena sprzedazy (netto) jest nizsza od ceny kupna (brutto z VAT)."""
        for miesiac in [1, 6, 12]:
            for godzina in [8, 12, 18]:
                sprzedaz = pobierz_cene_rce_sprzedaz(miesiac, godzina)
                kupno = pobierz_cene_rce(miesiac, godzina)
                self.assertLess(sprzedaz, kupno)

    def test_srednia_rce_sensowna(self):
        """Srednia cena RCE jest w sensownym zakresie (0.1-1.0 zl/kWh)."""
        for miesiac in range(1, 13):
            srednia = pobierz_srednia_rce_miesiac(miesiac)
            self.assertGreater(srednia, 0.1)
            self.assertLess(srednia, 1.0)

    def test_statystyki_rce_kompletne(self):
        """Statystyki RCE zawieraja dane dla kazdego miesiaca."""
        stats = pobierz_statystyki_rce()
        self.assertEqual(len(stats["miesiace"]), 12)
        for mc in stats["miesiace"]:
            self.assertIn("srednia_kupno_zl_kwh", mc)
            self.assertIn("godzina_najtanszej", mc)
            self.assertIn("godzina_najdrozszej", mc)

    def test_zima_drozsza_niz_lato(self):
        """Srednia cena RCE zimna jest wyzsza niz letnia."""
        srednia_styczen = pobierz_srednia_rce_miesiac(1)
        srednia_czerwiec = pobierz_srednia_rce_miesiac(6)
        self.assertGreater(srednia_styczen, srednia_czerwiec)


class TestProfilZuzycia(unittest.TestCase):
    """Testy profilu zuzycia energii."""

    def test_profil_bazowy_8760_godzin(self):
        """Profil godzinowy ma dokladnie 8760 wartosci (365 * 24)."""
        profil = ProfilZuzycia(zuzycie_bazowe_w=200.0)
        wynik = oblicz_profil_godzinowy(profil, 2025)
        self.assertEqual(len(wynik), 8760)

    def test_profil_bazowy_stale_zuzycie(self):
        """Przy samym zuzyciu bazowym, kazda godzina ma wartosc > 0."""
        profil = ProfilZuzycia(zuzycie_bazowe_w=300.0)
        wynik = oblicz_profil_godzinowy(profil, 2025)
        for i, val in enumerate(wynik):
            self.assertGreater(val, 0, f"Godzina {i} ma zerowe zuzycie bazowe")

    def test_zuzycie_miesieczne_suma(self):
        """Suma zuzycia miesiecznego powinna zgadzac sie z roczna."""
        profil = ProfilZuzycia(zuzycie_bazowe_w=200.0)
        profil_godz = oblicz_profil_godzinowy(profil, 2025)
        miesieczne = oblicz_zuzycie_miesieczne(profil_godz, 2025)
        roczne = sum(miesieczne)
        # Suma z profilu godzinowego
        roczne_z_godzin = sum(profil_godz) / 1000.0
        self.assertAlmostEqual(roczne, roczne_z_godzin, places=0)

    def test_pompa_ciepla_zwieksza_zuzycie_zima(self):
        """Pompa ciepla zwieksza zuzycie w miesiacach grzewczych."""
        profil_bez = ProfilZuzycia(zuzycie_bazowe_w=200.0)
        profil_z = ProfilZuzycia(
            zuzycie_bazowe_w=200.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=8000.0,
        )
        godz_bez = oblicz_profil_godzinowy(profil_bez, 2025)
        godz_z = oblicz_profil_godzinowy(profil_z, 2025)

        mc_bez = oblicz_zuzycie_miesieczne(godz_bez, 2025)
        mc_z = oblicz_zuzycie_miesieczne(godz_z, 2025)

        # Styczen (miesiac grzewczy) powinien miec wiecej
        self.assertGreater(mc_z[0], mc_bez[0])
        # Lipiec (brak ogrzewania) powinien byc taki sam
        self.assertAlmostEqual(mc_z[6], mc_bez[6], places=0)

    def test_cwu_calodobowe(self):
        """CWU zwieksza zuzycie przez caly rok rownomiernie."""
        profil_z = ProfilZuzycia(
            zuzycie_bazowe_w=200.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=2500.0,
        )
        godz = oblicz_profil_godzinowy(profil_z, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)

        # Kazdy miesiac powinien miec dodatkowe zuzycie CWU
        for m in mc:
            self.assertGreater(m, 0)

    def test_dni_robocze_vs_wolne(self):
        """Profil rozroznia dni robocze od wolnych."""
        # Duze zuzycie w dniu roboczym, male w wolnym
        roboczy = [0] * 24
        roboczy[18] = 2000  # 2000 Wh o 18:00 w dni robocze
        wolny = [0] * 24
        wolny[18] = 500  # 500 Wh o 18:00 w dni wolne

        profil = ProfilZuzycia(
            zuzycie_bazowe_w=100.0,
            zuzycie_godzinowe_roboczy=roboczy,
            zuzycie_godzinowe_wolny=wolny,
        )
        wynik = oblicz_profil_godzinowy(profil, 2025)

        # Sprawdz ze w roku mamy rozne wartosci
        unikalne = set(wynik)
        self.assertGreater(len(unikalne), 2)

    def test_czy_dzien_wolny(self):
        """Sprawdza poprawnosc wykrywania dni wolnych."""
        # 2025-01-04 to sobota
        self.assertTrue(czy_dzien_wolny(2025, 1, 4))
        # 2025-01-05 to niedziela
        self.assertTrue(czy_dzien_wolny(2025, 1, 5))
        # 2025-01-06 to poniedzialek
        self.assertFalse(czy_dzien_wolny(2025, 1, 6))

    def test_stworz_profil_z_danych(self):
        """Tworzy poprawny profil z danych wejsciowych."""
        dane = {
            "zuzycie_bazowe_w": 250,
            "pompa_ciepla_co": True,
            "zuzycie_co_roczne_kwh": 6000,
        }
        profil = stworz_profil_z_danych(dane)
        self.assertEqual(profil.zuzycie_bazowe_w, 250.0)
        self.assertTrue(profil.pompa_ciepla_co)
        self.assertEqual(profil.zuzycie_co_roczne_kwh, 6000.0)


class TestAnalizaEkonomiczna(unittest.TestCase):
    """Testy analizy ekonomicznej - bilansowanie produkcji i zuzycia."""

    def setUp(self):
        """Przygotuj proste dane testowe."""
        # Proste dane: stale zuzycie 500 Wh/h, stala produkcja 0 Wh
        self.zuzycie_stale = [500.0] * 8760
        self.produkcja_zero = [0.0] * 8760

        # Produkcja z PV: 0 noca, 1000 Wh w dzien (8-16)
        self.produkcja_pv = []
        for h in range(8760):
            godzina = h % 24
            if 8 <= godzina <= 15:
                self.produkcja_pv.append(1000.0)
            else:
                self.produkcja_pv.append(0.0)

    def test_bez_pv_caly_koszt(self):
        """Bez PV caly koszt to kupno z sieci."""
        wynik = analizuj_ekonomie(
            self.produkcja_zero,
            self.zuzycie_stale,
            taryfa="G11",
        )
        roczne = wynik["podsumowanie_roczne"]
        self.assertEqual(roczne["produkcja_kwh"], 0.0)
        self.assertGreater(roczne["koszt_kupna_zl"], 0)
        self.assertEqual(roczne["przychod_sprzedazy_zl"], 0.0)

    def test_produkcja_wieksza_od_zuzycia(self):
        """Gdy produkcja > zuzycie, nadwyzka jest sprzedawana."""
        # Zuzycie male (200 Wh/h), produkcja duza w dzien
        zuzycie_male = [200.0] * 8760
        wynik = analizuj_ekonomie(
            self.produkcja_pv,
            zuzycie_male,
            taryfa="G11",
        )
        roczne = wynik["podsumowanie_roczne"]
        self.assertGreater(roczne["sprzedaz_kwh"], 0)
        self.assertGreater(roczne["przychod_sprzedazy_zl"], 0)

    def test_autokonsumpcja_procent(self):
        """Autokonsumpcja jest prawidlowo obliczana."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv,
            self.zuzycie_stale,
            taryfa="G11",
        )
        roczne = wynik["podsumowanie_roczne"]
        # Autokonsumpcja musi byc miedzy 0 a 100%
        self.assertGreaterEqual(roczne["autokonsumpcja_procent"], 0)
        self.assertLessEqual(roczne["autokonsumpcja_procent"], 100)

    def test_bilans_energetyczny(self):
        """Produkcja = autokonsumpcja + sprzedaz (bilans musi sie zgadzac)."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv,
            self.zuzycie_stale,
            taryfa="G11",
        )
        roczne = wynik["podsumowanie_roczne"]
        # Produkcja = autokonsumpcja + sprzedaz (z dokladnoscia do zaokraglen)
        suma = roczne["autokonsumpcja_kwh"] + roczne["sprzedaz_kwh"]
        # Tolerancja na zaokraglenia i magazyn
        self.assertAlmostEqual(roczne["produkcja_kwh"], suma, delta=10)

    def test_oszczednosc_z_pv(self):
        """PV generuje oszczednosc wzgledem braku PV."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv,
            self.zuzycie_stale,
            taryfa="G11",
        )
        roczne = wynik["podsumowanie_roczne"]
        self.assertGreater(roczne["oszczednosc_roczna_zl"], 0)

    def test_magazyn_autokonsumpcja(self):
        """Magazyn w trybie autokonsumpcji zmniejsza kupno z sieci."""
        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            priorytet="autokonsumpcja",
        )

        wynik_bez = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11", magazyn=None
        )
        wynik_z = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11", magazyn=magazyn
        )

        # Z magazynem powinno byc mniej kupna z sieci
        self.assertLess(
            wynik_z["podsumowanie_roczne"]["kupno_kwh"],
            wynik_bez["podsumowanie_roczne"]["kupno_kwh"],
        )

    def test_magazyn_sprzedaz_w_wybranej_godzinie(self):
        """Magazyn w trybie sprzedazy rozladowuje sie w wybranej godzinie."""
        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            godzina_sprzedazy=18,
            priorytet="sprzedaz",
        )

        wynik = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11", magazyn=magazyn
        )
        # Magazyn powinien byc uzyty (ladowanie + rozladowanie)
        roczne = wynik["podsumowanie_roczne"]
        # Sprawdz ze jest sprzedaz (energia z magazynu sprzedana)
        self.assertGreater(roczne["sprzedaz_kwh"], 0)
        self.assertTrue(wynik["magazyn_uzyty"])

    def test_arbitraz_niemozliwy(self):
        """Magazyn NIE jest ladowany z sieci - tylko z PV nadwyzki.

        Test weryfikuje kluczowe ograniczenie: energia w magazynie
        pochodzi TYLKO z nadwyzki produkcji PV, nigdy z sieci.
        """
        # Gdy PV nie produkuje (noc), magazyn NIE moze sie ladowac
        produkcja_zero = [0.0] * 8760
        zuzycie = [500.0] * 8760

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            priorytet="autokonsumpcja",
        )

        wynik = analizuj_ekonomie(
            produkcja_zero, zuzycie, taryfa="G11", magazyn=magazyn
        )

        # Bez produkcji PV, magazyn nie powinien byc ladowany
        for mc in wynik["miesiace"]:
            self.assertEqual(mc["magazyn_ladowanie_kwh"], 0.0,
                           "Magazyn nie powinien byc ladowany bez produkcji PV!")

    def test_taryfa_g11_stala_cena(self):
        """G11 ma stala cene niezaleznie od godziny."""
        cena_8 = oblicz_cene_kupna("G11", 6, 8)
        cena_18 = oblicz_cene_kupna("G11", 6, 18)
        cena_2 = oblicz_cene_kupna("G11", 6, 2)
        self.assertEqual(cena_8, cena_18)
        self.assertEqual(cena_8, cena_2)

    def test_taryfa_dynamiczna_rozna_cena(self):
        """Taryfa dynamiczna ma rozne ceny w roznych godzinach."""
        cena_12 = oblicz_cene_kupna("dynamiczna", 6, 12)
        cena_18 = oblicz_cene_kupna("dynamiczna", 6, 18)
        self.assertNotEqual(cena_12, cena_18)
        # Wieczorem drozsza niz w poludnie latem
        self.assertGreater(cena_18, cena_12)

    def test_oplaty_stale_dodatnie(self):
        """Oplaty stale sa dodatnie dla kazdej taryfy."""
        for t in ["G11", "G11f", "dynamiczna"]:
            oplata = oblicz_oplaty_stale(t)
            self.assertGreater(oplata, 0, f"Oplata stala dla {t} powinna byc dodatnia")

    def test_12_miesiecy_w_wyniku(self):
        """Wynik zawiera dane dla 12 miesiecy."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11"
        )
        self.assertEqual(len(wynik["miesiace"]), 12)

    def test_uwaga_arbitraz_w_wyniku(self):
        """Wynik zawiera informacje o zakazie arbitrazu."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11"
        )
        self.assertIn("uwaga_arbitraz", wynik)
        self.assertIn("TYLKO", wynik["uwaga_arbitraz"])


class TestObliczCeneKupna(unittest.TestCase):
    """Testy obliczania ceny kupna energii."""

    def test_g11_sensowna_cena(self):
        """G11 - cena w sensownym zakresie."""
        cena = oblicz_cene_kupna("G11", 1, 12)
        self.assertGreater(cena, 0.5)
        self.assertLess(cena, 2.0)

    def test_g11f_tansza(self):
        """G11f jest tansza per kWh niz G11."""
        cena_g11 = oblicz_cene_kupna("G11", 1, 12)
        cena_g11f = oblicz_cene_kupna("G11f", 1, 12)
        self.assertLess(cena_g11f, cena_g11)

    def test_dynamiczna_latem_tanio_w_poludnie(self):
        """Dynamiczna latem w poludnie jest tansza niz wieczorem."""
        cena_12 = oblicz_cene_kupna("dynamiczna", 7, 12)
        cena_19 = oblicz_cene_kupna("dynamiczna", 7, 19)
        self.assertLess(cena_12, cena_19)


if __name__ == "__main__":
    unittest.main()
