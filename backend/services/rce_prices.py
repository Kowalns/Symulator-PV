"""
Serwis cen RCE (Rynek Dnia Nastepnego) z TGE (Towarowa Gielda Energii).

Zawiera reprezentatywne historyczne dane cenowe RCE dla Polski.
Dane oparte na srednich godzinowych cenach z TGE za 2023-2024.

Kluczowe obserwacje:
- Latem w godzinach 10-15 ceny sa najnizsze (duzo produkcji PV w systemie)
- Wieczorem 17-21 ceny sa najwyzsze (szczyt zapotrzebowania)
- Zima ceny ogolnie wyzsze (mniejsza produkcja PV, wieksze zuzycie)
- Noca ceny niskie (male zuzycie)

Ceny w PLN/MWh - przeliczane na PLN/kWh przy uzyciu.
"""

from typing import List, Dict, Optional


# Srednie godzinowe ceny RCE [PLN/MWh] dla kazdego miesiaca
# Dane reprezentatywne na podstawie historycznych notowan TGE 2023-2024
# Indeks zewnetrzny: miesiac (0=styczen, 11=grudzien)
# Indeks wewnetrzny: godzina (0-23)
# Ceny uwzgledniaja efekt "duck curve" - niskie ceny w srodku dnia latem
CENY_RCE_GODZINOWE_PLN_MWH = [
    # Styczen - wysokie ceny, brak efektu PV
    [380, 350, 330, 320, 340, 380, 450, 520, 550, 530, 500, 480,
     470, 460, 470, 490, 530, 580, 600, 560, 500, 450, 420, 390],
    # Luty - podobnie do stycznia
    [360, 330, 310, 300, 320, 360, 430, 500, 530, 510, 480, 460,
     450, 440, 450, 470, 510, 560, 580, 540, 480, 430, 400, 370],
    # Marzec - poczatek efektu PV w poludnie
    [320, 290, 270, 260, 280, 320, 390, 450, 470, 440, 400, 370,
     350, 340, 350, 380, 430, 490, 520, 480, 420, 380, 350, 330],
    # Kwiecien - wyrazny efekt PV
    [280, 250, 230, 220, 240, 270, 340, 390, 380, 340, 290, 260,
     240, 230, 250, 290, 370, 430, 460, 420, 370, 330, 300, 280],
    # Maj - silny efekt PV, niskie ceny w poludnie
    [250, 220, 200, 190, 210, 240, 300, 340, 310, 260, 210, 180,
     160, 150, 170, 220, 310, 380, 410, 380, 330, 290, 270, 250],
    # Czerwiec - najsilniejszy efekt PV, najnizsze ceny poludniowe
    [230, 200, 180, 170, 190, 220, 270, 310, 270, 220, 170, 140,
     120, 110, 130, 180, 280, 360, 390, 360, 310, 270, 250, 230],
    # Lipiec - bardzo silny efekt PV
    [240, 210, 190, 180, 200, 230, 280, 320, 280, 230, 180, 150,
     130, 120, 140, 190, 290, 370, 400, 370, 320, 280, 260, 240],
    # Sierpien - silny efekt PV ale krotsze dni
    [260, 230, 210, 200, 220, 250, 310, 350, 320, 270, 220, 190,
     170, 160, 180, 230, 320, 390, 420, 380, 340, 300, 280, 260],
    # Wrzesien - malejacy efekt PV
    [300, 270, 250, 240, 260, 290, 360, 410, 400, 360, 320, 290,
     270, 260, 280, 320, 390, 450, 480, 440, 390, 350, 320, 300],
    # Pazdziernik - slaby efekt PV
    [340, 310, 290, 280, 300, 340, 410, 470, 480, 460, 430, 410,
     400, 390, 400, 430, 480, 540, 560, 520, 460, 410, 380, 350],
    # Listopad - minimalny efekt PV
    [370, 340, 320, 310, 330, 370, 440, 510, 540, 520, 490, 470,
     460, 450, 460, 480, 520, 570, 590, 550, 490, 440, 410, 380],
    # Grudzien - brak efektu PV, wysokie ceny
    [390, 360, 340, 330, 350, 390, 460, 530, 560, 540, 510, 490,
     480, 470, 480, 500, 540, 590, 610, 570, 510, 460, 430, 400],
]


def pobierz_cene_rce(miesiac: int, godzina: int) -> float:
    """
    Zwraca srednia cene RCE dla danego miesiaca i godziny.

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Cena w PLN/kWh (brutto z VAT 23%)
    """
    cena_mwh = CENY_RCE_GODZINOWE_PLN_MWH[miesiac - 1][godzina]
    # Przeliczenie PLN/MWh na PLN/kWh + VAT 23%
    cena_kwh_netto = cena_mwh / 1000.0
    cena_kwh_brutto = cena_kwh_netto * 1.23
    return round(cena_kwh_brutto, 4)


def pobierz_ceny_rce_miesiac(miesiac: int) -> List[float]:
    """
    Zwraca 24 ceny RCE (jedna na godzine) dla danego miesiaca.

    Parametry:
        miesiac: numer miesiaca (1-12)

    Zwraca:
        Lista 24 cen w PLN/kWh (brutto)
    """
    return [pobierz_cene_rce(miesiac, g) for g in range(24)]


def pobierz_srednia_rce_miesiac(miesiac: int) -> float:
    """
    Zwraca srednia cene RCE dla calego miesiaca (srednia z 24h).

    Parametry:
        miesiac: numer miesiaca (1-12)

    Zwraca:
        Srednia cena w PLN/kWh (brutto)
    """
    ceny = pobierz_ceny_rce_miesiac(miesiac)
    return round(sum(ceny) / len(ceny), 4)


def pobierz_cene_rce_sprzedaz(miesiac: int, godzina: int) -> float:
    """
    Zwraca cene sprzedazy nadwyzki energii z PV po cenie RCE.

    Sprzedaz odbywa sie po cenie gieldowej RCE z danej godziny.
    To jest cena ktora prosumer otrzymuje za energie oddana do sieci.

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Cena sprzedazy w PLN/kWh (netto - bez VAT, bo prosumer sprzedaje)
    """
    cena_mwh = CENY_RCE_GODZINOWE_PLN_MWH[miesiac - 1][godzina]
    # Prosumer sprzedaje po cenie netto (bez VAT)
    cena_kwh_netto = cena_mwh / 1000.0
    return round(cena_kwh_netto, 4)


def pobierz_statystyki_rce() -> Dict:
    """
    Zwraca statystyki cen RCE - srednie, min, max dla kazdego miesiaca.

    Przydatne do prezentacji uzytkownikowi oczekiwanych cen.

    Zwraca:
        Slownik ze statystykami cen RCE
    """
    statystyki = []

    for miesiac in range(1, 13):
        ceny = pobierz_ceny_rce_miesiac(miesiac)
        ceny_sprzedaz = [pobierz_cene_rce_sprzedaz(miesiac, g) for g in range(24)]

        statystyki.append({
            "miesiac": miesiac,
            "srednia_kupno_zl_kwh": round(sum(ceny) / len(ceny), 4),
            "min_kupno_zl_kwh": round(min(ceny), 4),
            "max_kupno_zl_kwh": round(max(ceny), 4),
            "srednia_sprzedaz_zl_kwh": round(sum(ceny_sprzedaz) / len(ceny_sprzedaz), 4),
            "min_sprzedaz_zl_kwh": round(min(ceny_sprzedaz), 4),
            "max_sprzedaz_zl_kwh": round(max(ceny_sprzedaz), 4),
            "godzina_najtanszej": ceny.index(min(ceny)),
            "godzina_najdrozszej": ceny.index(max(ceny)),
        })

    return {"miesiace": statystyki}
