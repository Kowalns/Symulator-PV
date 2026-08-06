# Backup sesji - Symulator PV

> **Data ostatniej aktualizacji:** 2025-01-XX (sesja odzyskiwania utraconej pracy)
> **Branch:** `feature/restore-all-lost-work`
> **PR:** https://github.com/Kowalns/Symulator-PV/pull/2
> **Status testow:** 243 testy PASS (python3 -m unittest discover -s backend/tests -p 'test_*.py')

---

## 1. Cel projektu

Symulator PV to darmowa aplikacja webowa do kompleksowej symulacji naziemnej instalacji fotowoltaicznej (2-14 kWp) dla domu jednorodzinnego. Uzytkownik planuje instalacje PV na stelazu gruntowym, z gruntowa pompa ciepla do ogrzewania, na terenie operatora Energa w Polsce.

### Glowne cele:
- Wizualizacja 3D budynku i paneli na gruncie (Three.js + STL)
- Symulacja zacienienia godzinowego (8760h/rok) z uwzglednieniem bypass diod, half-cut, optymalizatorow
- Analiza ekonomiczna z taryfami Energa (G11, G11f, dynamiczna) i cenami RCE
- Dobor magazynu energii bez przewymiarowania (ladowanie TYLKO z PV)
- Porownanie 14+ scenariuszy side-by-side
- Optymalizacja pod samowystarczalnosc jesienia

### Profil uzytkownika:
- Poczatkujacy w programowaniu, PV i elektronice
- Planuje realna instalacje (nie akademicki projekt)
- Ogrzewanie gruntowa pompa ciepla (duze zuzycie zimowe)
- Operator: Energa (Polska polnocna)
- Chce PRECYZYJNYCH danych, nie przyblizonej estymacji

---

## 2. Kluczowe decyzje projektowe

Te decyzje zostaly podjete w trakcie sesji i sa OBOWIAZUJACE:

| # | Decyzja | Uzasadnienie |
|---|---------|-------------|
| 1 | Zero zaleznosci Python (tylko stdlib) | Uzytkownik nie chce pip install; prostota |
| 2 | Three.js z CDN (jsdelivr.net) | Jedyna zewnetrzna zaleznosc - do 3D w przegladarce |
| 3 | Zero kosztow na narzedzia | Brak platnych API, bibliotek, subskrypcji |
| 4 | Instalacja NAZIEMNA (stelaz gruntowy) | NIE dachowa - panele stoja na gruncie obok budynku |
| 5 | Bypass diody: >50% zacienienia sekcji = aktywacja | Strata ~33% mocy panela (1/3 wylaczona) |
| 6 | Half-cut: 2 polowki niezalezne | Cien na jednej polowie nie wplywa na druga |
| 7 | Arbitraz cenowy NIEMOZLIWY w Polsce | Regulacje prawne - magazyn laduje sie TYLKO z PV, nie z sieci |
| 8 | G11 = stala cena calodobowa (~1.14 zl/kWh brutto) | Z faktur Energa 2024 |
| 9 | G11f = dynamiczna cena RCE + nizsza dystrybucja (0.2180 zl/kWh) | Wyzsza oplata stala (~73 zl/mc), ale nizsza dystrybucja i dynamiczna cena energii |
| 10 | Sprzedaz nadwyzki po cenach RCE z danej godziny | Nie srednia roczna - godzinowa cena z PSE |
| 11 | Degradacja 0.5%/rok | Standard branzy, gwarancja 80% po 25 latach |
| 12 | Straty systemowe 2-5% | Kable, konwersja, brud na panelach |
| 13 | Temperatura: wspolczynnik Pmax (typowo -0.35%/st. C) | Latem panele traca 10-15% mocy |
| 14 | Kat nachylenia optymalizowany pod jesien | Wiekszy kat = lepsza produkcja jesienia (samowystarczalnosc) |
| 15 | Porownanie minimum 14 scenariuszy | Tabela side-by-side, wyroznienie najlepszych |
| 16 | Magazyn - dobor BEZ przewymiarowania | Analiza szczytu wieczornego, nie wiekszy niz potrzebny |
| 17 | Gruntowa pompa ciepla | COP 4.0-5.0, zuzycie 3000-6000 kWh/rok na ogrzewanie |
| 18 | Komentarze i dokumentacja PO POLSKU | Uzytkownik jest Polakiem, angielski utrudnialby zrozumienie |
| 19 | Ceny BRUTTO (z VAT) | Tak jak na fakturze - uzytkownik widzi realne kwoty |
| 20 | Baza paneli: najpopularniejsze w Polsce | JA Solar, Jinko, Trina, Canadian Solar, LONGi, Risen, DMEGC |

---

## 3. Aktualny stan realizacji

### Zrealizowane funkcjonalnosci (wszystkie GOTOWE i PRZETESTOWANE):

#### FEAT-001: Widok 3D + STL + ULDK
- **Status:** DONE
- **Pliki:** frontend/viewer.html, frontend/js/viewer3d.js, frontend/js/stl-loader.js, frontend/js/parcel.js, frontend/css/viewer.css
- **Co robi:**
  - Ladowanie modelu budynku z pliku STL (binarny parser)
  - Scena Three.js z kamera, swiatlem, cieniami, OrbitControls
  - Pobieranie granic dzialki z ULDK (proxy w backendzie, URL encoding)
  - Reczne rysowanie granic dzialki (klikanie punktow)
- **Testy:** test_handlers.py, test_parcel.py

#### FEAT-002: Baza urzadzen + konfiguracja instalacji
- **Status:** DONE
- **Pliki:** backend/data/panels_database.json (12 modeli), backend/data/inverters_database.json (14), backend/data/batteries_database.json (11), backend/services/installation_layout.py, backend/models/installation.py, frontend/js/installation-config.js
- **Co robi:**
  - Pelna baza paneli z parametrami (moc, wymiary, technologia, bypass, temperatura)
  - Baza falownikow (Huawei, SolarEdge, Fronius, GoodWe, Sungrow, Fox ESS, Sofar, Deye)
  - Baza magazynow (BYD, Huawei LUNA, SolarEdge, Pylontech, Fox ESS, Sofar)
  - Kalkulator rozmieszczenia: orientacja pion/poziom, kat, przeswit, odstepy
  - Obliczanie samozacienienia miedzy rzedami
  - Wizualizacja 3D rozmieszczonych paneli
- **Testy:** test_installation.py

#### FEAT-003: Symulacja zacienienia
- **Status:** DONE
- **Pliki:** backend/services/solar_position.py, backend/services/shading.py, backend/services/panel_performance.py, backend/services/optimizer.py
- **Co robi:**
  - Algorytm pozycji slonca (azymut + elewacja) dla 8760 godzin/rok
  - Convex hull cienia budynku rzutowany na plaszczyzne paneli
  - Sprawdzenie pokrycia kazdej sekcji bypass kazdego panela
  - Logika bypass diod (>50% = aktywacja, strata 33%)
  - Half-cut: niezalezne polowki
  - Optymalizatory mocy: minimalizacja mismatch w stringu
  - Wplyw temperatury (NOCT model)
  - Degradacja roczna 0.5%
  - Straty systemowe konfigurowalne 2-5%
  - Automatyczne wykrywanie CET/CEST (czas letni/zimowy)
- **Testy:** test_solar_position.py, test_shading.py

#### FEAT-004: Analiza ekonomiczna
- **Status:** DONE
- **Pliki:** backend/services/energy_profile.py, backend/services/rce_prices.py, backend/services/economics.py, backend/data/tariffs.json, frontend/pages/energy-profile.html
- **Co robi:**
  - Profil zuzycia: obciazenie bazowe + urzadzenia godzinowe + pompa ciepla
  - Taryfy Energa z realnymi cenami 2024 (G11: 1.14, G11f: 1.01, dynamiczna: RCE)
  - Ceny RCE godzinowe (profil historyczny - tanio w poludnie, drogo wieczorem)
  - Bilansowanie godzinowe: PV vs zuzycie vs magazyn vs siec
  - Sprzedaz nadwyzki po RCE z danej godziny
  - Magazyn: ladowanie z PV, rozladowanie wieczorem, sprawnosc roundtrip 95%
  - Obliczanie oszczednosci rocznych, zwrotu inwestycji
- **Testy:** test_economics.py

#### FEAT-005: Raport + porownanie scenariuszy
- **Status:** DONE
- **Pliki:** backend/services/report_generator.py, backend/services/battery_sizing.py, backend/services/scenario_comparison.py, frontend/pages/report.html
- **Co robi:**
  - Raport roczny i miesieczny (produkcja, straty, samowystarczalnosc)
  - Zalecenia: zmiana pozycji, orientacji, kata
  - Dobor magazynu: analiza szczytu wieczornego 17:00-23:00
  - Porownanie 14+ scenariuszy w tabeli side-by-side
  - Metryki: produkcja, autokonsumpcja, samowystarczalnosc, oszczednosc, zwrot
  - Wyroznienie najlepszego scenariusza per metryka
- **Testy:** test_report.py

#### FEAT-006: Dokumentacja projektu
- **Status:** DONE
- **Pliki:** .kiro/steering/project-plan.md, README.md
- **Co robi:**
  - Pelny plan projektu ze wszystkimi decyzjami
  - README z dokumentacja funkcji, API, architektura, slowniczkiem

---

## 4. Architektura i struktura plikow

```
Symulator-PV/
├── backend/
│   ├── main.py                     # Serwer HTTP na porcie 8000
│   ├── api/
│   │   └── handlers.py             # Obsluga endpointow REST API
│   ├── services/
│   │   ├── calculator.py           # Kalkulator PV (PVGIS)
│   │   ├── pvgis.py                # Pobieranie danych naslonecznienia
│   │   ├── installation_layout.py  # Rozmieszczenie paneli na gruncie
│   │   ├── solar_position.py       # Algorytm pozycji slonca
│   │   ├── shading.py              # Symulacja zacienienia (convex hull)
│   │   ├── panel_performance.py    # Wydajnosc z temperatura/cien/degradacja
│   │   ├── optimizer.py            # Optymalizatory mocy
│   │   ├── energy_profile.py       # Profil zuzycia energii
│   │   ├── rce_prices.py           # Ceny RCE godzinowe
│   │   ├── economics.py            # Analiza ekonomiczna
│   │   ├── report_generator.py     # Generator raportow
│   │   ├── battery_sizing.py       # Dobor magazynu
│   │   └── scenario_comparison.py  # Porownanie scenariuszy
│   ├── models/
│   │   ├── simulation.py           # Modele danych symulacji
│   │   └── installation.py         # Modele danych instalacji
│   ├── data/
│   │   ├── panels_database.json    # 12 modeli paneli
│   │   ├── inverters_database.json # 14 modeli falownikow
│   │   ├── batteries_database.json # 11 modeli magazynow
│   │   └── tariffs.json            # Taryfy Energa
│   └── tests/
│       ├── test_calculator.py
│       ├── test_handlers.py
│       ├── test_parcel.py
│       ├── test_installation.py
│       ├── test_solar_position.py
│       ├── test_shading.py
│       ├── test_economics.py
│       └── test_report.py
├── frontend/
│   ├── index.html                  # Strona glowna - kalkulator
│   ├── viewer.html                 # Widok 3D
│   ├── pages/
│   │   ├── energy-profile.html     # Profil zuzycia
│   │   └── report.html             # Raport i scenariusze
│   ├── js/
│   │   ├── app.js                  # Logika kalkulatora
│   │   ├── viewer3d.js             # Scena Three.js
│   │   ├── stl-loader.js           # Parser STL
│   │   ├── parcel.js               # ULDK + rysowanie granic
│   │   └── installation-config.js  # Konfiguracja instalacji
│   └── css/
│       ├── style.css
│       └── viewer.css
├── .kiro/
│   ├── steering/
│   │   ├── project-plan.md         # Pelny plan projektu
│   │   └── backup-protocol.md      # Protokol backupow (ten plik)
│   └── backups/
│       └── SESSION-LOG.md          # TEN PLIK - backup sesji
├── Dom.STL                         # Model 3D budynku (binarny)
├── Energa.zip                      # Faktury Energa (zrodlo cen)
└── README.md
```

---

## 5. API - endpointy (skrot)

| Metoda | Endpoint | Opis |
|--------|----------|------|
| GET | /api/health | Status serwera |
| GET | /api/panels | Lista paneli PV |
| GET | /api/inverters | Lista falownikow |
| GET | /api/batteries | Lista magazynow energii |
| GET | /api/tariffs | Taryfy Energa |
| GET | /api/uldk?... | Proxy do geoportalu (granice dzialek) |
| GET | /models/Dom.STL | Plik STL budynku |
| POST | /api/simulate | Symulacja podstawowa (PVGIS) |
| POST | /api/installation/configure | Konfiguracja rozmieszczenia paneli |
| POST | /api/shading/simulate | Symulacja zacienienia godzinowego |
| POST | /api/energy-profile | Profil zuzycia energii |
| POST | /api/economics/analyze | Analiza ekonomiczna |
| POST | /api/report/generate | Generowanie raportu |
| POST | /api/scenarios/compare | Porownanie scenariuszy |

---

## 6. Wymagania techniczne

- **Python:** 3.9+ (tylko stdlib, BEZ pip install)
- **Przegladarka:** Chrome/Firefox/Edge (nowoczesna)
- **Port:** 8000 (http.server)
- **Jedyna zewnetrzna zaleznosc runtime:** Three.js z CDN
- **API zewnetrzne (darmowe):** PVGIS, ULDK, dane RCE

### Uruchomienie:
```bash
python3 backend/main.py          # Serwer na localhost:8000
python3 -m unittest discover -s backend/tests -p 'test_*.py' -v  # Testy
```

---

## 7. Co trzeba zrobic dalej (TODO)

### Priorytety (kolejne kroki):
1. **Integracja frontendu** - polaczenie stron HTML z endpointami API (formularze, wyswietlanie wynikow)
2. **Wizualizacja zacienienia w 3D** - pokazanie cieni na scenie Three.js w czasie rzeczywistym
3. **Export raportu** - PDF lub drukowanie z przegladarki
4. **Optymalizacja pozycji** - algorytm szukajacy najlepszej pozycji paneli wzgledem budynku
5. **Pobranie realnych danych PVGIS** - integracja z API (wymaga internetu)
6. **Testy integracyjne** - testy calego flow od konfiguracji do raportu

### Pomysly na pozniej:
- Wizualizacja animowana cienia w ciagu dnia
- Import wiecej formatow 3D (OBJ, GLTF)
- Mapa cieplna zacienienia na panelach
- Porownanie z ofertami instalatorow

---

## 8. Znane problemy i uwagi

### Rozwiazane problemy (z code review):
1. **Convex hull cienia** - naprawiony algorytm rzutowania (byl blad z sortowaniem wierzcholkow)
2. **Bypass diody w mismatch** - poprawiona logika aktywacji przy czesciowym zacienieniu
3. **Symetryczna sprawnosc baterii** - ladowanie i rozladowanie maja taka sama sprawnosc (sqrt roundtrip)
4. **URL encoding ULDK** - poprawione kodowanie znakow specjalnych w numerach dzialek
5. **Automatyczny czas letni CEST** - automatyczne wykrywanie CET/CEST zamiast stalego offsetu

### Ograniczenia:
- PVGIS wymaga dostepu do internetu (API Komisji Europejskiej)
- ULDK wymaga dostepu do internetu (geoportal.gov.pl)
- Brak walidacji STL (zaklada poprawny plik binarny)
- Ceny RCE z PSE (realne dane cache'owane w backend/data/rce_cache.json, z fallbackiem na dane syntetyczne)

---

## 9. Kontekst sesji (dla odtworzenia)

### Jak powstal ten projekt:
1. Uzytkownik mial wielogodzinna sesje w Kiro, w ktorej zaprojektowal i omowil caly symulator PV
2. Sesja crashowala - utracono cala rozmowe i postep
3. Uzytkownik zapisal 18 screenshotow (JPG) z fragmentami konwersacji
4. Nowa sesja odczytala screenshoty (OCR z EasyOCR) i zrekonstruowala wymagania
5. Na podstawie zrekonstruowanych wymagan zaimplementowano wszystkie 6 funkcjonalnosci
6. Kod przeszedl 3 iteracje code review (7 problemow znalezionych i naprawionych)
7. Wszystkie 243 testy przechodza

### Jak uzywac tego backupu:
Jesli rozpoczynasz nowa sesje i chcesz kontynuowac ten projekt, napisz:
> "Sprawdz repozytorium Symulator-PV, w folderze .kiro/backups/ jest backup sesji. Zapoznaj sie z nim i przyjmij projekt od tego miejsca."

Asystent powinien:
1. Przeczytac ten plik (.kiro/backups/SESSION-LOG.md)
2. Przeczytac plan projektu (.kiro/steering/project-plan.md)
3. Sprawdzic stan testow (python3 -m unittest discover -s backend/tests -p 'test_*.py')
4. Zapytac co robic dalej

---

## 10. Preferencje uzytkownika

- **Jezyk komunikacji:** polski
- **Jezyk kodu:** komentarze po polsku, nazwy zmiennych angielskie/polskie bez polskich znakow
- **Poziom szczegolowosci:** wysoki - uzytkownik chce rozumiec CO i DLACZEGO
- **Podejscie:** praktyczne, realistyczne (nie akademickie)
- **Frustracja:** utrata sesji byla bardzo frustrujaca - backup MUSI byc utrzymywany
- **Budzetowanie:** zero kosztow na narzedzia i serwisy
- **Kontekst:** mieszka w Polsce polnocnej (Energa), planuje realna instalacje PV

---

## 11. Historia zmian tego backupu

| Data | Co zmieniono |
|------|-------------|
| 2025-01-XX | Utworzenie backupu po odzyskaniu utraconej sesji. Stan: 6 funkcjonalnosci gotowych, 243 testy PASS, PR #2 otwarty. |
| 2025-08-06 | FEAT-001: Zmiana instalacji z wielu rzedow na jedna tafle (jedna plaszczyzna). Usuniete: odstep_miedzy_rzedami_cm, liczba_rzedow. 240 testow PASS. |
| 2025-08-06 | FEAT-002: Realne ceny RCE z API PSE (api.raporty.pse.pl/api/rce-pln). Cache 783 dni danych (2024-06-14 do 2026-08-05). Poprawiony model taryfowy: G11f teraz dynamiczna (cena RCE + nizsza dystrybucja), nie stala. Ceny moga byc ujemne. 250 testow PASS. |
| 2025-08-06 | KRYTYCZNE POPRAWKI (7 problemow z review): (1) Usunieto blad *24 w energy_profile.py - profil godzinowy pompy ciepla juz reprezentuje udzial godziny. (2) Dodano korekte POA (Plane of Array) w panel_performance.py - napromieniowanie przeliczane na nachylony panel. (3) Cien rzutowany na plaszczyzne paneli (przeswit nad gruntem), nie na y=0. (4) DoD baterii uwzgledniane w pojemnosci efektywnej (economics.py + battery_sizing.py). (5) Nowy test_energy_profile.py - 18 testow weryfikujacych poprawnosc sum rocznych. (6) Znormalizowano PROFIL_GODZINOWY_POMPY_CO i CWU do sumy 1.0. (7) Degradacja baterii w modelu ekonomicznym (2%/rok, wymiana po 12 latach, projekcja 25-letnia). 274 testy PASS. |
