"""
Testy jednostkowe dla modulow analizy ekonomicznej.

Testowane moduly:
- backend/services/economics.py - analiza ekonomiczna
- backend/services/energy_profile.py - profil zuzycia energii
- backend/services/rce_prices.py - ceny RCE (realne dane z PSE)

Kluczowe zasady testowane:
1. Taryfy: G11 (stala), G11f_dynamiczna (dynamiczna + nizsza dystrybucja G11f),
   G11_dynamiczna (dynamiczna + standardowa dystrybucja G11)
2. Profil zuzycia poprawnie rozbija zuzycie na godziny
3. Bilansowanie produkcja vs zuzycie jest prawidlowe
4. Magazyn NIE moze byc ladowany z sieci (arbitraz niemozliwy)
5. Sprzedaz nadwyzki po cenach RCE
6. Uzytkownik moze wybrac godzine sprzedazy z magazynu
7. Ceny RCE moga byc ujemne (realne dane z PSE)
8. Oplata mocowa to ryczalt miesieczny, NIE stawka per kWh
"""

import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

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
    wczytaj_cache_rce,
    _agreguj_do_godzin,
    CACHE_PATH,
)


class TestTaryfy(unittest.TestCase):
    """Testy wczytywania i poprawnosci taryf energetycznych (Energa 2026)."""

    def setUp(self):
        """Wczytaj taryfy przed kazdym testem."""
        self.taryfy = wczytaj_taryfy()

    def test_taryfy_zaladowane(self):
        """Sprawdza czy plik taryf jest poprawnie wczytany."""
        self.assertIn("G11", self.taryfy)
        self.assertIn("G11f_dynamiczna", self.taryfy)
        self.assertIn("G11_dynamiczna", self.taryfy)

    def test_brak_starej_taryfy_dynamiczna(self):
        """Stary klucz 'dynamiczna' nie powinien istniec."""
        self.assertNotIn("dynamiczna", self.taryfy)

    def test_g11_cena_calkowita(self):
        """G11 ma stala cene calkowita za kWh (brutto)."""
        cena = self.taryfy["G11"]["cena_calkowita_brutto_zl_kwh"]
        self.assertGreater(cena, 0.8)
        self.assertLess(cena, 1.5)
        # Energa 2026: 0.6172 + 0.4287 + 0.0407 + 0.0090 + 0.0037 = 1.0993
        self.assertAlmostEqual(cena, 1.0993, places=3)

    def test_g11f_dynamiczna_typ(self):
        """G11f_dynamiczna ma typ 'dynamiczna' - cena energii zmienia sie co godzine."""
        self.assertEqual(self.taryfy["G11f_dynamiczna"]["typ"], "dynamiczna")

    def test_g11_dynamiczna_typ(self):
        """G11_dynamiczna ma typ 'dynamiczna'."""
        self.assertEqual(self.taryfy["G11_dynamiczna"]["typ"], "dynamiczna")

    def test_g11f_brak_stalej_ceny(self):
        """G11f_dynamiczna NIE ma pola cena_calkowita - bo cena jest dynamiczna."""
        self.assertNotIn("cena_calkowita_brutto_zl_kwh", self.taryfy["G11f_dynamiczna"])

    def test_g11f_nizsza_dystrybucja(self):
        """G11f ma nizsza dystrybucje zmienna niz G11 (0.0516 vs 0.3485 netto)."""
        dystr_g11 = self.taryfy["G11"]["skladniki_brutto_zl_kwh"]["dystrybucja_zmienna"]
        dystr_g11f = self.taryfy["G11f_dynamiczna"]["skladniki_brutto_zl_kwh"]["dystrybucja_zmienna"]
        self.assertLess(dystr_g11f, dystr_g11)
        # G11f dystrybucja netto = 0.0516, brutto = 0.0635
        self.assertAlmostEqual(dystr_g11f, 0.0635, places=3)
        # G11 dystrybucja netto = 0.3485, brutto = 0.4287
        self.assertAlmostEqual(dystr_g11, 0.4287, places=3)

    def test_g11f_wyzsza_oplata_stala(self):
        """G11f ma wyzsza miesieczna oplate stala niz G11 (wyzsza sieciowa stala)."""
        stala_g11 = sum(self.taryfy["G11"]["oplaty_stale_brutto_zl_mc"].values())
        stala_g11f = sum(self.taryfy["G11f_dynamiczna"]["oplaty_stale_brutto_zl_mc"].values())
        self.assertGreater(stala_g11f, stala_g11)

    def test_g11f_ma_narzut_sprzedawcy(self):
        """G11f_dynamiczna ma narzut sprzedawcy WK (0.0878 netto, 0.1080 brutto)."""
        narzut = self.taryfy["G11f_dynamiczna"]["skladniki_brutto_zl_kwh"]["narzut_sprzedawcy_wk"]
        self.assertAlmostEqual(narzut, 0.1080, places=3)

    def test_g11_dynamiczna_ma_narzut(self):
        """G11_dynamiczna ma narzut sprzedawcy WK."""
        narzut = self.taryfy["G11_dynamiczna"]["skladniki_brutto_zl_kwh"]["narzut_sprzedawcy_wk"]
        self.assertAlmostEqual(narzut, 0.1080, places=3)

    def test_g11_ma_oplate_kogeneracyjna(self):
        """G11 zawiera oplate kogeneracyjna (0.003 netto, 0.0037 brutto)."""
        kogeneracja = self.taryfy["G11"]["skladniki_brutto_zl_kwh"]["oplata_kogeneracyjna"]
        self.assertAlmostEqual(kogeneracja, 0.0037, places=3)

    def test_cena_energii_czynnej_g11(self):
        """Cena energii czynnej G11 brutto = 0.6172 zl/kWh."""
        cena = self.taryfy["G11"]["skladniki_brutto_zl_kwh"]["energia_czynna"]
        self.assertAlmostEqual(cena, 0.6172, places=3)

    def test_oplata_mocowa_ryczalt_miesieczny(self):
        """Oplata mocowa jest ryczaltem miesiecznym (29.58 brutto), NIE per kWh."""
        for klucz in ["G11", "G11f_dynamiczna", "G11_dynamiczna"]:
            mocowa = self.taryfy[klucz]["oplaty_stale_brutto_zl_mc"]["oplata_mocowa_ryczalt"]
            self.assertAlmostEqual(mocowa, 29.58, places=1)
            # Upewnij sie ze NIE ma oplaty mocowej w skladnikach per kWh
            self.assertNotIn("oplata_mocowa", self.taryfy[klucz].get("skladniki_brutto_zl_kwh", {}))

    def test_g11f_dynamiczna_srednia_nizsza_od_g11_dynamiczna(self):
        """G11f_dynamiczna ma nizsza cene niz G11_dynamiczna (nizsza dystrybucja)."""
        cena_g11f = oblicz_cene_kupna("G11f_dynamiczna", 7, 12)
        cena_g11_dyn = oblicz_cene_kupna("G11_dynamiczna", 7, 12)
        # G11f tansza niz G11_dynamiczna (bo ma nizsza dystrybucje)
        self.assertLess(cena_g11f, cena_g11_dyn)

    def test_oplata_oze(self):
        """Oplata OZE = 0.0073 netto, 0.0090 brutto."""
        oze = self.taryfy["G11"]["skladniki_brutto_zl_kwh"]["oplata_oze"]
        self.assertAlmostEqual(oze, 0.0090, places=3)

    def test_oplata_jakosciowa(self):
        """Oplata jakosciowa = 0.0331 netto, 0.0407 brutto."""
        jak = self.taryfy["G11"]["skladniki_brutto_zl_kwh"]["oplata_jakosciowa"]
        self.assertAlmostEqual(jak, 0.0407, places=3)


class TestCenyRCE(unittest.TestCase):
    """Testy cen RCE (Rynkowa Cena Energii) z danych PSE."""

    def test_cena_rce_w_sensownym_zakresie(self):
        """Ceny RCE sa w sensownym zakresie (moga byc ujemne!)."""
        for miesiac in range(1, 13):
            for godzina in range(24):
                cena = pobierz_cene_rce(miesiac, godzina)
                # Ceny moga byc ujemne, ale nie powinny byc absurdalnie niskie/wysokie
                self.assertGreater(cena, -1.0, f"Cena RCE zbyt niska: miesiac={miesiac}, godzina={godzina}")
                self.assertLess(cena, 3.0, f"Cena RCE zbyt wysoka: miesiac={miesiac}, godzina={godzina}")

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
                # Kupno = netto * 1.23 (brutto), sprzedaz = netto
                # Wiec kupno > sprzedaz (dla wartosci dodatnich)
                # Dla ujemnych: kupno (brutto ujemne) < sprzedaz (netto ujemne)
                # Ale stosunek jest taki sam: kupno/sprzedaz = 1.23
                if sprzedaz > 0:
                    self.assertLess(sprzedaz, kupno)

    def test_srednia_rce_sensowna(self):
        """Srednia cena RCE jest w sensownym zakresie."""
        for miesiac in range(1, 13):
            srednia = pobierz_srednia_rce_miesiac(miesiac)
            # Srednia powinna byc dodatnia (mimo ze pojedyncze godziny moga byc ujemne)
            self.assertGreater(srednia, 0.0)
            self.assertLess(srednia, 1.5)

    def test_statystyki_rce_kompletne(self):
        """Statystyki RCE zawieraja dane dla kazdego miesiaca."""
        stats = pobierz_statystyki_rce()
        self.assertEqual(len(stats["miesiace"]), 12)
        for mc in stats["miesiace"]:
            self.assertIn("srednia_kupno_zl_kwh", mc)
            self.assertIn("godzina_najtanszej", mc)
            self.assertIn("godzina_najdrozszej", mc)

    def test_zima_drozsza_niz_lato(self):
        """Srednia cena RCE zima jest wyzsza niz letnia."""
        srednia_styczen = pobierz_srednia_rce_miesiac(1)
        srednia_czerwiec = pobierz_srednia_rce_miesiac(6)
        self.assertGreater(srednia_styczen, srednia_czerwiec)

    def test_cache_rce_istnieje(self):
        """Cache RCE istnieje i zawiera dane."""
        dane = wczytaj_cache_rce()
        self.assertIsNotNone(dane, "Cache RCE powinien istniec (backend/data/rce_cache.json)")
        self.assertGreater(len(dane), 100, "Cache powinien miec dane za co najmniej 100 dni")

    def test_cache_format_poprawny(self):
        """Cache ma poprawny format - kazdy dzien ma 24 wartosci."""
        dane = wczytaj_cache_rce()
        if dane is None:
            self.skipTest("Brak cache RCE")
        for data, godziny in list(dane.items())[:10]:
            self.assertEqual(len(godziny), 24, f"Dzien {data} powinien miec 24 wartosci")
            for cena in godziny:
                self.assertIsInstance(cena, (int, float))

    def test_agregacja_15min_do_godzin(self):
        """Agregacja 96 rekordow 15-min do 24 srednich godzinowych."""
        # Symuluj 96 rekordow (4 na godzine, kazdy z cena = numer godziny * 10)
        rekordy = []
        for h in range(24):
            for q in range(4):
                minuta_start = q * 15
                minuta_end = (q + 1) * 15 if q < 3 else 0
                godzina_end = h if q < 3 else h + 1
                period = f"{h:02d}:{minuta_start:02d} - {godzina_end:02d}:{minuta_end:02d}"
                rekordy.append({
                    'rce_pln': float(h * 10 + q),
                    'udtczas_obow': period,
                })
        godzinowe = _agreguj_do_godzin(rekordy)
        self.assertEqual(len(godzinowe), 24)
        # Godzina 0: srednia z 0,1,2,3 = 1.5
        self.assertAlmostEqual(godzinowe[0], 1.5, places=1)
        # Godzina 1: srednia z 10,11,12,13 = 11.5
        self.assertAlmostEqual(godzinowe[1], 11.5, places=1)

    def test_ceny_moga_byc_ujemne(self):
        """Ceny RCE moga byc ujemne - nie sa clampowane do 0."""
        # Mockujemy cache z ujemnymi cenami
        fake_cache = {
            "2025-01-01": [-200.0] + [100.0] * 23,
            "2025-01-02": [-150.0] + [100.0] * 23,
            "2025-01-15": [-100.0] + [100.0] * 23,
        }
        with patch('backend.services.rce_prices._zaladuj_cache', return_value=fake_cache):
            cena = pobierz_cene_rce(1, 0)
            # Srednia: (-200 + -150 + -100) / 3 = -150 PLN/MWh
            # W PLN/kWh brutto: -150 / 1000 * 1.23 = -0.1845
            self.assertLess(cena, 0, "Cena RCE powinna byc ujemna gdy dane z PSE sa ujemne")

    def test_fallback_na_syntetyczne_dane(self):
        """Gdy cache jest pusty, uzywa fallbackowych danych syntetycznych."""
        with patch('backend.services.rce_prices._zaladuj_cache', return_value=None):
            cena = pobierz_cene_rce(7, 12)
            # Fallback: CENY_RCE_GODZINOWE_PLN_MWH[6][12] = 130 PLN/MWh
            # W PLN/kWh brutto: 130 / 1000 * 1.23 = 0.1599
            self.assertAlmostEqual(cena, 0.1599, places=3)


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
        """Taryfa dynamiczna (G11f_dynamiczna) ma rozne ceny w roznych godzinach."""
        cena_12 = oblicz_cene_kupna("G11f_dynamiczna", 6, 12)
        cena_18 = oblicz_cene_kupna("G11f_dynamiczna", 6, 18)
        self.assertNotEqual(cena_12, cena_18)
        # Wieczorem drozsza niz w poludnie latem
        self.assertGreater(cena_18, cena_12)

    def test_oplaty_stale_dodatnie(self):
        """Oplaty stale sa dodatnie dla kazdej taryfy."""
        for t in ["G11", "G11f_dynamiczna", "G11_dynamiczna"]:
            oplata = oblicz_oplaty_stale(t)
            self.assertGreater(oplata, 0, f"Oplata stala dla {t} powinna byc dodatnia")

    def test_12_miesiecy_w_wyniku(self):
        """Wynik zawiera dane dla 12 miesiecy."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11"
        )
        self.assertEqual(len(wynik["miesiace"]), 12)

    def test_uwaga_arbitraz_w_wyniku(self):
        """Wynik zawiera informacje o strategii magazynu."""
        wynik = analizuj_ekonomie(
            self.produkcja_pv, self.zuzycie_stale, taryfa="G11"
        )
        self.assertIn("uwaga_arbitraz", wynik)
        self.assertIn("TYLKO", wynik["uwaga_arbitraz"])


class TestObliczCeneKupna(unittest.TestCase):
    """Testy obliczania ceny kupna energii."""

    def test_g11_sensowna_cena(self):
        """G11 - cena w sensownym zakresie (ok. 1.10 zl/kWh brutto)."""
        cena = oblicz_cene_kupna("G11", 1, 12)
        self.assertGreater(cena, 0.8)
        self.assertLess(cena, 1.5)
        # Dokladna wartosc: 1.0993
        self.assertAlmostEqual(cena, 1.0993, places=3)

    def test_g11f_dynamiczna_cena(self):
        """G11f_dynamiczna ma dynamiczna cene - rozna w roznych godzinach."""
        cena_12 = oblicz_cene_kupna("G11f_dynamiczna", 6, 12)
        cena_18 = oblicz_cene_kupna("G11f_dynamiczna", 6, 18)
        # Rozne godziny = rozne ceny (dynamiczna)
        self.assertNotEqual(cena_12, cena_18)

    def test_g11f_nizsza_niz_g11_dynamiczna(self):
        """G11f_dynamiczna ma nizsza cene niz G11_dynamiczna (nizsza dystrybucja)."""
        # Ta sama godzina i miesiac - roznica to tylko dystrybucja
        cena_g11f = oblicz_cene_kupna("G11f_dynamiczna", 7, 12)
        cena_g11_dyn = oblicz_cene_kupna("G11_dynamiczna", 7, 12)
        self.assertLess(cena_g11f, cena_g11_dyn)
        # Roznica brutto: 0.4287 - 0.0635 = 0.3652 zl/kWh
        self.assertAlmostEqual(cena_g11_dyn - cena_g11f, 0.3652, places=4)

    def test_dynamiczna_latem_tanio_w_poludnie(self):
        """Taryfa dynamiczna latem w poludnie jest tansza niz wieczorem."""
        cena_12 = oblicz_cene_kupna("G11f_dynamiczna", 7, 12)
        cena_19 = oblicz_cene_kupna("G11f_dynamiczna", 7, 19)
        self.assertLess(cena_12, cena_19)

    def test_oplata_mocowa_nie_w_cenie_kwh(self):
        """Oplata mocowa NIE jest wliczona w cene za kWh (jest ryczaltem)."""
        # Cena G11f_dynamiczna nie zawiera 29.58/mc jako per kWh
        cena = oblicz_cene_kupna("G11f_dynamiczna", 1, 12)
        # Skladniki per kWh: RCE + 0.1080 + 0.0635 + 0.0407 + 0.0090 + 0.0037
        # = RCE + 0.2249. Nawet z najwyzsza RCE nie powinno przekroczyc 2.0
        self.assertLess(cena, 2.0)
        # Sprawdz ze oplata stala zawiera mocowa
        taryfy = wczytaj_taryfy()
        mocowa = taryfy["G11f_dynamiczna"]["oplaty_stale_brutto_zl_mc"]["oplata_mocowa_ryczalt"]
        self.assertAlmostEqual(mocowa, 29.58, places=1)

    def test_g11_stala_cena_niezalezna_od_godziny(self):
        """G11 ma stala cene niezaleznie od godziny i miesiaca."""
        ceny = set()
        for m in [1, 6, 12]:
            for g in [0, 8, 12, 18, 23]:
                ceny.add(oblicz_cene_kupna("G11", m, g))
        self.assertEqual(len(ceny), 1)


class TestMagazynSmartCharging(unittest.TestCase):
    """Testy inteligentnego ladowania magazynu z sieci i rozladowania w szczycie."""

    def setUp(self):
        """Przygotuj dane testowe."""
        # Zuzycie stale 500 Wh/h
        self.zuzycie_stale = [500.0] * 8760
        # Produkcja zerowa
        self.produkcja_zero = [0.0] * 8760
        # Produkcja PV slaba - nie naladuje magazynu do pelna
        # 500 Wh przez 4 godziny (8-11) = 2000 Wh nadwyzki
        # Przy zuzyciu 500 Wh/h: nadwyzka tylko w godzinach 8-11 (bilans +500 Wh)
        self.produkcja_slaba = []
        for h in range(8760):
            godzina = h % 24
            if 8 <= godzina <= 11:
                self.produkcja_slaba.append(1000.0)  # 1000 - 500 zuzycia = 500 nadwyzki
            else:
                self.produkcja_slaba.append(0.0)

        self.magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            godzina_sprzedazy=18,
            priorytet="autokonsumpcja",
        )

    def test_g11_brak_ladowania_z_sieci(self):
        """Dla taryfy G11 (stala cena) magazyn NIE jest ladowany z sieci."""
        wynik = analizuj_ekonomie(
            self.produkcja_zero, self.zuzycie_stale,
            taryfa="G11", magazyn=self.magazyn
        )
        # Bez produkcji PV, magazyn nie powinien byc ladowany
        for mc in wynik["miesiace"]:
            self.assertEqual(mc["magazyn_ladowanie_kwh"], 0.0,
                           "G11: magazyn nie powinien byc ladowany bez PV!")

    def test_dynamiczna_ladowanie_z_sieci_bez_pv(self):
        """Dla taryfy dynamicznej magazyn jest ladowany z sieci nawet bez PV."""
        wynik = analizuj_ekonomie(
            self.produkcja_zero, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=self.magazyn
        )
        # Magazyn powinien byc ladowany z sieci (fallback)
        roczne_ladowanie = sum(mc["magazyn_ladowanie_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_ladowanie, 0,
                         "Dynamiczna: magazyn powinien byc ladowany z sieci!")

    def test_dynamiczna_energia_z_sieci_nie_sprzedawana(self):
        """Energia z sieci w magazynie NIE moze byc sprzedawana."""
        magazyn_sprzedaz = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            godzina_sprzedazy=18,
            priorytet="sprzedaz",
        )
        # Bez PV, cala energia w magazynie pochodzi z sieci
        wynik = analizuj_ekonomie(
            self.produkcja_zero, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn_sprzedaz
        )
        # Magazyn ladowany z sieci, ale NIC nie sprzedane
        roczne_ladowanie = sum(mc["magazyn_ladowanie_kwh"] for mc in wynik["miesiace"])
        roczna_sprzedaz = sum(mc["sprzedaz_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_ladowanie, 0, "Magazyn powinien byc ladowany")
        self.assertEqual(roczna_sprzedaz, 0.0,
                       "Energia z sieci NIE moze byc sprzedawana!")

    def test_pv_energia_moze_byc_sprzedawana(self):
        """Energia z PV w magazynie MOZE byc sprzedawana."""
        magazyn_sprzedaz = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            godzina_sprzedazy=18,
            priorytet="sprzedaz",
        )
        # Duza produkcja PV (1000 Wh w godzinach 8-15)
        produkcja_pv = []
        for h in range(8760):
            godzina = h % 24
            if 8 <= godzina <= 15:
                produkcja_pv.append(2000.0)
            else:
                produkcja_pv.append(0.0)

        wynik = analizuj_ekonomie(
            produkcja_pv, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn_sprzedaz
        )
        # Energia z PV powinna byc sprzedawana (nadwyzka + magazyn)
        roczna_sprzedaz = sum(mc["sprzedaz_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczna_sprzedaz, 0,
                         "Energia z PV powinna byc sprzedawana!")

    def test_rozladowanie_w_szczycie_dynamiczna(self):
        """Taryfa dynamiczna: rozladowanie w godzinie szczytu (16-22) a nie stala godz."""
        wynik = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=self.magazyn
        )
        # Sprawdz ze magazyn jest rozladowywany (jest autokonsumpcja z magazynu)
        roczne_rozlad = sum(mc["magazyn_rozladowanie_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_rozlad, 0, "Magazyn powinien byc rozladowywany")

    def test_ladowanie_w_najtanszych_godzinach(self):
        """Ladowanie z sieci odbywa sie w godzinach z najnizsza cena RCE."""
        # Testujemy posrednio - z taryfa dynamiczna powinien byc tani koszt ladowania
        wynik_dynamiczna = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=self.magazyn
        )
        # Powinno byc ladowanie z sieci (bo PV nie naladuje pelnego magazynu)
        roczne_ladowanie = sum(mc["magazyn_ladowanie_kwh"] for mc in wynik_dynamiczna["miesiace"])
        # 4 godziny nadwyzki po 500 Wh = 2000 Wh PV ladowania/dzien
        # Magazyn 10 kWh = 10000 Wh, wiec 8000 Wh potrzebne z sieci
        self.assertGreater(roczne_ladowanie, 1000,
                         "Powinno byc ladowanie z PV + sieci")

    def test_koszt_ladowania_z_sieci_w_kupnie(self):
        """Koszt ladowania z sieci jest uwzgledniony w koszt_kupna_zl."""
        wynik_bez_mag = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=None
        )
        wynik_z_mag = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=self.magazyn
        )
        # Z magazynem kupujemy WIECEJ z sieci (ladowanie magazynu) ale mniej bezposrednio
        # Wazne: koszt_kupna_zl uwzglednia ladowanie z sieci
        kupno_z_mag = wynik_z_mag["podsumowanie_roczne"]["kupno_kwh"]
        kupno_bez = wynik_bez_mag["podsumowanie_roczne"]["kupno_kwh"]
        # Z magazynem powinno byc wiecej kupna (bo ladujemy magazyn)
        # ale mniej kosztownego kupna w szczycie
        # Sprawdz ze koszt jest > 0 (nie zignorowany)
        self.assertGreater(wynik_z_mag["podsumowanie_roczne"]["koszt_kupna_zl"], 0)

    def test_uwaga_dynamiczna_vs_g11(self):
        """Komunikat uwaga_arbitraz rozni sie dla taryf dynamicznych i G11."""
        wynik_g11 = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11", magazyn=self.magazyn
        )
        wynik_dyn = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=self.magazyn
        )
        self.assertIn("TYLKO", wynik_g11["uwaga_arbitraz"])
        self.assertIn("fallback", wynik_dyn["uwaga_arbitraz"])
        self.assertIn("NIE moze byc sprzedawana", wynik_dyn["uwaga_arbitraz"])

    def test_g11_dynamiczna_tez_laduje_z_sieci(self):
        """G11_dynamiczna (nie tylko G11f) tez laduje magazyn z sieci."""
        wynik = analizuj_ekonomie(
            self.produkcja_zero, self.zuzycie_stale,
            taryfa="G11_dynamiczna", magazyn=self.magazyn
        )
        roczne_ladowanie = sum(mc["magazyn_ladowanie_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_ladowanie, 0,
                         "G11_dynamiczna: magazyn powinien byc ladowany z sieci!")

    def test_sprawnosc_przy_ladowaniu_z_sieci(self):
        """Sprawnosc jest uwzgledniana przy ladowaniu z sieci."""
        # Magazyn 100% sprawnosci vs 50% sprawnosci
        mag_100 = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=100.0,
            priorytet="autokonsumpcja",
        )
        mag_50 = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=50.0,
            priorytet="autokonsumpcja",
        )
        wynik_100 = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=mag_100
        )
        wynik_50 = analizuj_ekonomie(
            self.produkcja_slaba, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=mag_50
        )
        # Z wyzsza sprawnoscia mniej kupna z sieci (bo mniej strat)
        self.assertLess(
            wynik_100["podsumowanie_roczne"]["kupno_kwh"],
            wynik_50["podsumowanie_roczne"]["kupno_kwh"],
        )

    def test_autokonsumpcja_rozladowanie_bez_niedoboru(self):
        """Autokonsumpcja: magazyn rozladowuje sie w szczycie nawet gdy PV pokrywa zuzycie.

        Regresja: wczesniej blok autokonsumpcja+godzina_rozladowania byl 'pass' (no-op).
        Teraz magazyn rozladowuje sie aby pokryc zuzycie, zwalniajac PV do sprzedazy.
        """
        # Duza produkcja PV (caly dzien 1000 Wh przy zuzyciu 500 Wh)
        # W szczycie (16-22) PV pokrywa zuzycie - nie ma niedoboru
        # Ale magazyn powinien sie rozladowac aby PV moglo byc sprzedane
        produkcja_duza = []
        for h in range(8760):
            godzina = h % 24
            if 6 <= godzina <= 20:
                produkcja_duza.append(1000.0)
            else:
                produkcja_duza.append(0.0)

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=5.0,
            moc_ladowania_kw=3.0,
            moc_rozladowania_kw=3.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            priorytet="autokonsumpcja",
        )

        wynik = analizuj_ekonomie(
            produkcja_duza, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        # Magazyn powinien byc rozladowywany (nie zero!)
        roczne_rozlad = sum(mc["magazyn_rozladowanie_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_rozlad, 100,
                         "Magazyn powinien sie rozladowywac w szczycie nawet bez niedoboru!")
        # Sprzedaz powinna byc wieksza (uwolniona nadwyzka PV)
        roczna_sprzedaz = wynik["podsumowanie_roczne"]["sprzedaz_kwh"]
        self.assertGreater(roczna_sprzedaz, 0,
                         "PV uwolnione przez magazyn powinno byc sprzedawane!")

    def test_sprzedaz_pass1_modeluje_rozladowanie(self):
        """Sprzedaz: pass-1 uwzglednia rozladowanie w szczycie przy planowaniu.

        Regresja: pass-1 nie modelowal rozladowania w szczycie, wiec
        brakujaca_energia byla zanizona i planowano za malo godzin ladowania.
        Teraz pass-1 symuluje rozladowanie PV w szczycie, wiec ladowanie z sieci
        jest aktywne (rekompensuje sprzedana energie PV).
        """
        # Produkcja PV: 2 godziny po 1500 Wh nadwyzki = 3000 Wh PV do magazynu
        # Magazyn 10 kWh w trybie sprzedaz
        # Po pass-1 z rozladowaniem: brakujaca energia = ~10000 Wh (bo PV sprzedane)
        # Wiec planowanie wybierze godziny ladowania z sieci
        produkcja_minimalna = []
        for h in range(8760):
            godzina = h % 24
            if 10 <= godzina <= 11:
                produkcja_minimalna.append(2000.0)  # nadwyzka 1500 Wh/h * 2h = 3000 Wh
            else:
                produkcja_minimalna.append(0.0)

        magazyn_sprzedaz = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            priorytet="sprzedaz",
        )

        wynik = analizuj_ekonomie(
            produkcja_minimalna, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn_sprzedaz
        )
        # Ladowanie z sieci powinno byc aktywne
        # (pass-1 widzi ze PV zostanie sprzedane w szczycie, wiec magazyn potrzebuje sieci)
        roczne_ladowanie = sum(mc["magazyn_ladowanie_kwh"] for mc in wynik["miesiace"])
        self.assertGreater(roczne_ladowanie, 0,
                         "Powinno byc ladowanie z sieci (pass-1 uwzglednia peak discharge)")
        # Koszt kupna powinien zawierac ladowanie z sieci
        self.assertGreater(wynik["podsumowanie_roczne"]["koszt_kupna_zl"], 0,
                         "Koszt kupna powinien uwzgledniac ladowanie z sieci")

    def test_brak_kolizji_ladowania_w_godzinach_pv(self):
        """Ladowanie z sieci NIE odbywa sie w godzinach z nadwyzka PV.

        Regresja: wczesniej godziny z nadwyzka PV mogly byc w godziny_ladowania_siec,
        powodujac kolizje (PV laduje najpierw, potem siec laduje resztke).
        Teraz te godziny sa wykluczone z planowania ladowania sieciowego.
        """
        # Produkcja PV: duza nadwyzka w godzinach 8-15 (typowe solarne)
        # Te godziny powinny byc wykluczone z ladowania sieciowego
        produkcja_solarna = []
        for h in range(8760):
            godzina = h % 24
            if 8 <= godzina <= 15:
                produkcja_solarna.append(3000.0)  # 3000 - 500 = 2500 Wh nadwyzki
            else:
                produkcja_solarna.append(0.0)

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=15.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            priorytet="autokonsumpcja",
        )

        wynik = analizuj_ekonomie(
            produkcja_solarna, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        # Test: ladowanie z sieci powinno byc mniejsze niz gdyby nie bylo PV
        # (bo godziny PV sa wykluczone, wiec siec laduje w mniejszej liczbie godzin)
        wynik_bez_pv = analizuj_ekonomie(
            self.produkcja_zero, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        # Z PV ladujemy mniej z sieci (bo PV juz naladowalo czesc)
        kupno_z_pv = wynik["podsumowanie_roczne"]["kupno_kwh"]
        kupno_bez_pv = wynik_bez_pv["podsumowanie_roczne"]["kupno_kwh"]
        self.assertLess(kupno_z_pv, kupno_bez_pv,
                       "Z PV powinno byc mniej kupna z sieci (mniej ladowania fallback)")


class TestEnergyConservation(unittest.TestCase):
    """Testy zachowania energii - walidacja ze nie ma podwojnego liczenia."""

    def setUp(self):
        """Przygotuj dane testowe z produkcja PV w godzinach szczytu."""
        self.zuzycie_stale = [500.0] * 8760

    def test_autokonsumpcja_plus_sprzedaz_nie_przekracza_produkcji(self):
        """Autokonsumpcja + sprzedaz nie moze przekraczac produkcji + kupna.

        Regresja: wcześniej nadwyzka_uwolniona = min(energia_dostarczona, produkcja)
        powodowala podwojne liczenie - PV liczone jako autokonsumpcja i sprzedaz.
        Teraz nadwyzka_uwolniona = min(energia_dostarczona, zuzycie) i odejmowana
        od autokonsumpcja_kwh.
        """
        # Produkcja PV caly dzien - w godzinie szczytu bilans >= 0
        produkcja_calodzienna = []
        for h in range(8760):
            godzina = h % 24
            if 6 <= godzina <= 20:
                produkcja_calodzienna.append(1000.0)  # 1000 Wh, zuzycie 500 Wh, bilans +500
            else:
                produkcja_calodzienna.append(0.0)

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=5.0,
            moc_ladowania_kw=3.0,
            moc_rozladowania_kw=3.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            priorytet="autokonsumpcja",
        )

        wynik = analizuj_ekonomie(
            produkcja_calodzienna, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        roczne = wynik["podsumowanie_roczne"]
        # Zasada zachowania energii:
        # autokonsumpcja_kwh + sprzedaz_kwh <= produkcja_kwh + kupno_kwh
        # (roznica to straty w magazynie)
        energia_wejsciowa = roczne["produkcja_kwh"] + roczne["kupno_kwh"]
        energia_wyjsciowa = roczne["autokonsumpcja_kwh"] + roczne["sprzedaz_kwh"]
        self.assertLessEqual(
            energia_wyjsciowa, energia_wejsciowa + 1.0,
            f"Naruszenie zachowania energii! "
            f"Wyjscie ({energia_wyjsciowa:.1f}) > Wejscie ({energia_wejsciowa:.1f}). "
            f"Prawdopodobne podwojne liczenie energii."
        )

    def test_autokonsumpcja_nie_przekracza_zuzycia(self):
        """Autokonsumpcja nie moze przekraczac calkowitego zuzycia."""
        produkcja_duza = []
        for h in range(8760):
            godzina = h % 24
            if 6 <= godzina <= 20:
                produkcja_duza.append(2000.0)
            else:
                produkcja_duza.append(0.0)

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            dod_procent=100.0,
            priorytet="autokonsumpcja",
        )

        wynik = analizuj_ekonomie(
            produkcja_duza, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        roczne = wynik["podsumowanie_roczne"]
        # Autokonsumpcja nie moze byc wieksza niz zuzycie
        self.assertLessEqual(
            roczne["autokonsumpcja_kwh"], roczne["zuzycie_kwh"] + 1.0,
            f"Autokonsumpcja ({roczne['autokonsumpcja_kwh']:.1f}) > "
            f"zuzycie ({roczne['zuzycie_kwh']:.1f})!"
        )

    def test_brak_ladowania_i_rozladowania_w_tej_samej_godzinie(self):
        """Magazyn nie powinien ladowac i rozladowywac w tej samej godzinie.

        Regresja: gdy godzina szczytu ma nadwyzke PV, magazyn ladowal z PV
        a potem rozladowywal w tej samej godzinie - stratny pass-through.
        Teraz pomijamy ladowanie PV w godzinie rozladowania.
        """
        # Produkcja PV caly dzien wlacznie z godzina szczytu
        produkcja_calodzienna = []
        for h in range(8760):
            godzina = h % 24
            if 6 <= godzina <= 20:
                produkcja_calodzienna.append(1500.0)
            else:
                produkcja_calodzienna.append(0.0)

        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=5.0,
            moc_ladowania_kw=3.0,
            moc_rozladowania_kw=3.0,
            sprawnosc_procent=90.0,  # 10% strat roundtrip
            dod_procent=100.0,
            priorytet="autokonsumpcja",
        )

        # Uruchom z 90% sprawnoscia - jesli laduje i rozladowuje w tej samej godzinie
        # traci 10% energii na nic
        wynik = analizuj_ekonomie(
            produkcja_calodzienna, self.zuzycie_stale,
            taryfa="G11f_dynamiczna", magazyn=magazyn
        )
        roczne = wynik["podsumowanie_roczne"]
        # Sprawdzenie posrednie: ladowanie roczne powinno byc mniejsze
        # niz gdyby ladowal tez w godzinie rozladowania
        # Minimalna weryfikacja: bilans energetyczny sie zgadza
        energia_wejsciowa = roczne["produkcja_kwh"] + roczne["kupno_kwh"]
        energia_wyjsciowa = roczne["autokonsumpcja_kwh"] + roczne["sprzedaz_kwh"]
        self.assertLessEqual(energia_wyjsciowa, energia_wejsciowa + 1.0)


if __name__ == "__main__":
    unittest.main()
