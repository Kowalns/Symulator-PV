"""
Testy jednostkowe profilu zuzycia energii.

Weryfikuje:
1. Profil godzinowy ma 8760 wartosci
2. Roczne sumy zuzycia sa prawidlowe (nie zawyzone 24x!)
3. Profil pompy ciepla CO sumuje sie do 1.0 (znormalizowany)
4. Profil CWU sumuje sie do 1.0
5. Zuzycie roczne: 250W bazowe + 5000 kWh CO + 2000 kWh CWU = ~9200 kWh/rok
6. Sezonowosc wplywa na zuzycie bazowe
7. Pompa ciepla dziala tylko w miesiacach grzewczych
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.services.energy_profile import (
    ProfilZuzycia,
    oblicz_profil_godzinowy,
    oblicz_zuzycie_miesieczne,
    stworz_profil_z_danych,
    PROFIL_GODZINOWY_POMPY_CO,
    PROFIL_GODZINOWY_CWU,
    MIESIACE_GRZEWCZE,
    SEZONOWOSC_MIESIECZNA,
)


class TestProfilNormalizacja(unittest.TestCase):
    """Testy normalizacji profili godzinowych."""

    def test_profil_co_sumuje_sie_do_1(self):
        """Profil godzinowy pompy ciepla CO sumuje sie do 1.0."""
        suma = sum(PROFIL_GODZINOWY_POMPY_CO)
        self.assertAlmostEqual(suma, 1.0, places=6,
                               msg=f"PROFIL_GODZINOWY_POMPY_CO sumuje sie do {suma}, powinno byc 1.0")

    def test_profil_cwu_sumuje_sie_do_1(self):
        """Profil godzinowy CWU sumuje sie do 1.0."""
        suma = sum(PROFIL_GODZINOWY_CWU)
        self.assertAlmostEqual(suma, 1.0, places=6,
                               msg=f"PROFIL_GODZINOWY_CWU sumuje sie do {suma}, powinno byc 1.0")

    def test_profil_co_24_wartosci(self):
        """Profil CO ma dokladnie 24 wartosci."""
        self.assertEqual(len(PROFIL_GODZINOWY_POMPY_CO), 24)

    def test_profil_cwu_24_wartosci(self):
        """Profil CWU ma dokladnie 24 wartosci."""
        self.assertEqual(len(PROFIL_GODZINOWY_CWU), 24)

    def test_profil_co_wszystkie_dodatnie(self):
        """Wszystkie wartosci profilu CO sa dodatnie."""
        for i, v in enumerate(PROFIL_GODZINOWY_POMPY_CO):
            self.assertGreater(v, 0, f"Godzina {i} ma wartosc <= 0")

    def test_profil_cwu_wszystkie_dodatnie(self):
        """Wszystkie wartosci profilu CWU sa dodatnie."""
        for i, v in enumerate(PROFIL_GODZINOWY_CWU):
            self.assertGreater(v, 0, f"Godzina {i} ma wartosc <= 0")


class TestRoczneSumyZuzycia(unittest.TestCase):
    """Testy rocznych sum zuzycia - KRYTYCZNE (weryfikacja braku bledu *24)."""

    def test_samo_bazowe_250w(self):
        """250W bazowe powinno dac ~2190 kWh/rok (250 * 8760 / 1000)."""
        profil = ProfilZuzycia(zuzycie_bazowe_w=250.0)
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        roczne = sum(mc)
        # 250W * 8760h = 2190 kWh (z sezonowoscia moze sie nieznacznie roznic)
        self.assertAlmostEqual(roczne, 2190.0, delta=50,
                               msg=f"250W bazowe = {roczne:.0f} kWh/rok (spodziewane ~2190)")

    def test_250w_plus_5000_co_plus_2000_cwu(self):
        """250W + 5000 kWh CO + 2000 kWh CWU powinno dac ~9200 kWh/rok (NIE 182 MWh!)."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=250.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=5000.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=2000.0,
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        roczne = sum(mc)
        # 2190 (bazowe) + 5000 (CO) + 2000 (CWU) = 9190 kWh
        # Z sezonowoscia moze byc +/- 5%
        self.assertGreater(roczne, 8500,
                           msg=f"Roczne zuzycie {roczne:.0f} kWh jest za niskie (min 8500)")
        self.assertLess(roczne, 10500,
                        msg=f"Roczne zuzycie {roczne:.0f} kWh jest za wysokie (max 10500)")
        # Krytyczny test: NIE moze byc 182 MWh (blad *24)!
        self.assertLess(roczne, 50000,
                        msg=f"BLAD KRYTYCZNY: zuzycie {roczne:.0f} kWh >> 50 MWh - prawdopodobnie blad *24!")

    def test_samo_co_5000_kwh(self):
        """5000 kWh CO rocznie powinno dac ~5000 kWh dodatkowego zuzycia."""
        profil_bez = ProfilZuzycia(zuzycie_bazowe_w=0.0)
        profil_z = ProfilZuzycia(
            zuzycie_bazowe_w=0.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=5000.0,
        )
        godz_bez = oblicz_profil_godzinowy(profil_bez, 2025)
        godz_z = oblicz_profil_godzinowy(profil_z, 2025)
        mc_bez = oblicz_zuzycie_miesieczne(godz_bez, 2025)
        mc_z = oblicz_zuzycie_miesieczne(godz_z, 2025)
        roznica = sum(mc_z) - sum(mc_bez)
        # Roznica powinna byc ~5000 kWh (nie 120000 kWh!)
        self.assertAlmostEqual(roznica, 5000.0, delta=100,
                               msg=f"Dodatkowe zuzycie CO = {roznica:.0f} kWh (oczekiwane ~5000)")

    def test_samo_cwu_2000_kwh(self):
        """2000 kWh CWU rocznie powinno dac ~2000 kWh dodatkowego zuzycia."""
        profil_bez = ProfilZuzycia(zuzycie_bazowe_w=0.0)
        profil_z = ProfilZuzycia(
            zuzycie_bazowe_w=0.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=2000.0,
        )
        godz_bez = oblicz_profil_godzinowy(profil_bez, 2025)
        godz_z = oblicz_profil_godzinowy(profil_z, 2025)
        mc_bez = oblicz_zuzycie_miesieczne(godz_bez, 2025)
        mc_z = oblicz_zuzycie_miesieczne(godz_z, 2025)
        roznica = sum(mc_z) - sum(mc_bez)
        # Roznica powinna byc ~2000 kWh (nie 48000 kWh!)
        self.assertAlmostEqual(roznica, 2000.0, delta=50,
                               msg=f"Dodatkowe zuzycie CWU = {roznica:.0f} kWh (oczekiwane ~2000)")

    def test_duzy_dom_nie_przekracza_30_mwh(self):
        """Nawet duzy dom (500W bazowe + 8000 CO + 3000 CWU) nie przekracza 30 MWh/rok."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=500.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=8000.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=3000.0,
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        roczne = sum(mc)
        # 4380 + 8000 + 3000 = ~15380 kWh - sensowna wartosc
        self.assertLess(roczne, 30000,
                        msg=f"Roczne zuzycie {roczne:.0f} kWh > 30 MWh - cos jest nie tak!")
        self.assertGreater(roczne, 12000,
                           msg=f"Roczne zuzycie {roczne:.0f} kWh < 12 MWh - za malo")


class TestSezonowoscPompyCiepla(unittest.TestCase):
    """Testy sezonowosci zuzycia pompy ciepla."""

    def test_co_tylko_w_miesiacach_grzewczych(self):
        """Pompa ciepla CO zuzywa tylko w miesiacach grzewczych (styczen-kwiecien, pazdziernik-grudzien)."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=0.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=5000.0,
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        # Miesiace niegrzewcze (maj=5, czerwiec=6, lipiec=7, sierpien=8, wrzesien=9)
        # powinny miec zuzycie = 0 (brak bazowego, brak CO)
        for m in [4, 5, 6, 7, 8]:  # indeksy 0-based (maj-wrzesien)
            self.assertAlmostEqual(mc[m], 0.0, places=1,
                                   msg=f"Miesiac {m+1} nie powinien miec zuzycia CO: {mc[m]}")

    def test_cwu_caly_rok(self):
        """CWU zuzywa rownomiernie przez caly rok."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=0.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=2400.0,  # 200 kWh/mc srednia
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        # Kazdy miesiac powinien miec zuzycie ~200 kWh (2400/12)
        for m in range(12):
            self.assertGreater(mc[m], 100,
                               msg=f"Miesiac {m+1}: zuzycie CWU {mc[m]:.0f} kWh za male")
            self.assertLess(mc[m], 300,
                            msg=f"Miesiac {m+1}: zuzycie CWU {mc[m]:.0f} kWh za duze")

    def test_styczen_wiecej_niz_lipiec_z_co(self):
        """Styczen (grzewczy) ma znacznie wiecej zuzycia niz lipiec (niegrzewczy)."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=200.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=6000.0,
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        mc = oblicz_zuzycie_miesieczne(godz, 2025)
        # Styczen (ind. 0) powinien miec wiecej niz lipiec (ind. 6)
        self.assertGreater(mc[0], mc[6] * 2,
                           msg=f"Styczen ({mc[0]:.0f}) powinien byc >2x lipiec ({mc[6]:.0f})")


class TestProfilZ_Danych(unittest.TestCase):
    """Testy tworzenia profilu z danych API."""

    def test_domyslny_profil(self):
        """Domyslne wartosci profilu."""
        profil = stworz_profil_z_danych({})
        self.assertEqual(profil.zuzycie_bazowe_w, 200.0)
        self.assertFalse(profil.pompa_ciepla_co)
        self.assertFalse(profil.pompa_ciepla_cwu)

    def test_profil_z_pompa(self):
        """Profil z pompa ciepla z danych API."""
        dane = {
            "zuzycie_bazowe_w": 300,
            "pompa_ciepla_co": True,
            "zuzycie_co_roczne_kwh": 7000,
            "pompa_ciepla_cwu": True,
            "zuzycie_cwu_roczne_kwh": 2500,
        }
        profil = stworz_profil_z_danych(dane)
        self.assertEqual(profil.zuzycie_bazowe_w, 300.0)
        self.assertTrue(profil.pompa_ciepla_co)
        self.assertEqual(profil.zuzycie_co_roczne_kwh, 7000.0)
        self.assertTrue(profil.pompa_ciepla_cwu)
        self.assertEqual(profil.zuzycie_cwu_roczne_kwh, 2500.0)

    def test_profil_8760_godzin(self):
        """Kazdy profil generuje dokladnie 8760 wartosci."""
        dane = {
            "zuzycie_bazowe_w": 250,
            "pompa_ciepla_co": True,
            "zuzycie_co_roczne_kwh": 5000,
            "pompa_ciepla_cwu": True,
            "zuzycie_cwu_roczne_kwh": 2000,
        }
        profil = stworz_profil_z_danych(dane)
        godz = oblicz_profil_godzinowy(profil, 2025)
        self.assertEqual(len(godz), 8760)

    def test_wszystkie_wartosci_nieujemne(self):
        """Wszystkie wartosci zuzycia godzinowego sa >= 0."""
        profil = ProfilZuzycia(
            zuzycie_bazowe_w=250.0,
            pompa_ciepla_co=True,
            zuzycie_co_roczne_kwh=5000.0,
            pompa_ciepla_cwu=True,
            zuzycie_cwu_roczne_kwh=2000.0,
        )
        godz = oblicz_profil_godzinowy(profil, 2025)
        for i, v in enumerate(godz):
            self.assertGreaterEqual(v, 0.0, f"Godzina {i} ma ujemne zuzycie: {v}")


if __name__ == "__main__":
    unittest.main()
