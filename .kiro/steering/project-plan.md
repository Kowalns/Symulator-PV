# Plan Projektu - Symulator PV

## 1. Opis projektu i cel

Symulator PV to aplikacja webowa do kompleksowej symulacji instalacji fotowoltaicznej naziemnej (na stelazu gruntowym) dla domu jednorodzinnego. Projekt powstal z potrzeby precyzyjnego zaplanowania instalacji PV o mocy 2-14 kWp, z uwzglednieniem realnych warunkow: zacienienia przez budynek, profilu zuzycia energii z gruntowa pompa ciepla, taryf Energa oraz mozliwosci magazynowania energii.

### Glowne cele:
- Wizualizacja 3D budynku i planowanej instalacji PV na gruncie
- Symulacja zacienienia paneli przez budynek w rozdzielczosci godzinowej (8760 godzin/rok)
- Dokladne obliczenie produkcji energii z uwzglednieniem strat (temperatura, degradacja, cien, bypass diody)
- Analiza ekonomiczna z realnymi taryfami Energa i cenami RCE
- Dobor magazynu energii bez przewymiarowania
- Porownanie wielu scenariuszy instalacji side-by-side
- Optymalizacja pod samowystarczalnosc (szczegolnie w miesiacach jesiennych)

### Kluczowe zalozenia:
- Instalacja naziemna (stelaz gruntowy), NIE dachowa
- Rozmiar: 2-14 kWp
- Ogrzewanie: gruntowa pompa ciepla (wplywa na profil zuzycia)
- Lokalizacja: Polska, operator Energa
- Uzytkownik: poczatkujacy w programowaniu, PV i elektronice

---

## 2. Architektura

### Backend (serwer)
- **Jezyk:** Python 3.9+
- **Biblioteki:** TYLKO biblioteka standardowa (http.server, json, dataclasses, math, datetime)
- **Zero zaleznosci zewnetrznych** - brak pip install
- **Serwer:** http.server na porcie 8000
- **API:** REST-like endpointy (GET/POST), odpowiedzi JSON
- **Serwowanie frontendu:** wbudowane jako pliki statyczne

### Frontend (przegladarka)
- **HTML5 + CSS3 + JavaScript** (vanilla, bez frameworkow)
- **Three.js** z CDN (jsdelivr.net) - do wizualizacji 3D
- **Zero narzedzi budowania** - brak npm, webpack, itp.

### Zasada: ZERO KOSZTOW
- Brak platnych narzedzi, bibliotek, API
- PVGIS (darmowe, Komisja Europejska)
- ULDK (darmowe, geoportal.gov.pl)
- Three.js (open-source, CDN)

---

## 3. Etapy realizacji

### Etap 1: Widok 3D + STL + ULDK

**Cel:** Wizualizacja budynku i dzialki w przestrzeni 3D.

**Co realizuje:**
- Ladowanie modelu budynku z pliku STL (binarny format 3D)
- Scena Three.js z kamera, swiatlem, cieniami i OrbitControls
- Pobieranie granic dzialki z ULDK (Geoportal) po numerze katastralnym
- Reczne rysowanie granic dzialki (klikanie punktow na plaszczyznie)
- Proxy ULDK w backendzie (bo przegladarka nie moze bezposrednio odpytywac ULDK - CORS)

**Pliki:**
- `frontend/viewer.html` - strona widoku 3D
- `frontend/js/viewer3d.js` - inicjalizacja sceny Three.js
- `frontend/js/stl-loader.js` - parser binarnego formatu STL
- `frontend/js/parcel.js` - integracja ULDK i rysowanie granic
- `frontend/css/viewer.css` - style widoku 3D

---

### Etap 2: Baza paneli + konfiguracja instalacji

**Cel:** Wybor urzadzen i rozmieszczenie paneli na gruncie.

**Co realizuje:**
- Baza danych paneli PV (12 modeli) - najpopularniejsze na polskim rynku
- Baza falownikow (14 modeli) - kompatybilne z wybranymi panelami
- Baza magazynow energii (11 modeli) - dostepne w Polsce
- Kalkulator ukladu instalacji naziemnej:
  - Orientacja paneli: pion lub poziom
  - Kat nachylenia (dowolny, optymalizacja pod jesien)
  - Przeswit nad gruntem
  - Odstepy montazowe miedzy rzedami (unikanie samozacienienia)
  - Obliczanie liczby paneli dla zadanej mocy (2-14 kWp)
- Wizualizacja 3D rozmieszczonych paneli na scenie z budynkiem
- Panel konfiguracji w widoku 3D

**Pliki:**
- `backend/data/panels_database.json` - baza paneli
- `backend/data/inverters_database.json` - baza falownikow
- `backend/data/batteries_database.json` - baza magazynow
- `backend/services/installation_layout.py` - kalkulator rozmieszczenia
- `backend/models/installation.py` - modele danych instalacji
- `frontend/js/installation-config.js` - konfiguracja w przegladarce

---

### Etap 3: Symulacja zacienienia

**Cel:** Godzinowa symulacja cienia budynku na panelach przez caly rok.

**Co realizuje:**
- Algorytm pozycji slonca (azymut + elewacja) dla kazdej godziny roku
- Rzutowanie cienia budynku (z STL) na panele naziemne
- Dla kazdego panela: ktore sekcje (bypass diody) sa zacienione i w jakim stopniu
- Logika bypass diod: jesli sekcja zacieniona w >50% to bypass aktywowany (strata ~33% mocy panela)
- Technologia half-cut: panel dzielony na 2 polowki, kazda z wlasnym obwodem
- Optymalizatory mocy: mozliwosc dodania (tak jak w praktyce - na kazdy panel lub na zacienione)
- Wplyw temperatury na wydajnosc (wspolczynnik temperaturowy Pmax)
- Degradacja 0.5% rocznie
- Straty systemowe 2-5% (kable, konwersja, itp.)

**Pliki:**
- `backend/services/solar_position.py` - algorytm pozycji slonca
- `backend/services/shading.py` - symulacja zacienienia
- `backend/services/panel_performance.py` - wydajnosc paneli z uwzgl. cienia
- `backend/services/optimizer.py` - logika optymalizatorow mocy

---

### Etap 4: Profil zuzycia + taryfy + ekonomia

**Cel:** Analiza ekonomiczna instalacji z realnymi taryfami i profilem zuzycia.

**Co realizuje:**
- Profil zuzycia energii:
  - Obciazenie bazowe (standby, lodowka, itp.)
  - Przypisanie godzinowe urzadzen
  - Gruntowa pompa ciepla (stale zuzycie zimowe/przejsciowe)
- Taryfy Energa (ceny brutto z faktur 2024):
  - **G11** - stala cena calodobowo (1.14 zl/kWh calkowita)
  - **G11f** - wyzsza oplata stala, tansza dystrybucja (1.01 zl/kWh, oplacalna >5000 kWh/rok)
  - **Oferta dynamiczna** - cena godzinowa powiazana z RCE (gielda TGE)
- Ceny RCE:
  - Historyczne srednie godzinowe (profil cenowy)
  - Sprzedaz nadwyzki PV po cenie RCE z danej godziny
- Analiza godzinowa (8760 godzin):
  - Ile energii PV pokrywa zuzycie
  - Ile trafia do magazynu
  - Ile sprzedawane po RCE
  - Ile kupowane z sieci

**WAZNE - Arbitraz cenowy:**
Arbitraz cenowy (ladowanie magazynu z sieci w taniej godzinie i sprzedaz w drogiej) jest **NIEMOZLIWY** w Polsce. Magazyn moze byc ladowany **WYLACZNIE z instalacji PV** (nie z sieci!). Sprzedaz z magazynu mozliwa tylko dla energii, ktora weszla z PV.

**Pliki:**
- `backend/services/energy_profile.py` - profil zuzycia
- `backend/services/rce_prices.py` - ceny godzinowe RCE
- `backend/services/economics.py` - analiza ekonomiczna
- `backend/data/tariffs.json` - dane taryf
- `frontend/pages/energy-profile.html` - strona profilu zuzycia

---

### Etap 5: Raport + porownanie scenariuszy

**Cel:** Generowanie raportow i porownywanie roznych konfiguracji.

**Co realizuje:**
- Raport roczny i miesieczny:
  - Produkcja energii (kWh) z podzialem na miesiace
  - Straty na zacienieniu vs instalacja bez zacienienia
  - Stopien samowystarczalnosci w kazdym miesiacu
  - Zalecenia: zmiana pozycji, orientacji, kata nachylenia
- Dobor magazynu energii:
  - Analiza szczytowego zuzycia wieczornego
  - Dobor pojemnosci BEZ przewymiarowania
  - Ladowanie TYLKO z PV (nie z sieci!)
- Porownanie scenariuszy (14+ wariantow side-by-side):
  - Rozne moce instalacji
  - Rozne katy nachylenia
  - Z/bez magazynu energii
  - Z/bez optymalizatorow
  - Rozne taryfy

**Pliki:**
- `backend/services/report_generator.py` - generator raportow
- `backend/services/battery_sizing.py` - dobor magazynu
- `backend/services/scenario_comparison.py` - porownanie scenariuszy
- `frontend/pages/report.html` - strona raportu

---

## 4. Wymagania techniczne

| Wymaganie | Realizacja |
|-----------|-----------|
| Zero kosztow | Python stdlib, CDN Three.js, darmowe API |
| Brak zaleznosci Python | Tylko biblioteka standardowa |
| Brak narzedzi budowania | Vanilla JS, brak npm/webpack |
| Przegladarka | Dowolna nowoczesna (Chrome/Firefox/Edge) |
| Python | Wersja 3.9+ |
| Serwer | http.server na localhost:8000 |
| 3D | Three.js z CDN (jsdelivr.net) |
| Dane pogodowe | PVGIS (Komisja Europejska, darmowe) |
| Mapy/dzialki | ULDK (geoportal.gov.pl, darmowe) |

---

## 5. Wymagania merytoryczne (fizyka PV)

### 5.1 Bypass diody
- Kazdy panel ma 3 sekcje bypass diod (typowo)
- Jesli cien pokrywa sekcje w **wiecej niz 50%** - dioda bypass aktywowana
- Aktywacja bypass = strata ~33% mocy panela (1/3 panela wylaczona)
- Panel z 3 sekcjami: 0, 1, 2 lub 3 sekcje moga byc w bypass

### 5.2 Technologia half-cut
- Panel podzielony na 2 niezalezne polowki (gora/dol)
- Kazda polowka ma wlasny obwod - zacienienie jednej nie wplywa na druga
- Zmniejsza straty na czesciowym zacienieniu
- Uwzglednione w bazie paneli (pole `technologia: "half-cut"`)

### 5.3 Optymalizatory mocy
- Mozliwosc dodania na kazdy panel lub tylko na zacienione
- W praktyce montuje sie na panelach, ktore sa zacieniane
- Optymalizator pozwala zacienionemu panelowi pracowac niezaleznie od reszty stringu
- Nie dodaje mocy - minimalizuje straty wynikajace z roznic miedzy panelami
- Wymaga kompatybilnego falownika (np. Huawei z SUN2000-xxx)

### 5.4 Temperatura
- Wspolczynnik temperaturowy Pmax (typowo -0.35%/stopien C)
- Temperatura panela = temperatura otoczenia + naslonecznienie * wspolczynnik NOCT
- Latem panele moga tracic 10-15% mocy z powodu nagrzania

### 5.5 Degradacja
- **0.5% rocznie** spadek mocy (starzenie sie ogniw)
- Gwarancja producenta: typowo 80% mocy po 25 latach
- W symulacji: kazdy rok kolejny = 0.5% mniej mocy

### 5.6 Straty systemowe
- **2-5%** strat na: kablach, polaczeniach, konwersji DC/AC, brudzie na panelach
- Konfigurowalne przez uzytkownika

---

## 6. Taryfy Energa

### G11 - Taryfa jednastrefowa
- Stala cena calodobowo
- Energia czynna: 0.6172 zl/kWh
- Dystrybucja zmienna: 0.3485 zl/kWh
- **Calkowita cena: ~1.14 zl/kWh** (brutto z VAT)
- Oplaty stale: ~21 zl/mc
- Najprostsza, najpopularniejsza

### G11f - Dla duzych odbiorcow
- Wyzsza oplata stala miesieczna (~73 zl/mc)
- Nizsza dystrybucja zmienna: 0.2180 zl/kWh
- **Calkowita cena: ~1.01 zl/kWh** (brutto z VAT)
- Oplacalna przy zuzyciu >5000 kWh/rok (np. z pompa ciepla)

### Oferta dynamiczna
- Cena energii zmienia sie co godzine
- Powiazana z cena gieldowa RCE (TGE - Towarowa Gielda Energii)
- Narzut sprzedawcy: 0.04 zl/kWh
- Nadwyzka z PV sprzedawana po cenie RCE z danej godziny
- Latem w poludnie ceny najnizsze (duzo PV w systemie)
- Oplaty stale: ~28 zl/mc

### Sprzedaz nadwyzki
- Nadwyzka PV sprzedawana po cenach RCE z danej godziny generacji
- Ceny RCE wahaja sie: 0.10-0.80 zl/kWh (srednia ~0.35 zl/kWh)
- W godzinach szczytu PV (11:00-14:00) ceny czesto najnizsze

---

## 7. Magazyn energii

### Zasady:
- **Ladowanie WYLACZNIE z PV** (nie z sieci!)
- Arbitraz cenowy jest **NIEMOZLIWY** w Polsce
- Nie mozna kupic taniej energii z sieci i sprzedac drozej
- Mozna przechowac energie z PV na wieczor (autokonsumpcja)

### Dobor pojemnosci:
- Analiza szczytu wieczornego zuzycia (17:00-23:00)
- Dobor BEZ przewymiarowania - magazyn nie wiekszy niz potrzebny
- Uwzglednienie sprawnosci roundtrip (~95%)
- Uwzglednienie DoD (glebia rozladowania) - typowo 90-96%

### Dostepne modele (w bazie):
- BYD Battery-Box (HVS/HVM) - 5-22 kWh
- Huawei LUNA2000 - 5-15 kWh modularnie
- SolarEdge Home Battery - 4.6-9.2 kWh
- Pylontech US5000 - 4.8 kWh (skalowalne)

---

## 8. Gruntowa pompa ciepla

### Wplyw na profil zuzycia:
- Stale zuzycie energii na ogrzewanie (zima: pazdziernik-kwiecien)
- Typowe zuzycie: 3000-6000 kWh/rok na ogrzewanie
- Profil calodobowy (pompa pracuje rownomiernie)
- COP 4.0-5.0 (z 1 kWh pradu robi 4-5 kWh ciepla)

### Wplyw na dobor instalacji:
- Wieksze roczne zuzycie = wieksza instalacja
- Taryfa G11f bardziej oplacalna (zuzycie >5000 kWh/rok)
- Samowystarczalnosc zimowa trudna - male naslonecznienie

---

## 9. Porownanie scenariuszy

### Parametry do porownania:
- Moc instalacji (2-14 kWp, w krokach)
- Kat nachylenia (20-60 stopni)
- Orientacja (poludnie, poludniowy-wschod, poludniowy-zachod)
- Taryfa (G11, G11f, dynamiczna)
- Magazyn energii (bez, 5 kWh, 10 kWh, itp.)
- Optymalizatory (z/bez)

### Metryki porownawcze:
- Roczna produkcja (kWh)
- Autokonsumpcja (%)
- Samowystarczalnosc (%) per miesiac
- Oszczednosc roczna (zl)
- Zwrot inwestycji (lata)
- Nadwyzka sprzedana (kWh, zl)

### Cel: 14+ scenariuszy wyswietlanych obok siebie
- Tabela porownawcza
- Wyroznienie najlepszego scenariusza dla danej metryki

---

## 10. Instalacja naziemna - parametry

### Stelaz gruntowy:
- Panele montowane na stelazu na gruncie (NIE na dachu)
- Pozycja wzgledem budynku okresla zacienienie
- Kat nachylenia: konfigurowalny (optymalizacja pod jesien = wiekszy kat)
- Orientacja: typowo poludnie, ale mozna dostosowac

### Parametry konfiguracyjne:
- Producent i model panela (z bazy)
- Orientacja panela: pion (portrait) lub poziom (landscape)
- Kat nachylenia (stopnie)
- Przeswit nad gruntem (cm)
- Odstepy montazowe miedzy rzedami (zapobiega samozacienieniu)
- Pozycja instalacji wzgledem budynku (x, y na plaszczyznie)
- Azymut instalacji (kierunek)

### Samozacienienie miedzy rzedami:
- Obliczane na podstawie kata nachylenia, wysokosci panela i pozycji slonca
- Minimalne odstepy wynikaja z najnizszej pozycji slonca zimowego (21 grudnia)

---

## 11. Konwencje i zasady projektu

### Jezyk:
- Wszystkie komentarze w kodzie: **po polsku**
- Cala dokumentacja: **po polsku**
- Nazwy zmiennych w kodzie: angielskie lub polskie (bez polskich znakow)
- Komunikaty w UI: po polsku

### Styl kodu:
- Backend: Python, dataclasses, typowanie, docstringi po polsku
- Frontend: vanilla JS, klasy CSS w BEM-like, komentarze po polsku
- Testy: unittest, nazwy testow opisowe po polsku

### Pliki:
- Struktura: backend/ (api, services, models, tests, data), frontend/ (html, js, css, pages)
- Bazy danych: JSON w backend/data/
- Brak bazy danych SQL - wszystko w plikach

---

## 12. Decyzje projektowe (z utraconej sesji)

1. Panele najpopularniejsze na polskim rynku (JA Solar, Jinko, Trina, Canadian Solar, itp.)
2. Instalacja 2-14 kWp na stelazu naziemnym
3. Bypass diody: >50% zacienienia sekcji = bypass aktywowany (~33% straty panela)
4. G11 = stala cena, G11f = wyzsza oplata stala ale tansza dystrybucja. Ceny brutto z faktur.
5. Sprzedaz nadwyzki po cenach RCE (w godzinach generacji, nie srednia roczna)
6. Samowystarczalnosc - kat nachylenia optymalizowany pod jesien (wiekszy kat = lepiej jesienia)
7. Arbitraz cenowy - **NIEMOZLIWY** w Polsce (regulacje prawne)
8. Degradacja 0.5%/rok, wplyw temperatury, straty systemowe 2-5%
9. Porownanie scenariuszy: minimum 14 wariantow side-by-side
10. Magazyn energii - dobor bez przewymiarowania, ladowanie TYLKO z PV
11. Ogrzewanie gruntowa pompa ciepla (duze zuzycie zimowe)
12. Komentarze i dokumentacja po polsku
13. Zero kosztow na narzedzia i biblioteki (stdlib + CDN)
