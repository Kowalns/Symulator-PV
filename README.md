# Symulator PV - Kalkulator produkcji energii z paneli slonecznych

## Co to jest?

Symulator PV to aplikacja webowa (strona internetowa), ktora pozwala obliczyc ile energii elektrycznej (pradu) wyprodukuja panele sloneczne (fotowoltaiczne) w danej lokalizacji.

**Jak to dziala w skrocie:**
1. Podajesz lokalizacje (miasto lub wspolrzedne geograficzne)
2. Podajesz parametry instalacji (moc paneli, kat nachylenia)
3. Aplikacja oblicza ile kWh pradu rocznie wyprodukuja Twoje panele

## Slowniczek (dla poczatkujacych)

- **PV (fotowoltaika)** - technologia zamieniania swiatla slonecznego na prad elektryczny
- **kW (kilowat)** - jednostka mocy. Typowa instalacja domowa ma 3-10 kW
- **kWh (kilowatogodzina)** - jednostka energii. Tyle pradu zuzywa np. czajnik w 1 godzine
- **Irradiacja** - ile energii slonecznej pada na dany teren (mierzone w kWh/m2 na rok)
- **Azymut** - kierunek w ktory patrza panele (poludnie = 0, zachod = 90)
- **Kat nachylenia** - jak bardzo panele sa pochylone. Optymalne: 30-40 stopni
- **PVGIS** - darmowa baza danych Komisji Europejskiej z danymi o sloncu w Europie

## Jak uruchomic?

### Wymagania
- Python 3.7 lub nowszy (wpisz `python3 --version` w terminalu zeby sprawdzic)
- Przegladarka internetowa (Chrome, Firefox, Edge itp.)

### Uruchomienie

1. Otwierasz terminal (wiersz polecen)
2. Przechodzisz do katalogu projektu:
   ```bash
   cd sciezka/do/Symulator-PV
   ```
3. Uruchamiasz serwer:
   ```bash
   python3 backend/main.py
   ```
4. Otwierasz przegladarke i wchodzisz na: http://localhost:8000

To wszystko! Aplikacja powinna dzialac.

### Zatrzymanie serwera
Nacisnij `Ctrl+C` w terminalu.

## Architektura (jak to jest zbudowane)

```
Symulator-PV/
├── backend/                 # Czesc serwerowa (Python)
│   ├── main.py             # Glowny plik - uruchamia serwer
│   ├── api/                # Obsluga zapytan HTTP
│   │   └── handlers.py    # Funkcje obslugujace endpointy API
│   ├── services/           # Logika biznesowa
│   │   ├── pvgis.py       # Pobieranie danych z PVGIS
│   │   └── calculator.py  # Obliczenia produkcji energii
│   ├── models/             # Modele danych
│   │   └── simulation.py  # Struktury danych (wejscie/wyjscie)
│   └── tests/              # Testy automatyczne
│       ├── test_calculator.py
│       ├── test_handlers.py
│       └── test_parcel.py  # Testy modulu granic dzialki
├── frontend/               # Czesc kliencka (przegladarka)
│   ├── index.html         # Strona glowna (symulacja PV)
│   ├── viewer.html        # Widok 3D - model budynku i granice dzialki
│   ├── css/
│   │   ├── style.css      # Styl glowny
│   │   └── viewer.css     # Styl widoku 3D
│   └── js/
│       ├── app.js          # Logika interfejsu symulatora
│       ├── viewer3d.js     # Inicjalizacja sceny Three.js
│       ├── stl-loader.js   # Ladowanie plikow STL
│       └── parcel.js       # Granice dzialki (ULDK + reczne rysowanie)
├── README.md              # Ten plik - opis projektu
└── .gitignore             # Lista plikow ignorowanych przez git
```

### Jak to dziala?

1. **Frontend** (przegladarka) - wyswietla formularz, zbiera dane od uzytkownika
2. Uzytkownik klika "Oblicz" - frontend wysyla dane do backendu przez API
3. **Backend** (serwer Python) - odbiera dane, wykonuje obliczenia
4. Backend probuje pobrac dane z **PVGIS** (dokladne dane europejskie)
5. Jesli PVGIS jest niedostepny, uzywa **obliczen uproszczonych** (fallback)
6. Backend odsyla wynik do frontendu
7. Frontend wyswietla wynik: roczna produkcja + wykres miesieczny

### Widok 3D (viewer.html)

Osobna strona z wizualizacja 3D, ktora pozwala:

1. **Zaladowac model budynku (STL)** - plik STL to popularny format modeli 3D.
   Model jest automatycznie centrowany i skalowany w scenie.
2. **Pobrac granice dzialki z geoportalu ULDK** - wpisujesz numer dzialki katastralnej,
   a aplikacja pobiera jej ksztalt z darmowego serwisu rzadowego i rysuje go w scenie 3D.
3. **Narysowac granice recznie** - jesli nie znasz numeru dzialki, mozesz recznie
   kliknac punkty na plasczyznie zeby zaznaczyc granice.

Scena 3D jest oparta na bibliotece Three.js (ladowana z CDN, nie wymaga instalacji).

## API Endpoints

- `GET /api/health` - sprawdzenie czy serwer dziala
- `POST /api/simulate` - przeprowadzenie symulacji PV

### Przyklad zapytania do API:
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

## Uruchomienie testow

```bash
python3 -m unittest discover -s backend/tests -p 'test_*.py' -v
```

## Plan rozwoju

- [x] Szkielet aplikacji (MVP - minimum viable product)
- [x] Import modelu 3D budynku (STL) - wizualizacja w Three.js
- [x] Pobieranie granic dzialki z geoportalu ULDK (kataster)
- [x] Reczne rysowanie granic dzialki w scenie 3D
- [ ] Integracja z Open-Meteo jako alternatywne zrodlo danych pogodowych
- [ ] Symulacja godzinowa (zamiast rocznej)
- [ ] Baza danych paneli i falownikow z ich parametrami
- [ ] Analiza ekonomiczna (zwrot inwestycji, oszczednosci)
- [ ] Eksport raportu PDF

## Technologie

- **Backend:** Python 3 (biblioteka standardowa - http.server, json, dataclasses)
- **Frontend:** HTML5, CSS3, JavaScript (vanilla - bez frameworkow)
- **Dane:** PVGIS API (Komisja Europejska) + obliczenia wlasne jako fallback
- **Geokodowanie:** Nominatim/OpenStreetMap (darmowe)

## Licencja

Projekt open-source. Darmowy do uzytku.
