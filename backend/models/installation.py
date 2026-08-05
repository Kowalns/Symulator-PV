"""
Modele danych dla konfiguracji instalacji PV.

Zawiera dataclasses opisujace:
- PanelModel - parametry modelu panela fotowoltaicznego
- InverterModel - parametry falownika
- BatteryModel - parametry magazynu energii
- InstallationConfig - konfiguracja instalacji naziemnej na stelazu
- PanelPosition - pozycja pojedynczego panela w przestrzeni 3D
- InstallationLayout - wynik obliczen rozmieszczenia paneli
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PanelModel:
    """
    Model panela fotowoltaicznego z pelna charakterystyka.

    Atrybuty:
        id: unikalny identyfikator modelu
        producent: nazwa producenta (np. "JA Solar")
        model: pelna nazwa modelu
        moc_wp: moc szczytowa w watach (Wp)
        wymiary_mm: wymiary panela - szerokosc i wysokosc w mm
        wydajnosc_procent: sprawnosc konwersji energii slonecznej
        wspolczynnik_temp_pmax: wspolczynnik temperaturowy mocy (%/C)
        technologia: typ ogniw ("half-cut" lub "standard")
        liczba_sekcji_bypass: ile sekcji chronionych diodami bypass (typowo 3)
        napiecie_mpp: napiecie w punkcie maksymalnej mocy (V)
        prad_mpp: prad w punkcie maksymalnej mocy (A)
        napiecie_oc: napiecie obwodu otwartego (V)
        prad_sc: prad zwarcia (A)
        degradacja_roczna_procent: roczna degradacja mocy (%)
        waga_kg: masa panela (kg)
        gwarancja_lata: okres gwarancji producenta (lata)
    """
    id: str
    producent: str
    model: str
    moc_wp: int
    wymiary_mm: dict  # {"szerokosc": int, "wysokosc": int}
    wydajnosc_procent: float
    wspolczynnik_temp_pmax: float
    technologia: str
    liczba_sekcji_bypass: int
    napiecie_mpp: float
    prad_mpp: float
    napiecie_oc: float
    prad_sc: float
    degradacja_roczna_procent: float
    waga_kg: float
    gwarancja_lata: int


@dataclass
class InverterModel:
    """
    Model falownika (inwertera) PV.

    Atrybuty:
        id: unikalny identyfikator
        producent: nazwa producenta
        model: pelna nazwa modelu
        moc_max_dc: maksymalna moc wejsciowa DC (W)
        moc_wyjsciowa_ac: moc wyjsciowa AC (W)
        zakres_mppt_v: zakres napiec MPPT {"min": V, "max": V}
        liczba_mppt: liczba niezaleznych wejsc MPPT
        max_prad_wejsciowy: maksymalny prad wejsciowy na MPPT (A)
        sprawnosc_procent: sprawnosc konwersji DC/AC (%)
        czy_optymalizatory: czy wymaga optymalizatorow mocy (SolarEdge)
    """
    id: str
    producent: str
    model: str
    moc_max_dc: int
    moc_wyjsciowa_ac: int
    zakres_mppt_v: dict  # {"min": float, "max": float}
    liczba_mppt: int
    max_prad_wejsciowy: float
    sprawnosc_procent: float
    czy_optymalizatory: bool


@dataclass
class BatteryModel:
    """
    Model magazynu energii (baterii).

    Atrybuty:
        id: unikalny identyfikator
        producent: nazwa producenta
        model: pelna nazwa modelu
        pojemnosc_kwh: pojemnosc uzytkowa (kWh)
        moc_ladowania_kw: maksymalna moc ladowania (kW)
        moc_rozladowania_kw: maksymalna moc rozladowania (kW)
        cykle_zycia: liczba cykli ladowania/rozladowania
        dod_procent: glebokosc rozladowania (DoD) w %
        sprawnosc_roundtrip_procent: sprawnosc cyklu ladowania/rozladowania (%)
    """
    id: str
    producent: str
    model: str
    pojemnosc_kwh: float
    moc_ladowania_kw: float
    moc_rozladowania_kw: float
    cykle_zycia: int
    dod_procent: float
    sprawnosc_roundtrip_procent: float


@dataclass
class InstallationConfig:
    """
    Konfiguracja instalacji PV na stelazu naziemnym.

    Atrybuty:
        panel_id: identyfikator wybranego modelu panela
        orientacja: orientacja paneli - "pion" (portrait) lub "poziom" (landscape)
        kat_nachylenia: kat nachylenia paneli w stopniach (15-60)
        azymut: kierunek ustawienia paneli (0=poludnie, -90=wschod, 90=zachod)
        przeswit_nad_gruntem_cm: wysokosc dolnej krawedzi nad gruntem (20-100 cm)
        odstep_miedzy_rzedami_cm: odstep miedzy rzedami paneli (50-300 cm)
        odstep_boczny_cm: odstep boczny miedzy panelami w rzedzie (2-20 cm)
        liczba_paneli: calkowita liczba paneli w instalacji
        liczba_kolumn: liczba kolumn (paneli obok siebie w rzedzie)
        liczba_rzedow: liczba rzedow (paneli jeden za drugim)
    """
    panel_id: str
    orientacja: str = "pion"
    kat_nachylenia: float = 30.0
    azymut: float = 0.0
    przeswit_nad_gruntem_cm: float = 50.0
    odstep_miedzy_rzedami_cm: float = 150.0
    odstep_boczny_cm: float = 3.0
    liczba_paneli: int = 10
    liczba_kolumn: int = 5
    liczba_rzedow: int = 2


@dataclass
class PanelPosition:
    """
    Pozycja pojedynczego panela w przestrzeni 3D.

    Wspolrzedne podawane w metrach.
    Punkt odniesienia (0,0,0) - srodek instalacji na poziomie gruntu.

    Atrybuty:
        index: numer panela (od 0)
        rzad: numer rzedu (od 0)
        kolumna: numer kolumny (od 0)
        x: pozycja w osi X (wschod-zachod) [m]
        y: pozycja w osi Y (gora-dol, wysokosc srodka panela) [m]
        z: pozycja w osi Z (polnoc-poludnie) [m]
        szerokosc_m: szerokosc panela w orientacji montazu [m]
        wysokosc_m: wysokosc panela w orientacji montazu [m]
        kat_nachylenia: kat nachylenia tego panela [stopnie]
    """
    index: int
    rzad: int
    kolumna: int
    x: float
    y: float
    z: float
    szerokosc_m: float
    wysokosc_m: float
    kat_nachylenia: float


@dataclass
class InstallationLayout:
    """
    Wynik obliczen rozmieszczenia paneli - gotowy do wizualizacji.

    Atrybuty:
        panele: lista pozycji wszystkich paneli
        moc_calkowita_kwp: calkowita moc instalacji (kWp)
        wymiary_instalacji_m: wymiary calej instalacji {szerokosc, glebokosc, wysokosc}
        liczba_paneli: calkowita liczba paneli
        panel_model: dane wybranego modelu panela
        config: uzyta konfiguracja
    """
    panele: List[PanelPosition] = field(default_factory=list)
    moc_calkowita_kwp: float = 0.0
    wymiary_instalacji_m: dict = field(default_factory=dict)
    liczba_paneli: int = 0
    panel_model: Optional[dict] = None
    config: Optional[dict] = None

    def to_dict(self) -> dict:
        """Zamienia layout na slownik do serializacji JSON."""
        return {
            "panele": [
                {
                    "index": p.index,
                    "rzad": p.rzad,
                    "kolumna": p.kolumna,
                    "x": round(p.x, 4),
                    "y": round(p.y, 4),
                    "z": round(p.z, 4),
                    "szerokosc_m": round(p.szerokosc_m, 4),
                    "wysokosc_m": round(p.wysokosc_m, 4),
                    "kat_nachylenia": p.kat_nachylenia,
                }
                for p in self.panele
            ],
            "moc_calkowita_kwp": round(self.moc_calkowita_kwp, 3),
            "wymiary_instalacji_m": self.wymiary_instalacji_m,
            "liczba_paneli": self.liczba_paneli,
            "panel_model": self.panel_model,
            "config": self.config,
        }
