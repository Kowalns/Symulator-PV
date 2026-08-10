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
    1. Bypass diody: jesli sekcja zacieniona >50%, bypass aktywuje sie,
       sekcja daje 0 mocy (strata ~1/liczba_sekcji mocy panela).
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
                                    noct: float = NOCT_DOMYSLNY) -> Dict:
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

    Zwraca:
        Slownik z wynikami rocznymi i miesiecznymi
    """
    # Jesli mamy dane TMY - uzywamy nowego modelu POA
    if dane_tmy is not None:
        return _oblicz_roczna_produkcje_tmy(
            moc_stc_w, wspolczynnik_temp_pmax, technologia, liczba_sekcji,
            zacienienia_godzinowe, panel_index, straty_systemowe,
            degradacja_roczna, rok_eksploatacji, kat_nachylenia,
            azymut_panela, dane_tmy, noct
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
                                  noct: float) -> Dict:
    """
    Oblicza roczna produkcje panela z wykorzystaniem danych TMY.

    Model POA: rozdziela irradiancje na beam/diffuse/ground.
    Cien blokuje TYLKO skladnik beam - diffuse dociera niezaleznie.
    Temperatura z modelu NOCT i danych TMY.
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
            kat_nachylenia, azymut_panela
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
        wynik_bez = oblicz_wydajnosc_panela(
            moc_stc_w, poa_total, temp_panel,
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
