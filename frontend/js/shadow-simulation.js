// ===========================
// Modul symulacji cieni (shadow-simulation.js)
//
// Zarzadza pozycja swiatla kierunkowego (slonca) na scenie 3D
// na podstawie obliczonej pozycji slonca. Umozliwia animacje
// uplywu czasu - slonce przesuwa sie po niebie w przyspieszonym tempie.
//
// Eksportowane funkcje:
// - initShadowSimulation(scene, directionalLight) - inicjalizacja
// - updateSunPosition(lat, lon, date) - aktualizacja pozycji swiatla
// - startAnimation(lat, lon, date, speedMultiplier, onUpdate) - start animacji
// - stopAnimation() - zatrzymanie animacji
// - getAnimationState() - czy animacja jest aktywna
// ===========================

import { calculateSunPosition, sunPositionToLightPosition, isDaylight } from './sun-position.js';

// --- Zmienne globalne modulu ---
let _scene = null;           // referencja do sceny Three.js
let _directionalLight = null; // referencja do swiatla kierunkowego (slonce)
let _ambientLight = null;     // referencja do swiatla otoczenia

// Stan animacji
let _animationRunning = false;   // czy animacja jest aktywna
let _animationFrameId = null;    // ID requestAnimationFrame (do anulowania)
let _lastFrameTime = null;       // timestamp ostatniej klatki
let _animationStartDate = null;  // data poczatkowa animacji
let _currentTimeMinutes = 0;     // aktualny czas w minutach od polnocy
let _speedMultiplier = 1;        // mnoznik predkosci animacji
let _animationLat = 0;           // szerokosc geograficzna dla animacji
let _animationLon = 0;           // dlugosc geograficzna dla animacji
let _onUpdateCallback = null;    // callback wywoływany co klatke animacji
let _totalElapsedMinutes = 0;    // laczny czas jaki minal w animacji

/**
 * Inicjalizuje modul symulacji cieni.
 * Zapamiertuje referencje do sceny i swiatla kierunkowego.
 *
 * @param {THREE.Scene} scene - scena Three.js
 * @param {THREE.DirectionalLight} directionalLight - swiatlo kierunkowe (slonce)
 */
export function initShadowSimulation(scene, directionalLight) {
    _scene = scene;
    _directionalLight = directionalLight;

    // Szukamy swiatla otoczenia (AmbientLight) na scenie
    _scene.traverse((child) => {
        if (child.isAmbientLight) {
            _ambientLight = child;
        }
    });
}

/**
 * Aktualizuje pozycje swiatla kierunkowego na podstawie pozycji slonca.
 * Oblicza gdzie jest slonce i ustawia swiatlo w odpowiednim miejscu.
 *
 * @param {number} lat - szerokosc geograficzna (stopnie)
 * @param {number} lon - dlugosc geograficzna (stopnie)
 * @param {Date} date - data i czas do obliczenia pozycji slonca
 * @returns {{elevation: number, azimuth: number, isDay: boolean}} pozycja slonca i czy jest dzien
 */
export function updateSunPosition(lat, lon, date) {
    if (!_directionalLight) {
        console.warn('shadow-simulation: brak zainicjalizowanego swiatla kierunkowego');
        return { elevation: 0, azimuth: 0, isDay: false };
    }

    // Obliczamy pozycje slonca
    const sunPos = calculateSunPosition(lat, lon, date);
    const isDay = isDaylight(sunPos.elevation);

    if (isDay) {
        // Dzien - ustawiamy swiatlo w pozycji slonca
        const lightPos = sunPositionToLightPosition(sunPos.elevation, sunPos.azimuth, 100);
        _directionalLight.position.copy(lightPos);
        _directionalLight.intensity = 1.0;
        _directionalLight.visible = true;

        // Swiatlo otoczenia - normalna jasnosc
        if (_ambientLight) {
            _ambientLight.intensity = 0.5;
        }
    } else {
        // Noc - wylaczamy swiatlo kierunkowe, minimalne otoczenie
        _directionalLight.intensity = 0;
        _directionalLight.visible = false;

        // Minimalne swiatlo otoczenia zeby scena nie byla calkiem czarna
        if (_ambientLight) {
            _ambientLight.intensity = 0.1;
        }
    }

    return {
        elevation: sunPos.elevation,
        azimuth: sunPos.azimuth,
        isDay: isDay
    };
}

/**
 * Uruchamia animacje uplywu czasu.
 * Slonce przesuwa sie po niebie w przyspieszonym tempie.
 *
 * @param {number} lat - szerokosc geograficzna
 * @param {number} lon - dlugosc geograficzna
 * @param {Date} date - data poczatkowa (godzina bedzie brana z tego obiektu)
 * @param {number} speedMultiplier - mnoznik predkosci (1x, 10x, 60x, 360x)
 * @param {Function} onUpdate - callback(currentDate, sunInfo) wywoływany co klatke
 */
export function startAnimation(lat, lon, date, speedMultiplier, onUpdate) {
    // Zatrzymujemy poprzednia animacje jesli trwa
    if (_animationRunning) {
        stopAnimation();
    }

    _animationLat = lat;
    _animationLon = lon;
    _speedMultiplier = speedMultiplier || 1;
    _onUpdateCallback = onUpdate || null;
    _animationRunning = true;
    _lastFrameTime = null;
    _totalElapsedMinutes = 0;

    // Zapamietujemy poczatkowa date i czas w minutach od polnocy
    _animationStartDate = new Date(date.getTime());
    _currentTimeMinutes = date.getHours() * 60 + date.getMinutes();

    // Startujemy petle animacji
    _animationFrameId = requestAnimationFrame(animationLoop);
}

/**
 * Zatrzymuje animacje.
 */
export function stopAnimation() {
    _animationRunning = false;
    if (_animationFrameId !== null) {
        cancelAnimationFrame(_animationFrameId);
        _animationFrameId = null;
    }
    _lastFrameTime = null;
    _onUpdateCallback = null;
}

/**
 * Zwraca czy animacja jest aktywna.
 * @returns {boolean} true jesli animacja trwa
 */
export function getAnimationState() {
    return _animationRunning;
}

/**
 * Wewnetrzna petla animacji - wywoływana co klatke przez requestAnimationFrame.
 * Przesuwa czas do przodu i aktualizuje pozycje slonca.
 *
 * @param {number} timestamp - czas w milisekundach (z requestAnimationFrame)
 */
function animationLoop(timestamp) {
    if (!_animationRunning) return;

    // Pierwszy frame - zapamietujemy czas
    if (_lastFrameTime === null) {
        _lastFrameTime = timestamp;
        _animationFrameId = requestAnimationFrame(animationLoop);
        return;
    }

    // Obliczamy ile czasu realnego minelo od ostatniej klatki (w sekundach)
    const deltaTimeSeconds = (timestamp - _lastFrameTime) / 1000;
    _lastFrameTime = timestamp;

    // Przesuwamy czas symulacji o (deltaTime * speedMultiplier) minut
    // speedMultiplier mowi ile minut symulacji mija w jednej sekundzie realnego czasu
    const minutesAdvance = deltaTimeSeconds * _speedMultiplier;
    _currentTimeMinutes += minutesAdvance;
    _totalElapsedMinutes += minutesAdvance;

    // Sprawdzamy czy minal pelny cykl 24h (1440 minut)
    if (_totalElapsedMinutes >= 1440) {
        // Koniec cyklu - zatrzymujemy animacje
        _currentTimeMinutes = _currentTimeMinutes % 1440;
        stopAnimation();

        // Ostatnia aktualizacja z koncowa pozycja
        const finalDate = _buildDateFromMinutes(_currentTimeMinutes);
        const sunInfo = updateSunPosition(_animationLat, _animationLon, finalDate);
        if (_onUpdateCallback) {
            // Callback moze juz byc null po stopAnimation, wiec uzywamy lokalnej kopii
        }
        return;
    }

    // Normalizujemy czas do zakresu 0-1440 (jedna doba)
    if (_currentTimeMinutes >= 1440) {
        _currentTimeMinutes -= 1440;
    }

    // Tworzymy date z aktualnym czasem symulacji
    const currentDate = _buildDateFromMinutes(_currentTimeMinutes);

    // Aktualizujemy pozycje slonca
    const sunInfo = updateSunPosition(_animationLat, _animationLon, currentDate);

    // Wywolujemy callback z aktualnymi danymi
    if (_onUpdateCallback) {
        _onUpdateCallback(currentDate, sunInfo);
    }

    // Kolejna klatka
    _animationFrameId = requestAnimationFrame(animationLoop);
}

/**
 * Buduje obiekt Date z ilosci minut od polnocy, zachowujac date z _animationStartDate.
 *
 * @param {number} minutes - minuty od polnocy (0-1440)
 * @returns {Date} obiekt daty z ustawionym czasem
 */
function _buildDateFromMinutes(minutes) {
    const date = new Date(_animationStartDate.getTime());
    const hours = Math.floor(minutes / 60);
    const mins = Math.floor(minutes % 60);
    date.setHours(hours, mins, 0, 0);
    return date;
}
