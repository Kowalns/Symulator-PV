# Symulator PV - Kompleksowy symulator instalacji fotowoltaicznej

## Co to jest?

Symulator PV to darmowa aplikacja webowa do planowania i symulacji naziemnej instalacji fotowoltaicznej (2-14 kWp). Pozwala:

- Zwizualizowac budynek w 3D i rozmiescic panele na gruncie
- Zasymulowac zacienienie paneli przez budynek (godzina po godzinie, caly rok)
- Obliczyc realna produkcje energii z uwzglednieniem strat
- Przeanalizowac oplacalnosc z taryfami Energa (G11, G11f, dynamiczna)
- Dobrac magazyn energii bez przewymiarowania
- Porownac wiele scenariuszy instalacji obok siebie

**Dla kogo:** Dla kazdego, kto planuje instalacje PV na gruncie i chce dokadnie wiedziec ile energii wyprodukuje, ile zaoszczedzi i jaka konfiguracje wybrac.

---

## Slowniczek (dla poczatkujacych)

| Termin | Co to znaczy |
|--------|-------------|
| **PV / fotowoltaika** | Technologia zamieniania swiatla slonecznego na prad elektryczny |
| **kWp (kilowat-peak)** | Moc szczytowa instalacji - ile moze dac w idealnych warunkach |
| **kWh (kilowatogodzina)** | Jednostka energii. Czajnik zuzywa ~1 kWh aby zagotowac wode |
| **Stelaz naziemny** | Konstrukcja metalowa na gruncie, na ktorej montuje sie panele |
| **Bypass dioda** | Element panela, ktory "omija" zacieniona czesc, ograniczajac straty |
| **Half-cut** | Technologia panela - ogniwa sa przepolowione, dzieki czemu cien na jednej polowie nie wplywa na druga |
| **Optymalizator mocy** | Urzadzenie montowane na panelu - pozwala mu pracowac niezaleznie od zacienionego sasiada |
| **Falownik (inwerter)** | Zamienia prad staly z paneli (DC) na prad zmienny do gniazdek (AC) |
| **MPPT** | Tracker szukajacy optymalnego punktu pracy paneli (wbudowany w falownik) |
| **RCE** | Rynkowa Cena Energii - cena gieldowa energii na TGE (Towarowa Gielda Energii) |
| **Autokonsumpcja** | Ile % wyprodukowanej energii zuzywasz sam (nie oddajesz do sieci) |
| **Samowystarczalnosc** | Ile % Twojego zuzycia pokrywasz wlasna energia z PV |
| **COP (pompa ciepla)** | Wspolczynnik wydajnosci - COP 4.0 = z 1 kWh pradu robi 4 kWh ciepla |

---

## Jak uruchomic?

### Wymagania
- Python 3.9 lub nowszy (sprawdz: `python3 --version`)
- Przegladarka internetowa (Chrome, Firefox, Edge)
- Polaczenie z internetem (do pobrania Three.js z CDN i danych z PVGIS)

### Uruchomienie

```bash
# 1. Przejdz do katalogu projektu
cd sciezka/do/Symulator-PV

# 2. Uruchom serwer
python3 backend/main.py

# 3. Otworz przegladarke
# http://localhost:8000
```

Serwer uruchomi sie na porcie 8000. Otworz przegladarke i wejdz na `http://localhost:8000`.

### Zatrzymanie
Nacisnij `Ctrl+C` w terminalu.

### Uruchomienie testow

```bash
python3 -m unittest discover -s backend/tests -p 'test_*.py' -v
```

---

## Funkcje aplikacji - strona po stronie

### 1. Strona glowna (`http://localhost:8000`)

Prosty kalkulator PV - podajesz lokalizacje i parametry, dostajesz szacunkowa roczna produkcje. Dane z PVGIS (europejska baza naslonecznienia).

**Co podajesz:**
- Lokalizacja (wspolrzedne lub miasto)
- Moc instalacji (kWp)
- Kat nachylenia paneli
- Azymut (kierunek: poludnie = 0)
- Straty systemowe (%)

### 2. Widok 3D (`http://localhost:8000/viewer.html`)

Interaktywna scena 3D z budynkiem, dzialka i panelami PV.

**Mozliwosci:**
- Wczytanie modelu budynku (plik STL)
- Pobranie granic dzialki z ULDK (po numerze katastralnym)
- Reczne rysowanie granic dzialki
- Konfiguracja instalacji PV:
  - Wybor paneli z bazy (12 modeli)
  - Orientacja: pion / poziom
  - Kat nachylenia
  - Pozycja na dzialce
  - Wizualizacja rozmieszczenia paneli

**Obsluga:**
- Obracanie widoku: lewy przycisk myszy + ruch
- Przybilizanie: kolko myszy
- Przesuwanie: prawy przycisk myszy + ruch

### 3. Profil energetyczny (`http://localhost:8000/pages/energy-profile.html`)

Konfiguracja zuzycia energii i analiza ekonomiczna.

**Co mozesz ustawic:**
- Obciazenie bazowe domu (stale zuzycie: lodowka, router, itp.)
- Urzadzenia i ich godziny pracy
- Gruntowa pompa ciepla (profil grzewczy)
- Taryfa Energa (G11, G11f, dynamiczna)

**Co dostajesz:**
- Profil zuzycia godzinowego
- Bilans energetyczny (produkcja vs zuzycie)
- Analiza oplacalnosci taryf
- Oszczednosci roczne

### 4. Raport (`http://localhost:8000/pages/report.html`)

Kompleksowy raport z symulacji i porownanie scenariuszy.

**Zawartosc raportu:**
- Produkcja miesieczna i roczna (kWh)
- Straty na zacienieniu (vs instalacja bez zacienienia)
- Samowystarczalnosc w kazdym miesiacu
- Zalecenia: optymalna pozycja, kat, orientacja
- Dobor magazynu energii (bez przewymiarowania)
- Porownanie 14+ scenariuszy side-by-side

---

## Baza urzadzen

### Panele PV (12 modeli)
Najpopularniejsze na polskim rynku: JA Solar, Jinko Solar, Trina Solar, Canadian Solar, LONGi, Risen, DMEGC i inne.

Parametry w bazie: moc (Wp), wymiary, wydajnosc, wspolczynnik temperaturowy, technologia (half-cut), liczba sekcji bypass, napiecie/prad MPP, degradacja roczna.

### Falowniki (14 modeli)
Huawei SUN2000, SolarEdge, Fronius, GoodWe, Sungrow, Fox ESS, Sofar Solar, Deye.

Parametry: moc AC/DC, zakres MPPT, liczba MPPT, sprawnosc, wsparcie optymalizatorow.

### Magazyny energii (11 modeli)
BYD Battery-Box, Huawei LUNA2000, SolarEdge Home Battery, Pylontech, Fox ESS, BYD LVS, Sofar.

Parametry: pojemnosc (kWh), moc ladowania/rozladowania, cykle zycia, DoD, sprawnosc roundtrip.

---

## API - dokumentacja endpointow

### GET /api/health
Sprawdzenie czy serwer dziala.
```json
{"status": "ok"}
```

### GET /api/panels
Lista paneli PV z bazy danych.

### GET /api/inverters
Lista falownikow z bazy danych.

### GET /api/batteries
Lista magazynow energii z bazy danych.

### GET /api/tariffs
Dane taryf Energa (G11, G11f, dynamiczna) z cenami.

### GET /api/uldk
Proxy do ULDK (geoportal) - pobieranie granic dzialek.
```
GET /api/uldk?request=GetParcelById&id=141201_1.0001.6509&result=geom_wkt&srid=4326
```

### GET /models/Dom.STL
Pobranie pliku STL modelu budynku.

### POST /api/simulate
Symulacja podstawowa - produkcja roczna z PVGIS.
```json
{
  "latitude": 52.23,
  "longitude": 21.01,
  "peak_power_kw": 5.0,
  "tilt_angle": 35,
  "azimuth_angle": 0,
  "system_loss_percent": 14
}
```

### POST /api/installation/configure
Konfiguracja instalacji naziemnej - rozmieszczenie paneli.
```json
{
  "panel_id": "ja_solar_jam72s30_550mr",
  "orientation": "landscape",
  "tilt_angle": 35,
  "ground_clearance_cm": 50,
  "row_spacing_cm": 200,
  "target_power_kwp": 5.0,
  "position_x": 10.0,
  "position_y": 15.0,
  "azimuth": 180
}
```

### POST /api/shading/simulate
Symulacja zacienienia - godzinowa analiza cienia na panelach.
```json
{
  "latitude": 54.35,
  "longitude": 18.65,
  "panels": [...],
  "building_vertices": [...],
  "use_optimizers": false,
  "year": 2024
}
```

### POST /api/energy-profile
Utworzenie profilu zuzycia energii.
```json
{
  "base_load_w": 300,
  "devices": [...],
  "heat_pump": {
    "enabled": true,
    "power_kw": 2.5,
    "cop": 4.0,
    "heating_months": [1, 2, 3, 4, 10, 11, 12]
  }
}
```

### POST /api/economics/analyze
Analiza ekonomiczna - bilansowanie godzinowe PV vs zuzycie.
```json
{
  "production_hourly": [...],
  "consumption_hourly": [...],
  "tariff": "G11",
  "battery_id": "byd_hvs_5_1",
  "sell_surplus": true
}
```

### POST /api/report/generate
Generowanie raportu rocznego/miesiecznego.
```json
{
  "simulation_results": {...},
  "economics_results": {...},
  "include_recommendations": true
}
```

### POST /api/scenarios/compare
Porownanie wielu scenariuszy (do 14+).
```json
{
  "scenarios": [
    {"name": "5kWp G11", "power_kwp": 5, "tariff": "G11", "battery": null},
    {"name": "5kWp G11f + bateria", "power_kwp": 5, "tariff": "G11f", "battery": "byd_hvs_5_1"}
  ]
}
```

---

## Architektura projektu

```
Symulator-PV/
├── backend/                    # Serwer Python (stdlib)
│   ├── main.py                # Uruchomienie serwera HTTP (port 8000)
│   ├── api/
│   │   └── handlers.py        # Obsluga endpointow API
│   ├── services/              # Logika obliczen
│   │   ├── calculator.py      # Podstawowy kalkulator PV (PVGIS)
│   │   ├── pvgis.py           # Pobieranie danych z PVGIS API
│   │   ├── installation_layout.py  # Rozmieszczenie paneli na gruncie
│   │   ├── solar_position.py  # Algorytm pozycji slonca
│   │   ├── shading.py         # Symulacja zacienienia (godzinowa)
│   │   ├── panel_performance.py  # Wydajnosc paneli (temperatura, cien)
│   │   ├── optimizer.py       # Optymalizatory mocy
│   │   ├── energy_profile.py  # Profil zuzycia energii
│   │   ├── rce_prices.py      # Ceny gieldowe RCE (godzinowe)
│   │   ├── economics.py       # Analiza ekonomiczna
│   │   ├── report_generator.py  # Generator raportow
│   │   ├── battery_sizing.py  # Dobor magazynu energii
│   │   └── scenario_comparison.py  # Porownanie scenariuszy
│   ├── models/
│   │   ├── simulation.py      # Modele danych symulacji
│   │   └── installation.py    # Modele danych instalacji
│   ├── data/
│   │   ├── panels_database.json    # Baza paneli (12 modeli)
│   │   ├── inverters_database.json # Baza falownikow (14 modeli)
│   │   ├── batteries_database.json # Baza magazynow (11 modeli)
│   │   └── tariffs.json            # Taryfy Energa + info RCE
│   └── tests/                 # Testy jednostkowe
│       ├── test_calculator.py
│       ├── test_handlers.py
│       ├── test_parcel.py
│       ├── test_installation.py
│       ├── test_solar_position.py
│       ├── test_shading.py
│       ├── test_economics.py
│       └── test_report.py
├── frontend/                   # Interfejs uzytkownika (przegladarka)
│   ├── index.html             # Strona glowna - kalkulator PV
│   ├── viewer.html            # Widok 3D - scena z budynkiem i panelami
│   ├── pages/
│   │   ├── energy-profile.html  # Profil zuzycia i analiza ekonomiczna
│   │   └── report.html         # Raport i porownanie scenariuszy
│   ├── js/
│   │   ├── app.js              # Logika kalkulatora PV
│   │   ├── viewer3d.js         # Scena Three.js (kamera, swiatla)
│   │   ├── stl-loader.js       # Parser plikow STL (binarny)
│   │   ├── parcel.js           # Integracja ULDK + rysowanie granic
│   │   └── installation-config.js  # Konfiguracja instalacji w 3D
│   └── css/
│       ├── style.css           # Styl strony glownej
│       └── viewer.css          # Styl widoku 3D
├── .kiro/steering/
│   └── project-plan.md        # Pelny plan projektu (ten dokument)
├── Dom.STL                    # Model 3D budynku (binarny STL)
├── Energa.zip                 # Faktury Energa (zrodlo cen taryf)
└── README.md                  # Ten plik
```

---

## Kluczowe informacje techniczne

### Symulacja zacienienia
- Rozdzielczosc: godzinowa (8760 godzin w roku)
- Algorytm: pozycja slonca -> rzutowanie cienia budynku -> sprawdzenie pokrycia kazdej sekcji panela
- Wynik: dla kazdego panela, kazdej godziny - ile sekcji bypass aktywowanych

### Bypass diody - jak to dziala
Panel ma 3 sekcje. Jezeli cien pokrywa sekcje w wiecej niz 50%, dioda bypass "omija" te sekcje. Strata = ~33% mocy panela (1/3 wylaczona). Jesli 2 sekcje zacienione = 66% straty.

### Magazyn energii - WAZNE
- Ladowanie **TYLKO z PV** (nie z sieci!)
- Arbitraz cenowy (kup tanio z sieci, sprzedaj drogo) jest **NIEMOZLIWY w Polsce**
- Magazyn sluzy do przechowania nadwyzki PV na wieczor (autokonsumpcja)

### Optymalizatory - kiedy stosowac
- Kiedy czesc paneli jest regularnie zacieniana
- Montaz: na kazdy zacieniony panel (nie na wszystkie)
- Efekt: zacieniony panel nie sciaga w dol reszty stringu
- Wymaga kompatybilnego falownika

---

## Technologie

| Warstwa | Technologia | Koszt |
|---------|-------------|-------|
| Backend | Python 3.9+ (stdlib: http.server, json, dataclasses) | darmowe |
| Frontend | HTML5 + CSS3 + vanilla JavaScript | darmowe |
| 3D | Three.js (CDN jsdelivr.net) | darmowe |
| Dane pogodowe | PVGIS API (Komisja Europejska) | darmowe |
| Mapy/dzialki | ULDK API (geoportal.gov.pl) | darmowe |
| Ceny energii | TGE RCE (dane historyczne) | darmowe |

**Calkowity koszt narzedzi: 0 zl**

---

## Licencja

Projekt open-source. Darmowy do uzytku.
