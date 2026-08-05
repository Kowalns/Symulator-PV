/**
 * Symulator PV - Logika frontendowa
 * 
 * Ten plik obsluguje interakcje uzytkownika na stronie:
 * 1. Formularz - zbieranie danych od uzytkownika
 * 2. Geokodowanie - zamiana nazwy miasta na wspolrzedne
 * 3. Komunikacja z API - wysylanie danych do backendu
 * 4. Wyswietlanie wynikow - pokazywanie rezultatow symulacji
 */

// Adres bazowy API (ten sam serwer)
const API_BASE = '';

// ============================================
// INICJALIZACJA - uruchamia sie po zaladowaniu strony
// ============================================

document.addEventListener('DOMContentLoaded', function() {
    // Pobieramy referencje do elementow HTML
    const form = document.getElementById('simulation-form');
    const searchBtn = document.getElementById('search-btn');
    const citySearch = document.getElementById('city-search');

    // Obsluga wyslania formularza
    form.addEventListener('submit', function(event) {
        event.preventDefault(); // Zapobiegamy przeladowaniu strony
        runSimulation();
    });

    // Obsluga przycisku szukania miasta
    searchBtn.addEventListener('click', function() {
        searchCity();
    });

    // Obsluga klawisza Enter w polu szukania
    citySearch.addEventListener('keypress', function(event) {
        if (event.key === 'Enter') {
            event.preventDefault();
            searchCity();
        }
    });
});

// ============================================
// GEOKODOWANIE - zamiana nazwy miasta na wspolrzedne
// ============================================

/**
 * Szuka miasta po nazwie uzywajac darmowego API Nominatim (OpenStreetMap).
 * Nominatim zamienia nazwe miejsca na wspolrzedne geograficzne.
 */
async function searchCity() {
    const cityInput = document.getElementById('city-search');
    const resultsDiv = document.getElementById('search-results');
    const query = cityInput.value.trim();

    if (!query) {
        alert('Wpisz nazwe miasta');
        return;
    }

    resultsDiv.classList.remove('hidden');
    resultsDiv.innerHTML = '<div class="search-result-item">Szukam...</div>';

    try {
        // Wywolanie API Nominatim (darmowe, limit 1 zapytanie/sek)
        const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5`;
        const response = await fetch(url, {
            headers: { 'Accept-Language': 'pl' }
        });

        if (!response.ok) {
            throw new Error('Blad polaczenia z serwisem geokodowania');
        }

        const results = await response.json();

        if (results.length === 0) {
            resultsDiv.innerHTML = '<div class="search-result-item">Nie znaleziono takiego miejsca</div>';
            return;
        }

        // Wyswietlenie wynikow
        resultsDiv.innerHTML = '';
        results.forEach(function(place) {
            const item = document.createElement('div');
            item.className = 'search-result-item';
            item.textContent = place.display_name;
            item.addEventListener('click', function() {
                // Ustawienie wspolrzednych w formularzu
                document.getElementById('latitude').value = parseFloat(place.lat).toFixed(4);
                document.getElementById('longitude').value = parseFloat(place.lon).toFixed(4);
                cityInput.value = place.display_name.split(',')[0];
                resultsDiv.classList.add('hidden');
            });
            resultsDiv.appendChild(item);
        });
    } catch (error) {
        resultsDiv.innerHTML = '<div class="search-result-item">Blad wyszukiwania. Wpisz wspolrzedne recznie.</div>';
        console.error('Blad geokodowania:', error);
    }
}

// ============================================
// SYMULACJA - wysylanie danych i odbieranie wynikow
// ============================================

/**
 * Przeprowadza symulacje - zbiera dane z formularza,
 * wysyla do backendu i wyswietla wyniki.
 */
async function runSimulation() {
    // Ukryj poprzednie wyniki i bledy
    hideElement('results-section');
    hideElement('error-section');
    showElement('loading-section');

    // Zablokuj przycisk na czas obliczen
    const submitBtn = document.getElementById('calculate-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Obliczam...';

    // Zbieranie danych z formularza
    const data = {
        latitude: parseFloat(document.getElementById('latitude').value),
        longitude: parseFloat(document.getElementById('longitude').value),
        peak_power_kw: parseFloat(document.getElementById('peak-power').value),
        tilt_angle: parseFloat(document.getElementById('tilt-angle').value),
        azimuth_angle: parseFloat(document.getElementById('azimuth').value),
        system_loss_percent: parseFloat(document.getElementById('system-loss').value),
        location_name: document.getElementById('city-search').value || null,
    };

    try {
        // Wysylanie danych do API backendu
        const response = await fetch(API_BASE + '/api/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.message || 'Blad serwera');
        }

        // Wyswietlenie wynikow
        displayResults(result);

    } catch (error) {
        showError(error.message || 'Nie udalo sie polaczyc z serwerem. Sprawdz czy serwer dziala.');
    } finally {
        // Odblokuj przycisk
        hideElement('loading-section');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Oblicz produkcje energii';
    }
}

// ============================================
// WYSWIETLANIE WYNIKOW
// ============================================

/**
 * Wyswietla wyniki symulacji na stronie.
 */
function displayResults(result) {
    // Glowny wynik - roczna produkcja
    document.getElementById('annual-energy').textContent =
        Math.round(result.annual_energy_kwh).toLocaleString('pl-PL');

    // Opis wyniku
    const description = getResultDescription(result.annual_energy_kwh, result.peak_power_kw);
    document.getElementById('result-description').textContent = description;

    // Szczegoly
    document.getElementById('detail-power').textContent = result.peak_power_kw + ' kW';
    document.getElementById('detail-irradiation').textContent =
        Math.round(result.irradiation_kwh_m2) + ' kWh/m\u00B2/rok';

    const sourceText = result.data_source === 'pvgis'
        ? 'PVGIS (dokladne dane europejskie)'
        : 'Obliczenia uproszczone (srednie dane)';
    document.getElementById('detail-source').textContent = sourceText;

    // Wykres miesieczny
    renderMonthlyChart(result.monthly_energy_kwh);

    // Pokaz sekcje wynikow
    showElement('results-section');

    // Przewin do wynikow
    document.getElementById('results-section').scrollIntoView({ behavior: 'smooth' });
}

/**
 * Generuje opis wyniku w zrozumialym jezyku.
 */
function getResultDescription(annualKwh, peakPower) {
    // Srednie zuzycie gospodarstwa domowego w Polsce to ok. 2500-3500 kWh/rok
    const avgHousehold = 3000;
    const percentage = Math.round((annualKwh / avgHousehold) * 100);

    if (percentage >= 100) {
        return `To pokryje ok. ${percentage}% rocznego zuzycia pradu typowego gospodarstwa domowego w Polsce!`;
    } else {
        return `To pokryje ok. ${percentage}% rocznego zuzycia pradu typowego gospodarstwa domowego (ok. ${avgHousehold} kWh/rok).`;
    }
}

/**
 * Rysuje prosty wykres slupkowy produkcji miesiecznej.
 * Wykres jest zrobiony w czystym CSS/JS (bez zewnetrznych bibliotek).
 */
function renderMonthlyChart(monthlyData) {
    const container = document.getElementById('monthly-chart');
    container.innerHTML = '';

    if (!monthlyData || monthlyData.length !== 12) {
        container.innerHTML = '<p>Brak danych miesiecznych</p>';
        return;
    }

    // Znajdz maksymalna wartosc (do skalowania wykresu)
    const maxValue = Math.max(...monthlyData);

    // Tworzenie slupkow
    monthlyData.forEach(function(value) {
        const bar = document.createElement('div');
        bar.className = 'chart-bar';

        // Wysokosc proporcjonalna do wartosci (max = 100% wysokosci)
        const heightPercent = maxValue > 0 ? (value / maxValue) * 100 : 0;
        bar.style.height = heightPercent + '%';

        // Wartosc wyswietlana po najechaniu
        bar.setAttribute('data-value', Math.round(value) + ' kWh');

        container.appendChild(bar);
    });
}

// ============================================
// POMOCNICZE FUNKCJE
// ============================================

/**
 * Pokazuje blad uzytkownikowi.
 */
function showError(message) {
    document.getElementById('error-text').textContent = message;
    showElement('error-section');
}

/**
 * Pokazuje element HTML (usuwa klase 'hidden').
 */
function showElement(id) {
    document.getElementById(id).classList.remove('hidden');
}

/**
 * Ukrywa element HTML (dodaje klase 'hidden').
 */
function hideElement(id) {
    document.getElementById(id).classList.add('hidden');
}
