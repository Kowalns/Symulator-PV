# Backup sesji - Symulator PV

> **Data ostatniej aktualizacji:** 2026-08-13 (sesja bieżąca - dodany Krok 4: Wizualizacja cienia)
> **Branch:** `main` (PR #2 zmergowany)
> **Testy:** 413 PASS (`python3 -m unittest discover -s backend/tests -p 'test_*.py'`)
> **Uruchomienie:** `python3 backend/main.py` → http://localhost:8000

---

## 1. Dane użytkownika

- **Lokalizacja:** Chojęcin-Szum (51.28°N, 17.95°E), woj. wielkopolskie, powiat kępiński
- **Działka:** 300802_2.0002.598/32 (5-bokowa, pobrana z ULDK)
- **Dom:** Model STL w kształcie litery T, plik w mm (18680×19830×6230 = 18.7×19.8×6.2 m), oś Z-up
- **Pompa ciepła:** NIBE F1245 8kW (gruntowa), COP ~4.0, moc elektr. ~2.0 kW
- **Zużycie szacowane:** CO ~3500 kWh/rok, CWU ~1200 kWh/rok, bazowe ~250W, łącznie ~7000 kWh/rok
- **Operator:** Energa, taryfa: G11f + Oferta dynamiczna II dla domu
- **Użytkownik:** Nie jest programistą, korzysta z GitHub Codespaces (przeglądarka), NIE instaluje nic na komputerze

---

## 2. Kluczowe decyzje (NIEZMIENNE)

| # | Decyzja | Uzasadnienie |
|---|---------|--------------|
| 1 | Zero zależności Python (stdlib only), Three.js z CDN | Prostota, zero kosztów |
| 2 | Komentarze i UI po polsku | Użytkownik nie zna angielskiego technicznego |
| 3 | Arbitraż cenowy NIEMOŻLIWY | Polskie regulacje - magazyn z sieci = tylko autokonsumpcja |
| 4 | G11f WYMAGA umowy dynamicznej | Nie jest osobną taryfą ze stałą ceną |
| 5 | Bypass diody: próg 15% | Realny próg aktywacji (nie 50%) |
| 6 | Ceny brutto (z VAT 23%) | Jak na fakturze |
| 7 | Energia z sieci w magazynie NIE może być sprzedawana | Anti-arbitraż, source tracking PV/grid |
| 8 | Ujemne ceny RCE: prosument PŁACI za iniekcję | Realistyczne, bez clamp do 0 |
| 9 | Net-billing: 80% niewykorzystanego depozytu przepada po 12 mc | Polskie przepisy |
| 10 | Instalacja = jedna tafla paneli (nie rzędy) | Wymaganie użytkownika |
| 11 | Cień blokuje TYLKO beam (nie diffuse) | Fizyka - rozproszone dociera niezależnie |
| 12 | Magazyn ładowany z sieci w najtańszych godzinach (fallback) | Optymalizacja dla taryf dynamicznych |
| 13 | Pompa ciepła pracuje w najtańszych godzinach | Optymalizacja dla taryf dynamicznych |

---

## 3. Chronologia prac w tej sesji

1. Odtworzenie utraconej pracy z crashniętej sesji (OCR 18 screenshotów, implementacja 6 FEAT)
2. System backupów (.kiro/backups/ + .kiro/steering/backup-protocol.md)
3. Poprawka: instalacja = jedna tafla (nie wiele rzędów z odstępami)
4. Realne ceny RCE z PSE API (783 dni cache), G11f jako taryfa dynamiczna
5. Taryfy z oficjalnych PDF Energa 2026 (G11f dystrybucja 0.0516, WK 0.1080 brutto, mocowa ryczałt)
6. Inteligentne ładowanie magazynu (grid fallback w najtańszych godzinach)
7. Optymalizacja pompy ciepła (koncentracja poboru w najtańszych godzinach RCE)
8. Usunięcie degradacji/projekcji 25-letniej (nie było w wymaganiach użytkownika)
9. Integracja frontendu (3-krokowy wizard: viewer → profil → raport)
10. Krytyczna ocena (7 bugów: pompa 24x, POA, cień na panel, DoD, testy, normalizacja, NOCT)
11. Panel 6 ekspertów (33 zastrzeżenia)
12. TMY z PVGIS API (beam/diffuse/ground POA, realne dane 8760h)
13. Etap B: model stringa, net-billing depozyt, bypass 15%, sprawność falownika, bifacial, marża
14. Bezlitosny review (11 bugów naprawionych)
15. Finalny expert review (5 bugów naprawionych: bypass zero, beam/electrical, ujemny depozyt)
16. Poprawki STL: mm→metry, Z-up→Y-up, przyciski obrotu, suwak azymutu
17. Domyślne dane użytkownika w formularzu (lokalizacja, działka, wymiary)
18. Fix SyntaxError (podwójny nawias })
19. Drag & drop: przeciąganie domu i paneli myszką na scenie 3D
20. Fix: obrót azymutu na Group (nie podnosi boku domu) - korekcja Z-up na meshu, azymut na grupie
21. Panele w rzędach i kolumnach (pole liczba_rzedow, backend + frontend)
22. Nowy design "Solar Pro" - ciemny motyw, złote/amber akcenty, glassmorphism, glow efekty
23. Rzędy paneli = jeden nad drugim na tym samym stelażu (nie osobne rzędy w głąb)
24. Fix: raport czytelnosc (inline styles -> dark theme), straty zacienienia zmienne per miesiac (wiecej zima, mniej latem), porownanie scenariuszy (uproszczenie), eksport CSV (separator srednik, UTF-8 BOM)
25. Fix: straty zacienienia per miesiac z PRAWDZIWEJ symulacji 8760h (usunieto zmyslone wspolczynniki sezonowe, backend zwraca energia_bez_zacienienia_miesieczna_kwh, frontend uzywa prawdziwych danych)
26. Podglad zacienienia w wybranej godzinie - nowy endpoint POST /api/shading/single-hour + wizualizacja paneli w report.html (siatka kolorowych prostokatow wg stopnia zacienienia, pozycja slonca, produkcja z/bez cienia)
27. Fix: localStorage persistence we wszystkich krokach, domyslne wartosci uzytkownika (10 paneli, 2 rzedy, 40 deg, pompa 8kW, CO 3000, CWU 1000, magazyn 16kWh, godzina sprzedazy 23), budynek pozycja z=-20 (naprawia 56% stale zacienienie - panele byly wewnatrz footprintu budynku), report.html czyta lokalizacje z instalacja_config fallback, ostrzezenie jesli straty zacienienia > 40%
28. Pozycjonowanie domu i paneli jako odleglosc od granic dzialki (pd i ws) - nowy interfejs: odleglosc od granicy poludniowej/wschodniej zamiast abstrakcyjnych X/Z, automatyczne przeliczanie na pozycje srodka (hidden inputs bud-x/bud-z/panel-pos-x/panel-pos-z zachowane dla backendu), wyswietlanie odleglosci NE naroznik domu do SW naroznik paneli, fallback na stare pola X/Z jesli brak danych ULDK, parcel.js zapisuje wierzcholki do localStorage (klucz 'parcel_vertices')
29. Krok 4: Wizualizacja cienia (shadow-animation.html) - nowa strona z animacja wedrowki cienia po dzialce. Layout 60%/40%: lewa strona widok 3D z gory (Three.js, cien budynku na ziemie, kompas, wskaznik slonca), prawa strona diagram paneli z kolorami wydajnosci (niebieski/zolty/pomaranczowy/czerwony). Kontrolki: data, play/pauza, slider 5:00-21:00 co 15 min, predkosc 1x/2x/5x/10x. Nowy endpoint GET /api/solar-position?lat&lon&rok&miesiac&dzien&godzina&minuta. Animacja setTimeout-chaining (nie setInterval) z cache zacienienia per godzina, error indicator po 2+ bledach. 13 nowych testow. Nawigacja w report.html -> shadow-animation.html.

---

## 4. Aktualna architektura

```
Symulator-PV/
├── backend/
│   ├── main.py                          # Serwer HTTP port 8000
│   ├── api/handlers.py                  # REST API handlers
│   ├── services/
│   │   ├── pvgis.py                     # TMY z PVGIS API + file cache
│   │   ├── panel_performance.py         # POA beam/diffuse/ground, NOCT, bifacial, falownik
│   │   ├── economics.py                 # Bilans godzinowy, magazyn PV/grid tracking, net-billing
│   │   ├── optimizer.py                 # Model stringa, mismatch, bypass, podział na stringi
│   │   ├── shading.py                   # Cień budynku (convex hull + Sutherland-Hodgman)
│   │   ├── energy_profile.py            # Profil zużycia, pompa ciepła, optymalizacja cenowa
│   │   ├── rce_prices.py                # Ceny RCE z PSE (783 dni cache)
│   │   ├── battery_sizing.py            # Dobór magazynu
│   │   ├── scenario_comparison.py       # Porównanie 14+ scenariuszy
│   │   ├── report_generator.py          # Generator raportów
│   │   ├── solar_position.py            # Pozycja słońca (azymut + elewacja)
│   │   └── installation_layout.py       # Rozmieszczenie paneli (jedna tafla)
│   ├── data/
│   │   ├── tariffs.json                 # G11, G11f_dynamiczna, G11_dynamiczna
│   │   ├── panels_database.json         # 15 paneli (w tym 3 bifacial)
│   │   ├── inverters_database.json      # 14 falowników
│   │   ├── batteries_database.json      # 11 magazynów
│   │   ├── rce_cache.json               # 783 dni cen RCE z PSE
│   │   └── tmy_cache/                   # Cache danych TMY z PVGIS
│   └── tests/                           # 413 testów
├── frontend/
│   ├── index.html                       # Strona główna (nawigacja 3 kroki)
│   ├── viewer.html                      # Krok 1: 3D + konfiguracja
│   ├── pages/energy-profile.html        # Krok 2: profil zużycia + taryfa
│   ├── pages/report.html                # Krok 3: raport + scenariusze
│   ├── pages/shadow-animation.html      # Krok 4: wizualizacja cienia (animacja)
│   ├── js/viewer3d.js                   # Three.js scena + drag&drop
│   ├── js/stl-loader.js                 # STL loader (mm→m, Z-up→Y-up, obrót)
│   ├── js/parcel.js                     # ULDK + rysowanie granic
│   ├── js/installation-config.js        # Konfiguracja instalacji PV
│   └── css/                             # Style
├── .kiro/
│   ├── backups/SESSION-LOG.md           # TEN PLIK
│   └── steering/
│       ├── project-plan.md              # Plan projektu
│       └── backup-protocol.md           # Protokół backupów
├── Dom.STL                              # Model 3D domu (T-kształt, mm)
├── Energa.zip                           # Faktury i taryfy (PDF)
└── README.md
```

---

## 5. API Endpointy

| Metoda | Endpoint | Opis |
|--------|----------|------|
| GET | /api/health | Status serwera |
| GET | /api/panels | Baza paneli PV (15 modeli) |
| GET | /api/inverters | Baza falowników |
| GET | /api/batteries | Baza magazynów |
| GET | /api/tariffs | Taryfy Energa + statystyki RCE |
| GET | /api/uldk?... | Proxy geoportal (granice działek) |
| POST | /api/tmy/fetch | Pobierz dane TMY z PVGIS |
| POST | /api/simulate | Symulacja podstawowa |
| POST | /api/installation/configure | Konfiguracja rozmieszczenia |
| POST | /api/shading/simulate | Symulacja zacienienia (8760h) |
| POST | /api/shading/single-hour | Podglad zacienienia (jedna godzina) |
| POST | /api/energy-profile | Profil zużycia |
| POST | /api/economics/analyze | Analiza ekonomiczna |
| POST | /api/report/generate | Raport roczny/miesięczny |
| POST | /api/scenarios/compare | Porównanie scenariuszy |
| GET | /api/solar-position?... | Pozycja słońca (azymut + elewacja) dla daty/czasu/lokalizacji |

---

## 6. Taryfy (oficjalne Energa 2026, brutto)

### G11 (stała):
- Energia: 0.6172 zł/kWh
- Dystrybucja: 0.4287 zł/kWh (0.3485 netto)
- Łącznie ~1.10 zł/kWh + opłaty stałe

### G11f + dynamiczna (scenariusz użytkownika):
- Energia: CTGE (cena TGE RDN) + WK 0.1080 brutto
- Dystrybucja: 0.0635 zł/kWh brutto (0.0516 netto)
- Opłata stała sieciowa: 55.51 zł/mc (3-faz)
- Opłata handlowa: 9.99 zł/mc (eFaktura)
- Opłata mocowa: 29.58 zł/mc (ryczałt >2800 kWh/rok)
- Cena sprzedaży nadwyżki: RCE_netto - marża (domyślnie 0.03 zł/kWh)

---

## 7. Co jest aktualnie robione / następne kroki

- Użytkownik testuje aplikację w GitHub Codespaces
- Design "Solar Pro" właśnie wdrożony (ciemny motyw, złote akcenty)
- Drag & drop domu i paneli działa
- Panele mogą być ułożone w rzędy × kolumny
- Obrót budynku (azymut) działa poprawnie
- Następny krok: użytkownik testuje z prawdziwymi danymi, poprawki UX wg feedbacku

---

## 8. Znane ograniczenia (do ewentualnej implementacji w przyszłości)

- Brak IAM (straty odbicia na szkle przy dużych kątach padania) - 2-4% wpływ
- Brak LID (Light Induced Degradation, rok 1: 2%) - 1.5-2% wpływ
- Brak modelu śniegu - 3-8% wpływ zimą
- Model stringa zakłada liniowy wzorzec cienia
- Net-billing: koniec roku kalendarzowego (uproszczenie vs rolling 12mc)
- CWU sezonowość uproszczona (mnożnik, nie fizyczny model)

---

## 9. Jak wznowić pracę w nowym czacie

Napisz: "Sprawdź repozytorium Symulator-PV, w folderze .kiro/backups/ jest backup sesji. Zapoznaj się z nim i przyjmij projekt od tego miejsca."

Asystent powinien:
1. Przeczytać .kiro/backups/SESSION-LOG.md (ten plik)
2. Przeczytać .kiro/steering/project-plan.md
3. Sprawdzić testy: python3 -m unittest discover -s backend/tests -p 'test_*.py'
4. Zapytać co robić dalej
