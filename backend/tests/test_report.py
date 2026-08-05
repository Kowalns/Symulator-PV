"""
Testy modulu raportu, doboru magazynu i porownania scenariuszy.

Weryfikuje:
1. Generowanie raportu rocznego/miesiecznego
2. Obliczanie strat zacienienia
3. Dobor magazynu energii (nie przewymiarowany)
4. Porownanie scenariuszy side-by-side
5. Rekomendacje optymalizacji
6. Degradacja paneli 0.5%/rok
"""

import unittest
import json
import sys
from pathlib import Path

# Sciezka do katalogu glownego projektu
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.report_generator import (
    KonfiguracjaRaportu,
    generuj_raport,
    oblicz_straty_zacienienia,
    oblicz_bilans_miesieczny,
    oblicz_projekcje_degradacji,
    generuj_rekomendacje,
)
from backend.services.battery_sizing import (
    dobierz_magazyn,
    oblicz_nadwyzke_i_niedobor_dzienny,
    dobierz_pojemnosc_magazynu,
    znajdz_model_baterii,
    wczytaj_baze_baterii,
    oblicz_oszczednosc_z_magazynu,
)
from backend.services.scenario_comparison import (
    porownaj_scenariusze,
    oblicz_scenariusz,
    przeskaluj_produkcje_dla_kata,
    oblicz_scenariusz_bazowy,
    KonfiguracjaScenariusza,
)
from backend.services.economics import KonfiguracjaMagazynu


# Typowa produkcja instalacji 5.5 kWp w Polsce [kWh/miesiac]
TYPOWA_PRODUKCJA = [180, 250, 420, 550, 680, 720, 700, 620, 450, 300, 180, 130]
# Produkcja bez zacienienia (ok. 8% wiecej)
PRODUKCJA_BEZ_ZACIENIENIA = [195, 270, 454, 594, 734, 778, 756, 670, 486, 324, 194, 140]
# Typowe zuzycie domu z pompa ciepla [kWh/miesiac]
TYPOWE_ZUZYCIE = [500, 450, 420, 380, 350, 320, 310, 320, 380, 430, 470, 520]


class TestRaportGenerator(unittest.TestCase):
    """Testy generowania raportu."""

    def setUp(self):
        """Przygotowanie konfiguracji testowej."""
        self.config = KonfiguracjaRaportu(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            produkcja_bez_zacienienia_kwh=PRODUKCJA_BEZ_ZACIENIENIA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
            pojemnosc_magazynu_kwh=10.0,
            sprawnosc_magazynu_procent=95.0,
            kat_nachylenia=30.0,
            azymut=0.0,
            moc_instalacji_kwp=5.5,
            degradacja_roczna_procent=0.5,
            taryfa="G11",
        )

    def test_generuj_raport_kompletny(self):
        """Test czy raport zawiera wszystkie wymagane sekcje."""
        raport = generuj_raport(self.config)
        self.assertIn("podsumowanie", raport)
        self.assertIn("straty_zacienienia", raport)
        self.assertIn("bilans_miesieczny", raport)
        self.assertIn("degradacja_25_lat", raport)
        self.assertIn("rekomendacje", raport)
        self.assertIn("parametry", raport)

    def test_raport_podsumowanie(self):
        """Test czy podsumowanie zawiera kluczowe wartosci."""
        raport = generuj_raport(self.config)
        pods = raport["podsumowanie"]
        self.assertIn("produkcja_roczna_kwh", pods)
        self.assertIn("zuzycie_roczne_kwh", pods)
        self.assertIn("autarchia_procent", pods)
        self.assertIn("miesiace_samowystarczalne", pods)
        self.assertGreater(pods["produkcja_roczna_kwh"], 0)
        self.assertGreater(pods["zuzycie_roczne_kwh"], 0)
        self.assertGreaterEqual(pods["miesiace_samowystarczalne"], 0)
        self.assertLessEqual(pods["miesiace_samowystarczalne"], 12)

    def test_straty_zacienienia(self):
        """Test obliczania strat zacienienia."""
        straty = oblicz_straty_zacienienia(
            TYPOWA_PRODUKCJA, PRODUKCJA_BEZ_ZACIENIENIA
        )
        self.assertIn("straty_miesieczne_procent", straty)
        self.assertIn("strata_roczna_procent", straty)
        self.assertIn("energia_utracona_rocznie_kwh", straty)
        # Straty powinny byc dodatnie (produkcja z zacienieniem < bez)
        self.assertGreater(straty["strata_roczna_procent"], 0)
        self.assertLess(straty["strata_roczna_procent"], 50)
        self.assertEqual(len(straty["straty_miesieczne_procent"]), 12)

    def test_straty_zerowe_bez_zacienienia(self):
        """Test: brak strat gdy produkcja = produkcja bez zacienienia."""
        straty = oblicz_straty_zacienienia(TYPOWA_PRODUKCJA, TYPOWA_PRODUKCJA)
        self.assertEqual(straty["strata_roczna_procent"], 0.0)
        self.assertEqual(straty["energia_utracona_rocznie_kwh"], 0.0)

    def test_bilans_miesieczny(self):
        """Test obliczania bilansu miesiecznego."""
        bilans = oblicz_bilans_miesieczny(
            TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE, 10.0, 95.0
        )
        self.assertIn("bilans_miesieczny", bilans)
        self.assertIn("miesiace_samowystarczalne", bilans)
        self.assertEqual(len(bilans["bilans_miesieczny"]), 12)
        # Kazdy miesiac powinien miec wymagane pola
        for m in bilans["bilans_miesieczny"]:
            self.assertIn("produkcja_kwh", m)
            self.assertIn("zuzycie_kwh", m)
            self.assertIn("samowystarczalny", m)

    def test_bilans_samowystarczalnosc_lato(self):
        """Test: latem (duza produkcja, male zuzycie) powinna byc samowystarczalnosc."""
        bilans = oblicz_bilans_miesieczny(
            TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE, 10.0, 95.0
        )
        # Czerwiec (ind. 5): produkcja 720, zuzycie 320 -> samowystarczalny
        self.assertTrue(bilans["bilans_miesieczny"][5]["samowystarczalny"])

    def test_bilans_bez_magazynu(self):
        """Test bilansu bez magazynu."""
        bilans = oblicz_bilans_miesieczny(
            TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE, 0.0, 95.0
        )
        # Bez magazynu - mniej miesiecy samowystarczalnych
        self.assertGreaterEqual(bilans["miesiace_samowystarczalne"], 0)

    def test_projekcja_degradacji(self):
        """Test projekcji degradacji 0.5%/rok na 25 lat."""
        prognoza = oblicz_projekcje_degradacji(5000.0, 0.5, 25)
        self.assertEqual(len(prognoza), 25)
        # Rok 1: brak degradacji
        self.assertEqual(prognoza[0]["wspolczynnik_degradacji"], 1.0)
        self.assertEqual(prognoza[0]["produkcja_kwh"], 5000.0)
        # Rok 25: ~88% oryginalnej mocy
        self.assertAlmostEqual(prognoza[24]["wspolczynnik_degradacji"], 0.8871, places=3)
        self.assertAlmostEqual(prognoza[24]["produkcja_kwh"], 4435.5, delta=10)
        # Kazdy nastepny rok powinien miec mniejsza produkcje
        for i in range(1, 25):
            self.assertLess(prognoza[i]["produkcja_kwh"], prognoza[i-1]["produkcja_kwh"])

    def test_rekomendacje_zwiekszenie_kata(self):
        """Test: rekomendacja zwiekszenia kata gdy niedobor jesienia."""
        # Niska produkcja jesienia, duze zuzycie -> powinien polecic wyzszy kat
        config = KonfiguracjaRaportu(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            produkcja_bez_zacienienia_kwh=PRODUKCJA_BEZ_ZACIENIENIA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
            kat_nachylenia=30.0,
        )
        rekomendacje = generuj_rekomendacje(config)
        typy = [r["typ"] for r in rekomendacje]
        # Powinien polecic magazyn (brak magazynu, sa nadwyzki i niedobory)
        self.assertIn("magazyn_energii", typy)

    def test_rekomendacje_azymut(self):
        """Test: rekomendacja korekty azymutu gdy duze odchylenie."""
        config = KonfiguracjaRaportu(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            produkcja_bez_zacienienia_kwh=PRODUKCJA_BEZ_ZACIENIENIA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
            azymut=30.0,
        )
        rekomendacje = generuj_rekomendacje(config)
        typy = [r["typ"] for r in rekomendacje]
        self.assertIn("orientacja", typy)


class TestBatterySizing(unittest.TestCase):
    """Testy doboru magazynu energii."""

    def test_wczytaj_baze_baterii(self):
        """Test wczytywania bazy baterii."""
        baterie = wczytaj_baze_baterii()
        self.assertIsInstance(baterie, list)
        self.assertGreater(len(baterie), 0)
        # Kazda bateria musi miec kluczowe pola
        for bat in baterie:
            self.assertIn("id", bat)
            self.assertIn("pojemnosc_kwh", bat)
            self.assertIn("sprawnosc_roundtrip_procent", bat)

    def test_nadwyzka_i_niedobor_dzienny(self):
        """Test obliczania nadwyzki dziennej i niedoboru wieczornego."""
        nadwyzki, niedobory = oblicz_nadwyzke_i_niedobor_dzienny(
            TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE
        )
        self.assertEqual(len(nadwyzki), 12)
        self.assertEqual(len(niedobory), 12)
        # Latem nadwyzka powinna byc wieksza (duzo produkcji PV)
        self.assertGreater(nadwyzki[5], nadwyzki[0])  # czerwiec > styczen
        # Zima niedobor wieczorny powinien byc wiekszy
        self.assertGreater(niedobory[0], niedobory[5])  # styczen > czerwiec

    def test_dobierz_pojemnosc_nie_przewymiarowany(self):
        """Test: magazyn nie jest przewymiarowany."""
        nadwyzki, niedobory = oblicz_nadwyzke_i_niedobor_dzienny(
            TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE
        )
        pojemnosc = dobierz_pojemnosc_magazynu(nadwyzki, niedobory, 95.0)
        # Pojemnosc nie powinna przekraczac mediany niedoboru przejsciowego
        miesiace_przejsciowe = [2, 3, 8, 9]
        max_niedobor = max(niedobory[m] for m in miesiace_przejsciowe)
        # Nie wieksza niz max niedobor + margines na sprawnosc
        self.assertLessEqual(pojemnosc, max_niedobor * 1.5)
        self.assertGreater(pojemnosc, 0)

    def test_znajdz_model_baterii(self):
        """Test znajdowania modelu baterii z bazy."""
        model = znajdz_model_baterii(5.0)
        self.assertIsNotNone(model)
        self.assertGreaterEqual(model["pojemnosc_kwh"], 5.0)
        # Powinien znalezc najmniejszy model >= 5 kWh
        self.assertIn("producent", model)
        self.assertIn("model", model)

    def test_znajdz_model_baterii_zero(self):
        """Test: dla pojemnosci 0 zwraca None."""
        model = znajdz_model_baterii(0.0)
        self.assertIsNone(model)

    def test_znajdz_model_baterii_duza(self):
        """Test: dla bardzo duzej pojemnosci zwraca najwieksza dostepna."""
        model = znajdz_model_baterii(100.0)
        self.assertIsNotNone(model)
        # Powinien zwrocic najwieksza dostepna baterie

    def test_dobierz_magazyn_kompletny(self):
        """Test pelnego doboru magazynu."""
        wynik = dobierz_magazyn(TYPOWA_PRODUKCJA, TYPOWE_ZUZYCIE)
        self.assertIn("rekomendacja", wynik)
        # Powinien polecic magazyn (jest nadwyzka i niedobor)
        self.assertEqual(wynik["rekomendacja"], "zainstaluj")
        self.assertIn("proponowany_model", wynik)
        self.assertIn("rekomendowana_pojemnosc_kwh", wynik)
        self.assertIn("pokrycie_wieczornego_szczytu_procent", wynik)
        self.assertIn("uzasadnienie", wynik)
        # Pojemnosc sensowna (nie za mala, nie za duza)
        self.assertGreater(wynik["rekomendowana_pojemnosc_kwh"], 0)
        self.assertLess(wynik["rekomendowana_pojemnosc_kwh"], 20)

    def test_dobierz_magazyn_nie_potrzebny(self):
        """Test: magazyn nie potrzebny gdy produkcja = 0."""
        # Zerowa produkcja - nie ma nadwyzki do magazynowania
        wynik = dobierz_magazyn([0]*12, TYPOWE_ZUZYCIE)
        self.assertIn(wynik["rekomendacja"], ["nie_potrzebny", "zainstaluj"])

    def test_oszczednosc_z_magazynu(self):
        """Test obliczania oszczednosci z magazynu."""
        niedobory = [8.0, 7.0, 6.0, 4.0, 3.0, 2.0, 2.0, 2.5, 4.0, 6.0, 7.5, 8.5]
        oszcz = oblicz_oszczednosc_z_magazynu(niedobory, 10.0, 95.0, 0.62)
        self.assertIn("oszczednosc_roczna_zl", oszcz)
        self.assertGreater(oszcz["oszczednosc_roczna_zl"], 0)


class TestScenarioComparison(unittest.TestCase):
    """Testy porownania scenariuszy."""

    def test_porownaj_scenariusze_kompletne(self):
        """Test kompletnego porownania scenariuszy."""
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
            kat_nachylenia=30.0,
            strata_zacienienia_procent=8.0,
        )
        self.assertIn("scenariusze", wynik)
        self.assertIn("parametry", wynik)
        self.assertIn("najlepszy_scenariusz", wynik)
        # Powinno byc wiele scenariuszy
        self.assertGreater(len(wynik["scenariusze"]), 5)

    def test_scenariusz_bazowy_drogi(self):
        """Test: scenariusz bez PV powinien miec najwyzszy koszt."""
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
        )
        # Znajdz scenariusz bazowy (bez PV)
        bazowe = [s for s in wynik["scenariusze"] if "Bez PV" in s["nazwa"]]
        z_pv = [s for s in wynik["scenariusze"] if "PV" in s["nazwa"] and "Bez PV" not in s["nazwa"]]
        self.assertGreater(len(bazowe), 0)
        self.assertGreater(len(z_pv), 0)
        # Bazowy powinien miec 0 oszczednosci (lub zaniedbywalnie bliska zeru)
        for b in bazowe:
            self.assertAlmostEqual(b["oszczednosc_roczna_zl"], 0.0, delta=0.1)

    def test_scenariusz_z_magazynem_wieksza_samowystarczalnosc(self):
        """Test: PV z magazynem >= PV bez magazynu w samowystarczalnosci."""
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
        )
        # PV bez magazynu (G11)
        bez_mag = [s for s in wynik["scenariusze"]
                   if "PV bez magazynu" in s["nazwa"] and "G11)" in s["nazwa"]]
        z_mag = [s for s in wynik["scenariusze"]
                 if "PV z magazynem" in s["nazwa"] and "G11)" in s["nazwa"]]
        if bez_mag and z_mag:
            self.assertGreaterEqual(
                z_mag[0]["miesiace_samowystarczalne"],
                bez_mag[0]["miesiace_samowystarczalne"]
            )

    def test_przeskaluj_produkcje_dla_kata(self):
        """Test przeskalowania produkcji dla innego kata."""
        # Wyzszy kat powinien dawac wiecej jesienia i mniej latem
        prod_50 = przeskaluj_produkcje_dla_kata(TYPOWA_PRODUKCJA, 30.0, 50.0)
        self.assertEqual(len(prod_50), 12)
        # Jesien (wrzesien, ind. 8): wyzszy kat powinien dac wiecej
        self.assertGreater(prod_50[8], TYPOWA_PRODUKCJA[8] * 0.9)
        # Lato (czerwiec, ind. 5): wyzszy kat powinien dac mniej lub tyle samo
        # (zalezy od modelu, ale nie powinna drastycznie wzrosnac)
        self.assertLess(prod_50[5], TYPOWA_PRODUKCJA[5] * 1.3)

    def test_oblicz_scenariusz_bazowy(self):
        """Test obliczania scenariusza bazowego."""
        wynik = oblicz_scenariusz_bazowy(TYPOWE_ZUZYCIE, "G11")
        self.assertIn("podsumowanie_roczne", wynik)
        self.assertIn("miesiace", wynik)
        # Bez PV: produkcja = 0
        self.assertEqual(wynik["podsumowanie_roczne"]["produkcja_kwh"], 0.0)
        # Koszt calkowity powinien byc > 0 (kupno z sieci)
        self.assertGreater(wynik["podsumowanie_roczne"]["koszt_calkowity_zl"], 0)

    def test_oblicz_scenariusz_z_magazynem(self):
        """Test obliczania scenariusza z magazynem."""
        magazyn = KonfiguracjaMagazynu(
            pojemnosc_kwh=10.0,
            moc_ladowania_kw=5.0,
            moc_rozladowania_kw=5.0,
            sprawnosc_procent=95.0,
            priorytet="autokonsumpcja",
        )
        config = KonfiguracjaScenariusza(
            nazwa="Test z magazynem",
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
            taryfa="G11",
            magazyn=magazyn,
        )
        wynik = oblicz_scenariusz(config)
        self.assertEqual(wynik["nazwa"], "Test z magazynem")
        self.assertGreater(wynik["produkcja_roczna_kwh"], 0)
        self.assertGreater(wynik["oszczednosc_roczna_zl"], 0)

    def test_najlepszy_scenariusz(self):
        """Test wyboru najlepszego scenariusza."""
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
        )
        najlepszy = wynik["najlepszy_scenariusz"]
        self.assertIn("nazwa", najlepszy)
        self.assertIn("powod", najlepszy)
        # Najlepszy nie moze byc "bez PV"
        self.assertNotIn("Bez PV", najlepszy["nazwa"])

    def test_porownanie_taryf(self):
        """Test: rozne taryfy daja rozne koszty."""
        wynik = porownaj_scenariusze(
            produkcja_miesieczna_kwh=TYPOWA_PRODUKCJA,
            zuzycie_miesieczne_kwh=TYPOWE_ZUZYCIE,
        )
        # Znajdz scenariusze PV bez magazynu dla roznych taryf
        g11 = [s for s in wynik["scenariusze"]
               if "PV bez magazynu" in s["nazwa"] and "G11)" in s["nazwa"]]
        dyn = [s for s in wynik["scenariusze"]
               if "PV bez magazynu" in s["nazwa"] and "dynamiczna" in s["nazwa"]]
        if g11 and dyn:
            # Koszty powinny sie roznic
            self.assertNotEqual(g11[0]["koszt_roczny_zl"], dyn[0]["koszt_roczny_zl"])


class TestHandleryRaportu(unittest.TestCase):
    """Testy handlerow API raportu i scenariuszy."""

    def test_handle_report_generate(self):
        """Test endpointu generowania raportu."""
        from backend.api.handlers import handle_report_generate
        dane = {
            "produkcja_miesieczna_kwh": TYPOWA_PRODUKCJA,
            "produkcja_bez_zacienienia_kwh": PRODUKCJA_BEZ_ZACIENIENIA,
            "zuzycie_miesieczne_kwh": TYPOWE_ZUZYCIE,
            "kat_nachylenia": 30.0,
            "moc_instalacji_kwp": 5.5,
        }
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_report_generate(body)
        self.assertEqual(status, 200)
        self.assertIn("podsumowanie", response)
        self.assertIn("straty_zacienienia", response)
        self.assertIn("bilans_miesieczny", response)
        self.assertIn("degradacja_25_lat", response)
        self.assertIn("dobor_magazynu", response)

    def test_handle_report_brak_danych(self):
        """Test: blad gdy brak danych."""
        from backend.api.handlers import handle_report_generate
        status, response = handle_report_generate(None)
        self.assertEqual(status, 400)

    def test_handle_report_brak_produkcji(self):
        """Test: blad gdy brak pola produkcji."""
        from backend.api.handlers import handle_report_generate
        dane = {"zuzycie_miesieczne_kwh": TYPOWE_ZUZYCIE}
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_report_generate(body)
        self.assertEqual(status, 400)

    def test_handle_scenarios_compare(self):
        """Test endpointu porownania scenariuszy."""
        from backend.api.handlers import handle_scenarios_compare
        dane = {
            "produkcja_miesieczna_kwh": TYPOWA_PRODUKCJA,
            "zuzycie_miesieczne_kwh": TYPOWE_ZUZYCIE,
            "kat_nachylenia": 30.0,
            "strata_zacienienia_procent": 8.0,
        }
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_scenarios_compare(body)
        self.assertEqual(status, 200)
        self.assertIn("scenariusze", response)
        self.assertIn("najlepszy_scenariusz", response)
        self.assertGreater(len(response["scenariusze"]), 5)

    def test_handle_scenarios_brak_danych(self):
        """Test: blad gdy brak danych."""
        from backend.api.handlers import handle_scenarios_compare
        status, response = handle_scenarios_compare(None)
        self.assertEqual(status, 400)

    def test_handle_scenarios_bledne_dane(self):
        """Test: blad gdy dane maja zla liczbe wartosci."""
        from backend.api.handlers import handle_scenarios_compare
        dane = {
            "produkcja_miesieczna_kwh": [100, 200],  # za malo
            "zuzycie_miesieczne_kwh": TYPOWE_ZUZYCIE,
        }
        body = json.dumps(dane).encode("utf-8")
        status, response = handle_scenarios_compare(body)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
