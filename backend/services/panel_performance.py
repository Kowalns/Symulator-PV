"""
Serwis obliczania wydajnosci paneli PV.

Uwzglednia:
1. Wplyw temperatury (wspolczynnik temperaturowy mocy z danych panela)
2. Wplyw zacienienia z bypass diodami i technologia half-cut
3. Nasycenie promieniowaniem (irradiance) - model POA z danymi TMY lub fallback
4. Degradacja roczna paneli (typowo 0.5%)
5. Straty kablowe i na falowniku (2-5%)

Model POA (Plane of Array) z danymi TMY:
POA_beam = DNI * cos(AOI)
POA_diffuse = DHI * (1 + cos(tilt)) / 2  (model izotropowy)
POA_ground = GHI * albedo * (1 - cos(tilt)) / 2  (odbicia od gruntu)
POA_total = POA_beam + POA_diffuse + POA_ground

Model NOCT temperatury:
T_cell = T_amb_TMY + (NOCT - 20) * G_POA / 800

Fallback (bez danych TMY):
Stary model ze stalymi miesiecznymi szczytami i srednimi temperaturami.

Formula wydajnosci:
P_actual = P_stc * (G/1000) * (1 + coeff_temp * (T_panel - 25)) * shading_factor * (1 - system_losses)

Gdzie:
- P_stc: moc w warunkach STC [W]
- G: napromieniowanie [W/m2]
- coeff_temp: wspolczynnik temp. mocy [%/C] (np. -0.35)
- T_panel: temperatura panela [C]
- shading_factor: wspolczynnik redukcji od zacienienia (0-1)
- system_losses: straty systemowe (0.02-0.05)
"""

import math
from typing import List, Dict, Optional
from dataclasses import dataclass, field

from backend.services.shading import WynikZacienieniaPanel


# Srednie miesieczne temperatury otoczenia w Polsce [C] - FALLBACK
# Indeks 0 = styczen, indeks 11 = grudzien
TEMPERATURA_OTOCZENIA_POLSKA = [-3.0, -1.0, 3.0, 9.0, 14.0, 17.0,
                                 20.0, 19.0, 14.0, 9.0, 4.0, -1.0]

# Korekta NOCT - roznica miedzy temperatura panela a otoczenia [C]
# Panel w sloncu nagrzewa sie o ok. 25-30C powyzej otoczenia
DELTA_T_NOCT = 28.0

# Domyslna wartosc NOCT [C] dla nowoczesnych paneli
NOCT_DOMYSLNY = 45.0

# Domyslne straty systemowe (kable + falownik)
STRATY_SYSTEMOWE_DOMYSLNE = 0.03  # 3%


def oblicz_sprawnosc_falownika(moc_aktualna_w: float, moc_nominalna_falownika_w: float) -> float:
    """
    Oblicza sprawnosc falownika na podstawie aktualnego obciazenia.

    Model sprawnosci zalezy od procentu obciazenia:
    - Ponizej 2% mocy nominalnej: eta = 0 (falownik wylaczony, ponizej progu startu)
    - 2-10% obciazenia: eta rośnie liniowo od 0.85 do 0.95
    - 10-20%: eta rośnie liniowo od 0.95 do 0.97
    - 20-100%: plateau 0.96-0.975 z peakiem przy 50% (model kwadratowy)

    Parametry:
        moc_aktualna_w: aktualna moc wejsciowa DC [W]
        moc_nominalna_falownika_w: moc nominalna falownika [W]

    Zwraca:
        Sprawnosc falownika (0.0 - 1.0)
    """
    if moc_nominalna_falownika_w <= 0:
        return 0.0

    if moc_aktualna_w <= 0:
        return 0.0

    obciazenie = moc_aktualna_w / moc_nominalna_falownika_w

    if obciazenie < 0.02:
        # Ponizej progu startu - falownik wylaczony
        return 0.0
    elif obciazenie <= 0.10:
        # 2-10%: liniowy wzrost od 0.85 do 0.95
        t = (obciazenie - 0.02) / (0.10 - 0.02)
        return 0.85 + t * (0.95 - 0.85)
    elif obciazenie <= 0.20:
        # 10-20%: liniowy wzrost od 0.95 do 0.97
        t = (obciazenie - 0.10) / (0.20 - 0.10)
        return 0.95 + t * (0.97 - 0.95)
    else:
        # 20-100%: plateau z peakiem przy 50%
        # Model kwadratowy: eta = 0.975 - k * (obciazenie - 0.5)^2
        # Przy 50%: eta = 0.975 (peak)
        # Przy 20%: eta = 0.97 (ciaglosc z zakresem 10-20%)
        # 0.97 = 0.975 - k * (0.2 - 0.5)^2 -> k = 0.005 / 0.09 = 0.0556
        k = 0.005 / (0.3 ** 2)
        # Ograniczenie obciazenia do 1.0 (przy przeciazeniu)
        obc = min(obciazenie, 1.0)
        eta = 0.975 - k * (obc - 0.5) ** 2
        return max(0.96, min(0.975, eta))

# Uproszczony model napromieniowania dla Polski [W/m2] - FALLBACK
# Wartosci szczytowe w poludnie, niskie rano/wieczorem
# Indeks 0=styczen, 11=grudzien - szczytowe napromieniowanie w poludnie
NAPROMIENIOWANIE_SZCZYTOWE_POLSKA = [200, 300, 450, 600, 750, 850,
                                      900, 800, 600, 400, 250, 150]

# Albedo (wspolczynnik odbicia gruntu) - trawa
ALBEDO_DOMYSLNE = 0.2


def oblicz_zysk_bifacjalny(ghi: float, albedo: float,
                           bifacial_wspolczynnik: float,
                           wysokosc_nad_gruntem_m: float = 0.5) -> float:
    """
    Oblicza dodatkowa irradiancje z tylnej strony panela bifacjalnego.

    Zysk bifacjalny = GHI * albedo * bifacial_wspolczynnik * wspolczynnik_wysokosci

    Wspolczynnik wysokosci - interpolacja liniowa:
    - 0.5m -> 0.6
    - 1.0m -> 0.8
    - 1.5m -> 0.95
    - powyzej 1.5m -> 0.95 (cap)

    Parametry:
        ghi: Global Horizontal Irradiance [W/m2]
        albedo: wspolczynnik odbicia gruntu (0.2=trawa, 0.6=snieg)
        bifacial_wspolczynnik: wydajnosc tylnej strony panela (0.0-1.0, typowo 0.70)
        wysokosc_nad_gruntem_m: przeswit panela nad gruntem [m]

    Zwraca:
        Dodatkowa irradiancja w [W/m2] z tylnej strony panela
    """
    if ghi <= 0 or albedo <= 0 or bifacial_wspolczynnik <= 0:
        return 0.0

    # Interpolacja wspolczynnika wysokosci
    # Punkty referencyjne: (0.5, 0.6), (1.0, 0.8), (1.5, 0.95)
    if wysokosc_nad_gruntem_m <= 0.5:
        wspolczynnik_wysokosci = 0.6
    elif wysokosc_nad_gruntem_m <= 1.0:
        # Interpolacja liniowa 0.5m->0.6, 1.0m->0.8
        t = (wysokosc_nad_gruntem_m - 0.5) / (1.0 - 0.5)
        wspolczynnik_wysokosci = 0.6 + t * (0.8 - 0.6)
    elif wysokosc_nad_gruntem_m <= 1.5:
        # Interpolacja liniowa 1.0m->0.8, 1.5m->0.95
        t = (wysokosc_nad_gruntem_m - 1.0) / (1.5 - 1.0)
        wspolczynnik_wysokosci = 0.8 + t * (0.95 - 0.8)
    else:
        # Powyzej 1.5m - cap na 0.95
        wspolczynnik_wysokosci = 0.95

    zysk = ghi * albedo * bifacial_wspolczynnik * wspolczynnik_wysokosci
    return zysk


@dataclass
class WynikWydajnosciPanel:
    """
    Wynik obliczen wydajnosci pojedynczego panela w danej godzinie.

    Atrybuty:
        panel_index: numer panela
        moc_nominalna_w: moc nominalna w STC [W]
        moc_aktualna_w: moc po uwzglednieniu wszystkich strat [W]
        napromieniowanie_wm2: nasycenie promieniowaniem [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wsp_temperaturowy: mnoznik temperaturowy (< 1 w upale, > 1 w zimie)
        wsp_zacienienia: mnoznik zacienienia (0 do 1)
        wsp_strat_systemowych: mnoznik strat (0.95-0.98 typowo)
        wsp_degradacji: mnoznik degradacji (0.995 po 1 roku)
        energia_wh: energia wyprodukowana w tej godzinie [Wh]
    """
    panel_index: int = 0
    moc_nominalna_w: float = 0.0
    moc_aktualna_w: float = 0.0
    napromieniowanie_wm2: float = 0.0
    temperatura_panela_c: float = 25.0
    wsp_temperaturowy: float = 1.0
    wsp_zacienienia: float = 1.0
    wsp_strat_systemowych: float = 0.97
    wsp_degradacji: float = 1.0
    energia_wh: float = 0.0


def oblicz_temperature_panela(miesiac: int, godzina: int) -> float:
    """
    Oblicza temperature panela na podstawie miesiaca i godziny.

    Temperatura panela = T_otoczenia + NOCT_korekta * (G/800)
    W nocy panel ma temperature otoczenia.
    W ciagu dnia nagrzewa sie proporcjonalnie do napromieniowania.

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)

    Zwraca:
        Temperatura panela w [C]
    """
    t_otoczenia = TEMPERATURA_OTOCZENIA_POLSKA[miesiac - 1]

    # Prosta modulacja temperatury w ciagu dnia
    # Godziny sloneczne: 6-20 (przyblizone)
    if godzina < 6 or godzina > 20:
        return t_otoczenia

    # Wspolczynnik dnia (0 rano/wieczorem, 1 w poludnie)
    if godzina <= 13:
        wsp_dnia = (godzina - 6) / 7.0
    else:
        wsp_dnia = (20 - godzina) / 7.0
    wsp_dnia = max(0.0, min(1.0, wsp_dnia))

    # Temperatura panela z korrekta NOCT
    t_panel = t_otoczenia + DELTA_T_NOCT * wsp_dnia

    return t_panel


def oblicz_napromieniowanie(miesiac: int, godzina: int, elewacja_slonca: float,
                            kat_nachylenia: float = 0.0, azymut_panela: float = 0.0,
                            azymut_slonca: float = 180.0) -> float:
    """
    Oblicza napromieniowanie (irradiance) na plaszczyznie panela (POA - Plane of Array).

    Korekta kata padania (POA):
    cos(theta) = sin(elewacja)*cos(beta) + cos(elewacja)*sin(beta)*cos(azymut_slonca - azymut_panela)
    G_POA = G_beam * cos(theta) / sin(elewacja)

    Gdzie:
    - theta: kat padania promieniowania na nachylony panel
    - beta: kat nachylenia panela (0=poziomo, 90=pionowo)
    - elewacja: elewacja slonca (kat nad horyzontem)
    - azymut_slonca: azymut slonca (180=poludnie)
    - azymut_panela: azymut panela (0=poludnie w konwencji instalacji)

    Parametry:
        miesiac: numer miesiaca (1-12)
        godzina: godzina dnia (0-23)
        elewacja_slonca: elewacja Slonca [stopnie]
        kat_nachylenia: kat nachylenia panela [stopnie] (0=poziomy)
        azymut_panela: azymut panela [stopnie] (0=poludnie, ujemne=wschod, dodatnie=zachod)
        azymut_slonca: azymut Slonca [stopnie] (180=poludnie w konwencji astronomicznej)

    Zwraca:
        Napromieniowanie na plaszczyznie panela (POA) w [W/m2]
    """
    if elewacja_slonca <= 0:
        return 0.0

    # Szczytowa irradiancja dla danego miesiaca (na plaszczyzne pozioma)
    szczytowe = NAPROMIENIOWANIE_SZCZYTOWE_POLSKA[miesiac - 1]

    # Irradiancja na plaszczyzne pozioma (GHI) proporcjonalna do sin(elewacja)
    sin_elewacja = math.sin(math.radians(elewacja_slonca))

    # GHI = G_beam * sin(elewacja) - napromieniowanie na plaszczyzne pozioma
    ghi = szczytowe * sin_elewacja

    # Korekta POA - przeliczenie na nachylony panel
    # cos(theta) = sin(elewacja)*cos(beta) + cos(elewacja)*sin(beta)*cos(azymut_slonca - azymut_panela)
    beta_rad = math.radians(kat_nachylenia)
    elev_rad = math.radians(elewacja_slonca)

    # Konwersja azymutow do wspolnej konwencji
    # azymut_slonca: konwencja astronomiczna (180=poludnie)
    # azymut_panela: konwencja instalacji (0=poludnie)
    # Roznica: az_slonca - (az_panela + 180) = az_slonca - az_panela - 180
    roznica_azymut = math.radians(azymut_slonca - (azymut_panela + 180.0))

    cos_theta = (math.sin(elev_rad) * math.cos(beta_rad) +
                 math.cos(elev_rad) * math.sin(beta_rad) * math.cos(roznica_azymut))

    # Jesli cos(theta) <= 0, panel jest odwrocony od slonca
    if cos_theta <= 0:
        return 0.0

    # G_POA = GHI * cos(theta) / sin(elewacja)
    # GHI = szczytowe * sin(elewacja), wiec:
    # G_POA = szczytowe * sin(elewacja) * cos(theta) / sin(elewacja) = szczytowe * cos(theta)
    # Ale to uproszczenie - uzywamy pelnej formuly z G_beam:
    # G_beam = GHI / sin(elewacja) = szczytowe
    # G_POA = G_beam * cos(theta) = szczytowe * cos(theta)
    # Ale tak naprawde GHI juz uwzglednia air mass, wiec:
    irradiancja_poa = ghi * cos_theta / sin_elewacja

    # Ograniczenie do maksimum 1000 W/m2 (warunki STC)
    return min(1000.0, max(0.0, irradiancja_poa))


def oblicz_poa_tmy(ghi: float, dni: float, dhi: float,
                   elewacja_slonca: float, azymut_slonca: float,
                   kat_nachylenia: float = 30.0, azymut_panela: float = 0.0,
                   albedo: float = ALBEDO_DOMYSLNE) -> Dict[str, float]:
    """
    Oblicza napromieniowanie POA (Plane of Array) z danych TMY.

    Rozdziela irradiancje na trzy skladniki:
    - POA_beam: promieniowanie bezposrednie (DNI * cos(AOI))
    - POA_diffuse: promieniowanie rozproszone (model izotropowy)
    - POA_ground: odbicia od gruntu (GHI * albedo)

    Parametry:
        ghi: Global Horizontal Irradiance [W/m2]
        dni: Direct Normal Irradiance [W/m2]
        dhi: Diffuse Horizontal Irradiance [W/m2]
        elewacja_slonca: elewacja Slonca [stopnie]
        azymut_slonca: azymut Slonca [stopnie] (180=poludnie)
        kat_nachylenia: kat nachylenia panela [stopnie] (0=poziomy)
        azymut_panela: azymut panela [stopnie] (0=poludnie)
        albedo: wspolczynnik odbicia gruntu (0.2 = trawa)

    Zwraca:
        Slownik z kluczami: 'beam', 'diffuse', 'ground', 'total'
    """
    if elewacja_slonca <= 0 or (ghi <= 0 and dni <= 0 and dhi <= 0):
        return {"beam": 0.0, "diffuse": 0.0, "ground": 0.0, "total": 0.0}

    beta_rad = math.radians(kat_nachylenia)
    elev_rad = math.radians(elewacja_slonca)

    # Obliczenie katu padania (AOI - Angle of Incidence)
    # cos(AOI) = sin(elewacja)*cos(beta) + cos(elewacja)*sin(beta)*cos(az_slonca - az_panela - 180)
    roznica_azymut = math.radians(azymut_slonca - (azymut_panela + 180.0))
    cos_aoi = (math.sin(elev_rad) * math.cos(beta_rad) +
               math.cos(elev_rad) * math.sin(beta_rad) * math.cos(roznica_azymut))

    # POA beam - promieniowanie bezposrednie na nachylona plaszyczne
    poa_beam = dni * max(0.0, cos_aoi) if dni > 0 else 0.0

    # POA diffuse - model izotropowy (panel "widzi" czesc nieba)
    poa_diffuse = dhi * (1.0 + math.cos(beta_rad)) / 2.0 if dhi > 0 else 0.0

    # POA ground - odbicia od gruntu
    poa_ground = ghi * albedo * (1.0 - math.cos(beta_rad)) / 2.0 if ghi > 0 else 0.0

    poa_total = poa_beam + poa_diffuse + poa_ground

    # Fizyczny limit POA - zabezpieczenie na wypadek blednych danych TMY.
    # Na powierzchni Ziemi irradiancja na nachylona plaszczyznie nie powinna
    # przekraczac ~1400 W/m2 (limit atmosferyczny).
    POA_CAP = 1400.0
    if poa_total > POA_CAP:
        # Skaluj proporcjonalnie wszystkie skladniki
        skala = POA_CAP / poa_total
        poa_beam *= skala
        poa_diffuse *= skala
        poa_ground *= skala
        poa_total = POA_CAP

    return {
        "beam": round(poa_beam, 2),
        "diffuse": round(poa_diffuse, 2),
        "ground": round(poa_ground, 2),
        "total": round(poa_total, 2),
    }


def oblicz_temperature_panela_tmy(t_ambient: float, g_poa: float,
                                   noct: float = NOCT_DOMYSLNY) -> float:
    """
    Oblicza temperature panela na podstawie danych TMY i modelu NOCT.

    Model: T_cell = T_ambient + (NOCT - 20) * G_POA / 800

    Parametry:
        t_ambient: temperatura otoczenia z TMY [C]
        g_poa: napromieniowanie na plaszczyznie panela [W/m2]
        noct: Nominal Operating Cell Temperature [C] (domyslnie 45)

    Zwraca:
        Temperatura panela [C]
    """
    if g_poa <= 0:
        return t_ambient

    t_cell = t_ambient + (noct - 20.0) * g_poa / 800.0
    return t_cell


def oblicz_wspolczynnik_zacienienia(zacienienie: WynikZacienieniaPanel,
                                     liczba_sekcji: int = 3,
                                     technologia: str = "standard") -> float:
    """
    Oblicza wspolczynnik redukcji mocy z powodu zacienienia.

    Reguly:
    1. Bypass diody: jesli sekcja zacieniona >15%, bypass aktywuje sie,
       sekcja daje 0 mocy (strata ~1/liczba_sekcji mocy panela).
       (Prog 15% odpowiada rzeczywistemu zachowaniu - wystarczy zacienienie
       kilku cel w sekcji aby prad spadl ponizej progu aktywacji bypass.)
    2. Half-cut: panel ma 2 niezalezne polowy. Jesli zacieniona jest
       tylko jedna polowa, druga produkuje normalnie (50% mocy).
    3. Bez half-cut i bypass: strata proporcjonalna do zacienienia.

    Parametry:
        zacienienie: wynik analizy zacienienia panela
        liczba_sekcji: liczba sekcji bypass (typowo 3)
        technologia: "half-cut" lub "standard"

    Zwraca:
        Wspolczynnik mocy 0.0 (caly panel wyciemniony) do 1.0 (bez strat)
    """
    if zacienienie.stopien_zacienienia <= 0:
        return 1.0

    if zacienienie.stopien_zacienienia >= 1.0:
        return 0.0

    # Jesli mamy informacje o bypass diodach
    if zacienienie.sekcje_zacienione:
        if technologia == "half-cut":
            # Half-cut: 2 niezalezne polowy
            # Jesli tylko jedna polowa zacieniona, druga daje pelna moc
            if zacienienie.polowa_gorna_zacieniona and not zacienienie.polowa_dolna_zacieniona:
                # Dolna polowa produkuje normalnie
                return 0.5
            elif zacienienie.polowa_dolna_zacieniona and not zacienienie.polowa_gorna_zacieniona:
                # Gorna polowa produkuje normalnie
                return 0.5
            elif zacienienie.polowa_gorna_zacieniona and zacienienie.polowa_dolna_zacieniona:
                # Obie polowy zacienione - strata proporcjonalna do bypass
                bypass = zacienienie.bypass_aktywne
                return max(0.0, 1.0 - bypass / liczba_sekcji)
            else:
                # Zadna polowa nie zacieniona wystarczajaco (>50%)
                # Ale poszczegolne sekcje moga byc aktywne
                bypass = zacienienie.bypass_aktywne
                if bypass > 0:
                    # Half-cut zmniejsza wplyw: kazdy bypass to strata polowy sekcji
                    # bo w half-cut sekcja jest podzielona na 2 polowki
                    return max(0.0, 1.0 - bypass / (liczba_sekcji * 2.0))
                else:
                    # Drobne zacienienie bez aktywacji bypass
                    return 1.0 - zacienienie.stopien_zacienienia * 0.3
        else:
            # Standard (bez half-cut): bypass diody standardowo
            bypass = zacienienie.bypass_aktywne
            if bypass > 0:
                # Kazda aktywna bypass to strata 1/N mocy
                return max(0.0, 1.0 - bypass / liczba_sekcji)
            else:
                # Drobne zacienienie bez aktywacji bypass - strata proporcjonalna
                return 1.0 - zacienienie.stopien_zacienienia * 0.5

    # Fallback: proporcjonalna strata
    return 1.0 - zacienienie.stopien_zacienienia


def oblicz_wydajnosc_panela(moc_stc_w: float,
                            napromieniowanie_wm2: float,
                            temperatura_panela_c: float,
                            wspolczynnik_temp_pmax: float,
                            wspolczynnik_zacienienia: float,
                            straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
                            degradacja_roczna: float = 0.005,
                            rok_eksploatacji: int = 1,
                            moc_nominalna_falownika_w: Optional[float] = None) -> WynikWydajnosciPanel:
    """
    Oblicza aktualna moc panela z uwzglednieniem wszystkich strat.

    Formula: P = P_stc * (G/1000) * wsp_temp * wsp_zacien * (1-straty) * wsp_degrad

    Jesli podano moc_nominalna_falownika_w, zamiast stalych strat systemowych
    (1-straty_systemowe) uzywa krzywej sprawnosci falownika.

    Parametry:
        moc_stc_w: moc nominalna w warunkach STC [W]
        napromieniowanie_wm2: napromieniowanie [W/m2]
        temperatura_panela_c: temperatura panela [C]
        wspolczynnik_temp_pmax: wspolczynnik temperaturowy [%/C] (np. -0.35)
        wspolczynnik_zacienienia: wspolczynnik redukcji od cienia (0-1)
        straty_systemowe: straty na kablach i falowniku (0.02-0.05)
        degradacja_roczna: roczna degradacja mocy (0.005 = 0.5%)
        rok_eksploatacji: ktory rok eksploatacji (1 = pierwszy)
        moc_nominalna_falownika_w: moc nominalna falownika [W] (opcjonalnie).
            Gdy podane i >0, uzywana jest krzywa sprawnosci falownika
            zamiast stalego wspolczynnika (1-straty_systemowe).

    Zwraca:
        WynikWydajnosciPanel z obliczona moca i energia
    """
    # Brak produkcji bez napromieniowania
    if napromieniowanie_wm2 <= 0:
        return WynikWydajnosciPanel(
            moc_nominalna_w=moc_stc_w,
            moc_aktualna_w=0.0,
            napromieniowanie_wm2=0.0,
            temperatura_panela_c=temperatura_panela_c,
            wsp_temperaturowy=1.0,
            wsp_zacienienia=wspolczynnik_zacienienia,
            wsp_strat_systemowych=1.0 - straty_systemowe,
            energia_wh=0.0,
        )

    # 1. Wspolczynnik napromieniowania (STC = 1000 W/m2)
    wsp_irradiancja = napromieniowanie_wm2 / 1000.0

    # 2. Wspolczynnik temperaturowy
    # wspolczynnik_temp_pmax jest podawany jako %/C (np. -0.35)
    # Delta T = T_panel - 25C (temperatura STC)
    delta_t = temperatura_panela_c - 25.0
    wsp_temp = 1.0 + (wspolczynnik_temp_pmax / 100.0) * delta_t

    # Ograniczenie do sensownych wartosci
    wsp_temp = max(0.5, min(1.2, wsp_temp))

    # 3. Wspolczynnik degradacji
    wsp_degradacji = (1.0 - degradacja_roczna) ** (rok_eksploatacji - 1)

    # 4. Wspolczynnik strat systemowych lub sprawnosc falownika
    if moc_nominalna_falownika_w is not None and moc_nominalna_falownika_w > 0:
        # Oblicz moc DC przed falownikiem (bez strat falownika)
        moc_dc = moc_stc_w * wsp_irradiancja * wsp_temp * wspolczynnik_zacienienia * wsp_degradacji
        # Sprawnosc falownika na podstawie aktualnego obciazenia
        sprawnosc = oblicz_sprawnosc_falownika(moc_dc, moc_nominalna_falownika_w)
        wsp_strat = sprawnosc
    else:
        wsp_strat = 1.0 - straty_systemowe

    # Obliczenie mocy aktualnej
    moc_aktualna = (moc_stc_w * wsp_irradiancja * wsp_temp *
                    wspolczynnik_zacienienia * wsp_strat * wsp_degradacji)

    # Moc nie moze byc ujemna
    moc_aktualna = max(0.0, moc_aktualna)

    # Energia w Wh (moc * 1 godzina)
    energia_wh = moc_aktualna

    return WynikWydajnosciPanel(
        moc_nominalna_w=moc_stc_w,
        moc_aktualna_w=round(moc_aktualna, 2),
        napromieniowanie_wm2=napromieniowanie_wm2,
        temperatura_panela_c=temperatura_panela_c,
        wsp_temperaturowy=round(wsp_temp, 4),
        wsp_zacienienia=wspolczynnik_zacienienia,
        wsp_strat_systemowych=round(wsp_strat, 4),
        wsp_degradacji=round(wsp_degradacji, 6),
        energia_wh=round(energia_wh, 2),
    )


def oblicz_roczna_produkcje_panela(moc_stc_w: float,
                                    wspolczynnik_temp_pmax: float,
                                    technologia: str,
                                    liczba_sekcji: int,
                                    zacienienia_godzinowe: list,
                                    panel_index: int = 0,
                                    szerokosc_geo: float = 52.23,
                                    straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
                                    degradacja_roczna: float = 0.005,
                                    rok_eksploatacji: int = 1,
                                    kat_nachylenia: float = 30.0,
                                    azymut_panela: float = 0.0,
                                    dane_tmy: Optional[Dict] = None,
                                    noct: float = NOCT_DOMYSLNY,
                                    bifacial: bool = False,
                                    bifacial_wspolczynnik: float = 0.0,
                                    przeswit_nad_gruntem_m: float = 0.5,
                                    albedo: float = ALBEDO_DOMYSLNE) -> Dict:
    """
    Oblicza roczna produkcje energii pojedynczego panela.

    Jesli dane_tmy jest podane, uzywa modelu POA z danymi TMY
    (beam/diffuse/ground rozdzielone, cien blokuje tylko beam).
    Jesli dane_tmy jest None, uzywa starego modelu fallback.

    Parametry:
        moc_stc_w: moc nominalna w STC [W]
        wspolczynnik_temp_pmax: wspolczynnik temperaturowy [%/C]
        technologia: "half-cut" lub "standard"
        liczba_sekcji: liczba sekcji bypass
        zacienienia_godzinowe: lista wynikow zacienienia (po jednym na godzine)
        panel_index: indeks panela do analizy
        szerokosc_geo: szerokosc geograficzna (do profilu napromieniowania)
        straty_systemowe: straty systemowe
        degradacja_roczna: roczna degradacja
        rok_eksploatacji: rok eksploatacji
        kat_nachylenia: kat nachylenia panela [stopnie]
        azymut_panela: azymut panela [stopnie] (0=poludnie)
        dane_tmy: opcjonalne dane TMY z PVGIS (slownik z kluczami ghi, dni, dhi, temperatura)
        noct: Nominal Operating Cell Temperature [C]
        bifacial: czy panel jest bifacjalny (domyslnie False)
        bifacial_wspolczynnik: wydajnosc tylnej strony panela (0.0-1.0, typowo 0.70)
        przeswit_nad_gruntem_m: wysokosc dolnej krawedzi panela nad gruntem [m]
        albedo: wspolczynnik odbicia gruntu (0.2=trawa, 0.6=snieg)

    Zwraca:
        Slownik z wynikami rocznymi i miesiecznymi
    """
    # Jesli mamy dane TMY - uzywamy nowego modelu POA
    if dane_tmy is not None:
        return _oblicz_roczna_produkcje_tmy(
            moc_stc_w, wspolczynnik_temp_pmax, technologia, liczba_sekcji,
            zacienienia_godzinowe, panel_index, straty_systemowe,
            degradacja_roczna, rok_eksploatacji, kat_nachylenia,
            azymut_panela, dane_tmy, noct,
            bifacial=bifacial,
            bifacial_wspolczynnik=bifacial_wspolczynnik,
            przeswit_nad_gruntem_m=przeswit_nad_gruntem_m,
            albedo=albedo
        )

    # Fallback - stary model bez danych TMY
    return _oblicz_roczna_produkcje_fallback(
        moc_stc_w, wspolczynnik_temp_pmax, technologia, liczba_sekcji,
        zacienienia_godzinowe, panel_index, szerokosc_geo,
        straty_systemowe, degradacja_roczna, rok_eksploatacji,
        kat_nachylenia, azymut_panela
    )


def _oblicz_roczna_produkcje_tmy(moc_stc_w: float,
                                  wspolczynnik_temp_pmax: float,
                                  technologia: str,
                                  liczba_sekcji: int,
                                  zacienienia_godzinowe: list,
                                  panel_index: int,
                                  straty_systemowe: float,
                                  degradacja_roczna: float,
                                  rok_eksploatacji: int,
                                  kat_nachylenia: float,
                                  azymut_panela: float,
                                  dane_tmy: Dict,
                                  noct: float,
                                  bifacial: bool = False,
                                  bifacial_wspolczynnik: float = 0.0,
                                  przeswit_nad_gruntem_m: float = 0.5,
                                  albedo: float = ALBEDO_DOMYSLNE) -> Dict:
    """
    Oblicza roczna produkcje panela z wykorzystaniem danych TMY.

    Model POA: rozdziela irradiancje na beam/diffuse/ground.
    Cien blokuje TYLKO skladnik beam - diffuse dociera niezaleznie.
    Temperatura z modelu NOCT i danych TMY.

    Dla paneli bifacjalnych dodaje zysk z tylnej strony:
    zysk_bifacjalny = GHI * albedo * bifacial_wspolczynnik * wspolczynnik_wysokosci
    """
    energia_miesieczna = [0.0] * 12
    energia_roczna = 0.0
    energia_bez_zacienienia = 0.0
    godziny_z_zacienieniem = 0

    # Listy danych TMY
    ghi_lista = dane_tmy["ghi"]
    dni_lista = dane_tmy["dni"]
    dhi_lista = dane_tmy["dhi"]
    temp_lista = dane_tmy["temperatura"]

    # Iteracja po godzinach roku (8760 godzin = indeks TMY)
    # TMY ma dokladnie 8760 godzin (rok niestepny: 365 dni)
    # zacienienia_godzinowe moze miec 8760 lub 8784 (rok przestepny)
    indeks_tmy = 0

    for godzina_dane in zacienienia_godzinowe:
        miesiac = godzina_dane.miesiac
        godzina = godzina_dane.godzina
        elewacja = godzina_dane.elewacja_slonca
        azymut_slonca = godzina_dane.azymut_slonca

        # Mapowanie indeksu TMY - TMY ma 8760 godzin (365 dni)
        # Jesli rok jest przestepny (8784 godzin), powtarzamy ostatni dzien
        tmy_idx = min(indeks_tmy, 8759)
        indeks_tmy += 1

        # Pobierz dane TMY dla tej godziny
        ghi = ghi_lista[tmy_idx]
        dni = dni_lista[tmy_idx]
        dhi = dhi_lista[tmy_idx]
        t_amb = temp_lista[tmy_idx]

        # Oblicz POA (Plane of Array)
        poa = oblicz_poa_tmy(
            ghi, dni, dhi, elewacja, azymut_slonca,
            kat_nachylenia, azymut_panela, albedo=albedo
        )

        poa_total = poa["total"]
        if poa_total <= 0:
            continue

        # Temperatura panela z modelu NOCT
        temp_panel = oblicz_temperature_panela_tmy(t_amb, poa_total, noct)

        # Znajdz dane zacienienia dla tego panela
        panel_zacienienie = None
        for pz in godzina_dane.panele:
            if pz.panel_index == panel_index:
                panel_zacienienie = pz
                break

        # Oblicz efektywna irradiancje z uwzglednieniem zacienienia
        # Cien blokuje TYLKO beam - diffuse i ground docieraja niezaleznie
        jest_zacieniony = False
        if panel_zacienienie is not None and panel_zacienienie.stopien_zacienienia > 0:
            jest_zacieniony = True
            godziny_z_zacienieniem += 1

            # Przy zacienieniu: beam jest blokowany proporcjonalnie do stopnia zacienienia
            # Diffuse i ground docieraja niezaleznie od cienia budynku
            stopien = panel_zacienienie.stopien_zacienienia

            # Efektywna irradiancja: beam zredukowany przez cien, diffuse pelen
            irradiancja_efektywna = (
                poa["beam"] * (1.0 - stopien) +
                poa["diffuse"] +
                poa["ground"]
            )

            # Wspolczynnik zacienienia bypass (efekt elektryczny na czesc niezacieniona)
            # Redukujemy tylko proporcjonalnie do czesci beam ktora przechodzi
            # Jesli beam jest calkowicie zablokowany, bypass nie ma znaczenia
            # (panel produkuje tylko z diffuse ktore jest rownomiernie rozlozone)
            if poa["beam"] > 0 and (1.0 - stopien) > 0:
                wsp_zacien_bypass = oblicz_wspolczynnik_zacienienia(
                    panel_zacienienie, liczba_sekcji, technologia
                )
                # Skaluj efekt bypass proporcjonalnie do udzialu beam w total
                udzial_beam = (poa["beam"] * (1.0 - stopien)) / irradiancja_efektywna if irradiancja_efektywna > 0 else 0
                # Bypass wplywa tylko na czesc beamowa, diffuse jest jednorodne
                wsp_zacien_bypass = 1.0 - udzial_beam * (1.0 - wsp_zacien_bypass)
            else:
                # Brak beam - diffuse jest jednorodne, bypass nie wplywa
                wsp_zacien_bypass = 1.0
        else:
            wsp_zacien_bypass = 1.0
            irradiancja_efektywna = poa_total

        if irradiancja_efektywna <= 0:
            continue

        # Dodaj zysk bifacjalny (tylna strona panela)
        if bifacial and bifacial_wspolczynnik > 0:
            zysk_bif = oblicz_zysk_bifacjalny(
                ghi, albedo, bifacial_wspolczynnik, przeswit_nad_gruntem_m
            )
            irradiancja_efektywna += zysk_bif

        # Przelicz temperature panela na efektywna irradiancje (po zacienieniu)
        if jest_zacieniony:
            temp_panel = oblicz_temperature_panela_tmy(t_amb, irradiancja_efektywna, noct)

        # Oblicz wydajnosc panela
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w, irradiancja_efektywna, temp_panel,
            wspolczynnik_temp_pmax, wsp_zacien_bypass,
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )

        energia_miesieczna[miesiac - 1] += wynik.energia_wh
        energia_roczna += wynik.energia_wh

        # Oblicz produkcje bez zacienienia (pelne POA)
        # Temperatura referencji obliczona z pelnym POA (bez zacienienia)
        temp_panel_bez = oblicz_temperature_panela_tmy(t_amb, poa_total, noct)
        wynik_bez = oblicz_wydajnosc_panela(
            moc_stc_w, poa_total, temp_panel_bez,
            wspolczynnik_temp_pmax, 1.0,
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )
        energia_bez_zacienienia += wynik_bez.energia_wh

    # Straty z powodu zacienienia
    strata_zacienienie = 0.0
    if energia_bez_zacienienia > 0:
        strata_zacienienie = 1.0 - (energia_roczna / energia_bez_zacienienia)

    return {
        "panel_index": panel_index,
        "energia_roczna_kwh": round(energia_roczna / 1000.0, 2),
        "energia_miesieczna_kwh": [round(e / 1000.0, 2) for e in energia_miesieczna],
        "energia_bez_zacienienia_kwh": round(energia_bez_zacienienia / 1000.0, 2),
        "strata_zacienienie_procent": round(strata_zacienienie * 100.0, 2),
        "godziny_z_zacienieniem": godziny_z_zacienieniem,
        "moc_stc_w": moc_stc_w,
        "technologia": technologia,
        "zrodlo_danych": "tmy",
    }


def oblicz_roczna_produkcje_instalacji(
        panele_wyniki_zacienienia: list,
        moc_stc: float,
        wsp_temp: float,
        technologia: str,
        liczba_sekcji: int,
        dane_tmy: Optional[Dict],
        kat_nachylenia: float,
        azymut_panela: float,
        straty_systemowe: float = STRATY_SYSTEMOWE_DOMYSLNE,
        degradacja: float = 0.005,
        rok_eksploatacji: int = 1,
        stringi: Optional[list] = None,
        z_optymalizatorami: bool = True,
        moc_nominalna_falownika_w: Optional[float] = None,
        noct: float = NOCT_DOMYSLNY,
        bifacial: bool = False,
        bifacial_wspolczynnik: float = 0.0,
        przeswit_nad_gruntem_m: float = 0.5,
        albedo: float = ALBEDO_DOMYSLNE) -> Dict:
    """
    Oblicza roczna produkcje calej instalacji z uwzglednieniem stringow i mismatch.

    Dla kazdej godziny TMY:
    - Z optymalizatorami: kazdy panel pracuje niezaleznie (suma wszystkich)
    - Bez optymalizatorow: panele pogrupowane w stringi, najgorzej zacieniony
      panel ogranicza caly string (mismatch loss via oblicz_mismatch_stringa)

    Parametry:
        panele_wyniki_zacienienia: lista wynikow zacienienia godzinowego (caly rok)
        moc_stc: moc nominalna jednego panela [W]
        wsp_temp: wspolczynnik temperaturowy mocy [%/C]
        technologia: "half-cut" lub "standard"
        liczba_sekcji: liczba sekcji bypass
        dane_tmy: dane TMY z PVGIS (slownik z kluczami ghi, dni, dhi, temperatura)
        kat_nachylenia: kat nachylenia panela [stopnie]
        azymut_panela: azymut panela [stopnie] (0=poludnie)
        straty_systemowe: straty systemowe
        degradacja: roczna degradacja
        rok_eksploatacji: rok eksploatacji
        stringi: lista KonfiguracjaStringa (z optimizer.py) - podzial paneli na stringi
        z_optymalizatorami: czy uzywac optymalizatorow (True=niezalezne MPPT per panel)
        moc_nominalna_falownika_w: moc nominalna falownika [W] (opcjonalnie)
        noct: Nominal Operating Cell Temperature [C]
        bifacial: czy panel jest bifacjalny
        bifacial_wspolczynnik: wydajnosc tylnej strony panela (0.0-1.0)
        przeswit_nad_gruntem_m: wysokosc dolnej krawedzi panela nad gruntem [m]
        albedo: wspolczynnik odbicia gruntu

    Zwraca:
        Slownik z wynikami: roczna_kwh, miesieczna_kwh[12], stringi_info, per-panel
    """
    from backend.services.optimizer import oblicz_mismatch_stringa as _oblicz_mismatch

    # Zbierz wszystkie indeksy paneli
    wszystkie_indeksy = set()
    if stringi:
        for s in stringi:
            for idx in s.indeksy_paneli:
                wszystkie_indeksy.add(idx)
    else:
        # Jesli brak stringow, zbierz indeksy z danych zacienienia
        if panele_wyniki_zacienienia:
            for pz in panele_wyniki_zacienienia[0].panele:
                wszystkie_indeksy.add(pz.panel_index)

    if not wszystkie_indeksy:
        return {
            "roczna_kwh": 0.0,
            "miesieczna_kwh": [0.0] * 12,
            "stringi_info": [],
            "panele": [],
            "z_optymalizatorami": z_optymalizatorami,
        }

    liczba_paneli = len(wszystkie_indeksy)

    # Jesli nie podano stringow, utworz jeden string ze wszystkimi panelami
    if stringi is None or len(stringi) == 0:
        from backend.services.optimizer import KonfiguracjaStringa
        stringi = [KonfiguracjaStringa(
            indeksy_paneli=sorted(list(wszystkie_indeksy)),
            nazwa="String 1"
        )]

    # Przygotuj struktury wynikowe
    energia_miesieczna = [0.0] * 12
    energia_roczna = 0.0
    energia_bez_zacienienia = 0.0
    energia_per_string = {i: 0.0 for i in range(len(stringi))}

    # Dane TMY
    if dane_tmy is None:
        # Fallback - bez TMY obliczamy per-panel niezaleznie (stary model)
        # W tym przypadku stringi sa pomijane (brak dokladnych danych godzinowych)
        wyniki_paneli = []
        for panel_idx in sorted(wszystkie_indeksy):
            wynik = oblicz_roczna_produkcje_panela(
                moc_stc, wsp_temp, technologia, liczba_sekcji,
                panele_wyniki_zacienienia, panel_idx,
                52.23, straty_systemowe, degradacja, rok_eksploatacji,
                kat_nachylenia=kat_nachylenia,
                azymut_panela=azymut_panela,
                dane_tmy=None,
                noct=noct,
                bifacial=bifacial,
                bifacial_wspolczynnik=bifacial_wspolczynnik,
                przeswit_nad_gruntem_m=przeswit_nad_gruntem_m,
                albedo=albedo,
            )
            wyniki_paneli.append(wynik)

        roczna = sum(w["energia_roczna_kwh"] for w in wyniki_paneli)
        miesieczna = [0.0] * 12
        for w in wyniki_paneli:
            for i in range(12):
                miesieczna[i] += w["energia_miesieczna_kwh"][i]

        stringi_info = []
        for si, s in enumerate(stringi):
            stringi_info.append({
                "nazwa": s.nazwa,
                "indeksy_paneli": s.indeksy_paneli,
                "liczba_paneli": len(s.indeksy_paneli),
            })

        return {
            "roczna_kwh": round(roczna, 2),
            "miesieczna_kwh": [round(e, 2) for e in miesieczna],
            "stringi_info": stringi_info,
            "panele": wyniki_paneli,
            "z_optymalizatorami": z_optymalizatorami,
        }

    # Pelny model z TMY - godzina po godzinie z uwzglednieniem stringow
    ghi_lista = dane_tmy["ghi"]
    dni_lista = dane_tmy["dni"]
    dhi_lista = dane_tmy["dhi"]
    temp_lista = dane_tmy["temperatura"]

    # Degradacja
    wsp_degradacji = (1.0 - degradacja) ** (rok_eksploatacji - 1)

    indeks_tmy = 0
    produkcja_godzinowa_wh = []

    for godzina_dane in panele_wyniki_zacienienia:
        miesiac = godzina_dane.miesiac
        elewacja = godzina_dane.elewacja_slonca
        azymut_slonca = godzina_dane.azymut_slonca

        tmy_idx = min(indeks_tmy, 8759)
        indeks_tmy += 1

        ghi = ghi_lista[tmy_idx]
        dni = dni_lista[tmy_idx]
        dhi = dhi_lista[tmy_idx]
        t_amb = temp_lista[tmy_idx]

        # Oblicz POA
        poa = oblicz_poa_tmy(
            ghi, dni, dhi, elewacja, azymut_slonca,
            kat_nachylenia, azymut_panela, albedo=albedo
        )

        poa_total = poa["total"]
        if poa_total <= 0:
            produkcja_godzinowa_wh.append(0.0)
            continue

        # Temperatura panela
        temp_panel = oblicz_temperature_panela_tmy(t_amb, poa_total, noct)

        # Wspolczynnik temperaturowy
        delta_t = temp_panel - 25.0
        wsp_temp_val = 1.0 + (wsp_temp / 100.0) * delta_t
        wsp_temp_val = max(0.5, min(1.2, wsp_temp_val))

        # Wspolczynnik napromieniowania bazowy
        wsp_irr_base = poa_total / 1000.0

        # Zbierz wspolczynniki zacienienia per panel
        zacienienia_per_panel = {}
        for pz in godzina_dane.panele:
            if pz.panel_index in wszystkie_indeksy:
                wsp_z = oblicz_wspolczynnik_zacienienia(pz, liczba_sekcji, technologia)
                zacienienia_per_panel[pz.panel_index] = wsp_z

        # Dla paneli bez danych zacienienia - brak zacienienia
        for idx in wszystkie_indeksy:
            if idx not in zacienienia_per_panel:
                zacienienia_per_panel[idx] = 1.0

        # Oblicz produkcje w zaleznosci od trybu
        energia_godziny = 0.0

        if z_optymalizatorami:
            # Kazdy panel pracuje niezaleznie (wlasny MPPT przez optymalizator)
            # Ale falownik jest wspolny - sprawnosc zalezy od sumarycznej mocy DC
            # Krok 1: oblicz moc DC kazdego panela niezaleznie
            moc_dc_paneli = []
            for idx in sorted(wszystkie_indeksy):
                # Pobierz dane zacienienia dla tego panela
                panel_zacienienie = None
                for pz in godzina_dane.panele:
                    if pz.panel_index == idx:
                        panel_zacienienie = pz
                        break

                # Uzyj FIZYCZNEGO stopnia zacienienia (0-1) jako mnoznika beam
                # oraz osobno wsp_zacien (bypass factor) jako mnoznika mocy DC
                if panel_zacienienie is not None and panel_zacienienie.stopien_zacienienia > 0:
                    stopien_zacienienia = panel_zacienienie.stopien_zacienienia
                    wsp_zacien = zacienienia_per_panel[idx]  # bypass factor (elektryczny)
                else:
                    stopien_zacienienia = 0.0
                    wsp_zacien = 1.0

                # Efektywna irradiancja: beam zredukowany fizycznie przez cien,
                # diffuse i ground docieraja niezaleznie
                efektywna_irr = (
                    poa["beam"] * (1.0 - stopien_zacienienia) +
                    poa["diffuse"] +
                    poa["ground"]
                )

                # Dodaj zysk bifacjalny
                if bifacial and bifacial_wspolczynnik > 0:
                    zysk_bif = oblicz_zysk_bifacjalny(
                        ghi, albedo, bifacial_wspolczynnik, przeswit_nad_gruntem_m
                    )
                    efektywna_irr += zysk_bif

                if efektywna_irr <= 0:
                    moc_dc_paneli.append(0.0)
                    continue

                # Temperatura z efektywna irradiancja
                temp_p = oblicz_temperature_panela_tmy(t_amb, efektywna_irr, noct)
                delta_t_p = temp_p - 25.0
                wsp_temp_p = 1.0 + (wsp_temp / 100.0) * delta_t_p
                wsp_temp_p = max(0.5, min(1.2, wsp_temp_p))

                # Moc DC z uwzglednieniem bypass factor (efekt elektryczny)
                moc_dc = moc_stc * (efektywna_irr / 1000.0) * wsp_temp_p * wsp_degradacji * wsp_zacien
                moc_dc_paneli.append(max(0.0, moc_dc))

            # Krok 2: oblicz sprawnosc falownika na podstawie sumarycznej mocy DC
            suma_dc = sum(moc_dc_paneli)
            if suma_dc > 0:
                if moc_nominalna_falownika_w and moc_nominalna_falownika_w > 0:
                    eta = oblicz_sprawnosc_falownika(suma_dc, moc_nominalna_falownika_w)
                else:
                    eta = 1.0 - straty_systemowe

                energia_godziny = suma_dc * eta
                energia_godziny = max(0.0, energia_godziny)

                # Rozdziel energie proporcjonalnie na stringi (per-panel -> per-string)
                panele_sorted = sorted(wszystkie_indeksy)
                for si, s in enumerate(stringi):
                    moc_dc_stringa = sum(
                        moc_dc_paneli[panele_sorted.index(idx)]
                        for idx in s.indeksy_paneli
                        if idx in wszystkie_indeksy
                    )
                    if suma_dc > 0:
                        udzial = moc_dc_stringa / suma_dc
                        energia_per_string[si] += energia_godziny * udzial
        else:
            # Bez optymalizatorow - per string z mismatch
            # Krok 1: oblicz moc DC kazdego stringa
            moc_dc_stringow = {}
            for si, s in enumerate(stringi):
                if not s.indeksy_paneli:
                    continue

                # Wspolczynniki zacienienia paneli w stringu
                wsp_lista = [zacienienia_per_panel.get(idx, 1.0) for idx in s.indeksy_paneli]

                # Mismatch stringa
                wsp_mismatch = _oblicz_mismatch(wsp_lista, liczba_sekcji)

                # Efektywna irradiancja stringa (po mismatch) - uzywana do mocy
                efektywna_irr = poa_total * wsp_mismatch

                # Dodaj zysk bifacjalny
                if bifacial and bifacial_wspolczynnik > 0:
                    zysk_bif = oblicz_zysk_bifacjalny(
                        ghi, albedo, bifacial_wspolczynnik, przeswit_nad_gruntem_m
                    )
                    efektywna_irr += zysk_bif

                if efektywna_irr <= 0:
                    continue

                # Temperatura z PELNYM poa_total (nie z mismatch-zredukowanej irradiancji)
                # Mismatch wplywa na moc elektryczna, nie na temperature fizyczna panela
                irr_do_temp = poa_total
                if bifacial and bifacial_wspolczynnik > 0:
                    irr_do_temp += oblicz_zysk_bifacjalny(
                        ghi, albedo, bifacial_wspolczynnik, przeswit_nad_gruntem_m
                    )
                temp_p = oblicz_temperature_panela_tmy(t_amb, irr_do_temp, noct)
                delta_t_p = temp_p - 25.0
                wsp_temp_p = 1.0 + (wsp_temp / 100.0) * delta_t_p
                wsp_temp_p = max(0.5, min(1.2, wsp_temp_p))

                n_paneli = len(s.indeksy_paneli)
                # Caly string produkuje jak n_paneli * moc z mismatch
                moc_dc_string = moc_stc * n_paneli * (efektywna_irr / 1000.0) * wsp_temp_p * wsp_degradacji
                moc_dc_stringow[si] = max(0.0, moc_dc_string)

            # Krok 2: oblicz sprawnosc falownika na podstawie sumarycznej mocy DC wszystkich stringow
            suma_dc_stringow = sum(moc_dc_stringow.values())
            if suma_dc_stringow > 0:
                if moc_nominalna_falownika_w and moc_nominalna_falownika_w > 0:
                    eta = oblicz_sprawnosc_falownika(suma_dc_stringow, moc_nominalna_falownika_w)
                else:
                    eta = 1.0 - straty_systemowe

                energia_godziny = suma_dc_stringow * eta
                energia_godziny = max(0.0, energia_godziny)

                # Rozdziel energie proporcjonalnie na stringi
                for si, moc_dc_s in moc_dc_stringow.items():
                    udzial = moc_dc_s / suma_dc_stringow
                    energia_per_string[si] += energia_godziny * udzial

        # Oblicz produkcje bez zacienienia (referencja)
        efektywna_ref = poa_total
        if bifacial and bifacial_wspolczynnik > 0:
            zysk_bif = oblicz_zysk_bifacjalny(
                ghi, albedo, bifacial_wspolczynnik, przeswit_nad_gruntem_m
            )
            efektywna_ref += zysk_bif

        temp_ref = oblicz_temperature_panela_tmy(t_amb, efektywna_ref, noct)
        delta_t_ref = temp_ref - 25.0
        wsp_temp_ref = 1.0 + (wsp_temp / 100.0) * delta_t_ref
        wsp_temp_ref = max(0.5, min(1.2, wsp_temp_ref))
        moc_ref = moc_stc * liczba_paneli * (efektywna_ref / 1000.0) * wsp_temp_ref * wsp_degradacji
        if moc_nominalna_falownika_w and moc_nominalna_falownika_w > 0:
            eta_ref = oblicz_sprawnosc_falownika(moc_ref, moc_nominalna_falownika_w)
        else:
            eta_ref = 1.0 - straty_systemowe
        energia_ref = max(0.0, moc_ref * eta_ref)
        energia_bez_zacienienia += energia_ref

        energia_miesieczna[miesiac - 1] += energia_godziny
        energia_roczna += energia_godziny
        produkcja_godzinowa_wh.append(round(energia_godziny, 2))

    # Informacje o stringach
    stringi_info = []
    for si, s in enumerate(stringi):
        stringi_info.append({
            "nazwa": s.nazwa,
            "indeksy_paneli": s.indeksy_paneli,
            "liczba_paneli": len(s.indeksy_paneli),
            "energia_roczna_kwh": round(energia_per_string.get(si, 0.0) / 1000.0, 2),
        })

    # Strata z mismatch
    strata_mismatch = 0.0
    if energia_bez_zacienienia > 0:
        strata_mismatch = (1.0 - energia_roczna / energia_bez_zacienienia) * 100.0

    return {
        "roczna_kwh": round(energia_roczna / 1000.0, 2),
        "miesieczna_kwh": [round(e / 1000.0, 2) for e in energia_miesieczna],
        "stringi_info": stringi_info,
        "z_optymalizatorami": z_optymalizatorami,
        "strata_zacienienie_mismatch_procent": round(strata_mismatch, 2),
        "energia_bez_zacienienia_kwh": round(energia_bez_zacienienia / 1000.0, 2),
        "produkcja_godzinowa_wh": produkcja_godzinowa_wh,
    }


def _oblicz_roczna_produkcje_fallback(moc_stc_w: float,
                                       wspolczynnik_temp_pmax: float,
                                       technologia: str,
                                       liczba_sekcji: int,
                                       zacienienia_godzinowe: list,
                                       panel_index: int,
                                       szerokosc_geo: float,
                                       straty_systemowe: float,
                                       degradacja_roczna: float,
                                       rok_eksploatacji: int,
                                       kat_nachylenia: float,
                                       azymut_panela: float) -> Dict:
    """
    Stary model obliczen rocznej produkcji - fallback bez danych TMY.

    Uzywa hardcoded stalych NAPROMIENIOWANIE_SZCZYTOWE_POLSKA
    i TEMPERATURA_OTOCZENIA_POLSKA.
    """
    energia_miesieczna = [0.0] * 12
    energia_roczna = 0.0
    energia_bez_zacienienia = 0.0
    godziny_z_zacienieniem = 0

    for godzina_dane in zacienienia_godzinowe:
        miesiac = godzina_dane.miesiac
        godzina = godzina_dane.godzina
        elewacja = godzina_dane.elewacja_slonca
        azymut_slonca = godzina_dane.azymut_slonca

        # Napromieniowanie na plaszczyznie panela (POA)
        irradiancja = oblicz_napromieniowanie(
            miesiac, godzina, elewacja,
            kat_nachylenia=kat_nachylenia,
            azymut_panela=azymut_panela,
            azymut_slonca=azymut_slonca
        )
        if irradiancja <= 0:
            continue

        # Temperatura panela
        temp_panel = oblicz_temperature_panela(miesiac, godzina)

        # Znajdz dane zacienienia dla tego panela
        panel_zacienienie = None
        for pz in godzina_dane.panele:
            if pz.panel_index == panel_index:
                panel_zacienienie = pz
                break

        if panel_zacienienie is None:
            wsp_zacien = 1.0
        else:
            wsp_zacien = oblicz_wspolczynnik_zacienienia(
                panel_zacienienie, liczba_sekcji, technologia
            )
            if panel_zacienienie.stopien_zacienienia > 0:
                godziny_z_zacienieniem += 1

        # Oblicz wydajnosc z zacienieniem
        wynik = oblicz_wydajnosc_panela(
            moc_stc_w, irradiancja, temp_panel,
            wspolczynnik_temp_pmax, wsp_zacien,
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )

        energia_miesieczna[miesiac - 1] += wynik.energia_wh
        energia_roczna += wynik.energia_wh

        # Oblicz produkcje bez zacienienia (do porownania)
        wynik_bez = oblicz_wydajnosc_panela(
            moc_stc_w, irradiancja, temp_panel,
            wspolczynnik_temp_pmax, 1.0,  # brak zacienienia
            straty_systemowe, degradacja_roczna, rok_eksploatacji
        )
        energia_bez_zacienienia += wynik_bez.energia_wh

    # Straty z powodu zacienienia
    strata_zacienienie = 0.0
    if energia_bez_zacienienia > 0:
        strata_zacienienie = 1.0 - (energia_roczna / energia_bez_zacienienia)

    return {
        "panel_index": panel_index,
        "energia_roczna_kwh": round(energia_roczna / 1000.0, 2),
        "energia_miesieczna_kwh": [round(e / 1000.0, 2) for e in energia_miesieczna],
        "energia_bez_zacienienia_kwh": round(energia_bez_zacienienia / 1000.0, 2),
        "strata_zacienienie_procent": round(strata_zacienienie * 100.0, 2),
        "godziny_z_zacienieniem": godziny_z_zacienieniem,
        "moc_stc_w": moc_stc_w,
        "technologia": technologia,
        "zrodlo_danych": "fallback",
    }
