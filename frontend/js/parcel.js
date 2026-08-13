/**
 * parcel.js - Integracja z ULDK API i rysowanie granic dzialki
 *
 * Funkcjonalnosci:
 * 1. Pobieranie geometrii dzialki z ULDK przez proxy backendowe /api/uldk
 * 2. Parsowanie WKT POLYGON na tablice wspolrzednych
 * 3. Konwersja wspolrzednych WGS84 na lokalne wspolrzedne sceny (metryczne)
 * 4. Rysowanie granic dzialki jako linia na scenie 3D
 * 5. Tryb recznego rysowania granic - klikanie punktow na plaszczyznie
 */

import { THREE, scene, camera, renderer, controls, container, groundPlane } from './viewer3d.js';

// Referencje do narysowanych granic
let parcelLines = null;         // Linia granic z ULDK
let drawingLines = null;        // Linia z recznego rysowania
let drawingPoints = [];         // Punkty recznego rysowania
let drawingMarkers = [];        // Wizualne markery punktow
let isDrawingMode = false;      // Czy tryb rysowania jest aktywny

// Elementy DOM
const parcelIdInput = document.getElementById('parcel-id');
const fetchParcelBtn = document.getElementById('fetch-parcel');
const parcelStatus = document.getElementById('parcel-status');
const startDrawingBtn = document.getElementById('start-drawing');
const finishDrawingBtn = document.getElementById('finish-drawing');
const cancelDrawingBtn = document.getElementById('cancel-drawing');
const drawingStatus = document.getElementById('drawing-status');
const drawingIndicator = document.getElementById('drawing-indicator');

// --- Parsowanie WKT ---

/**
 * Parsuje WKT POLYGON na tablice wspolrzednych [lon, lat].
 * Format WKT: POLYGON((lon1 lat1, lon2 lat2, ...))
 * Lub: POLYGON((x1 y1, x2 y2, ...))
 *
 * Zwraca: Array of [x, y] (lon/lat lub EPSG:2180)
 */
function parseWKT(wktString) {
    // Usuwanie prefiksu SRID jesli jest obecny
    let wkt = wktString.trim();
    if (wkt.startsWith('SRID=')) {
        wkt = wkt.substring(wkt.indexOf(';') + 1);
    }

    // Obsluga POLYGON i MULTIPOLYGON
    const polygonMatch = wkt.match(/POLYGON\s*\(\((.+?)\)\)/i);
    if (!polygonMatch) {
        throw new Error('Nie rozpoznano formatu WKT - oczekiwano POLYGON');
    }

    const coordsString = polygonMatch[1];
    const pairs = coordsString.split(',');

    const coordinates = pairs.map(pair => {
        const parts = pair.trim().split(/\s+/);
        if (parts.length < 2) {
            throw new Error(`Nieprawidlowa para wspolrzednych: "${pair}"`);
        }
        return [parseFloat(parts[0]), parseFloat(parts[1])];
    });

    return coordinates;
}

/**
 * Konwertuje wspolrzedne WGS84 (lon/lat) na lokalne wspolrzedne metryczne.
 * Uzywa prostego przeliczenia wzgledem srodka dzialki.
 * 1 stopien szerokosci ~= 111320 m
 * 1 stopien dlugosci ~= 111320 * cos(lat) m
 *
 * Zwraca: Array of {x, z} - wspolrzedne w metrach (Y to wysokosc w Three.js)
 */
function wgs84ToLocal(coordinates) {
    if (coordinates.length === 0) return [];

    // Oblicz srodek dzialki (centroid)
    let sumLon = 0, sumLat = 0;
    for (const [lon, lat] of coordinates) {
        sumLon += lon;
        sumLat += lat;
    }
    const centerLon = sumLon / coordinates.length;
    const centerLat = sumLat / coordinates.length;

    // Przelicz na metry wzgledem srodka
    const metersPerDegreeLat = 111320;
    const metersPerDegreeLon = 111320 * Math.cos(centerLat * Math.PI / 180);

    return coordinates.map(([lon, lat]) => ({
        x: (lon - centerLon) * metersPerDegreeLon,
        z: -(lat - centerLat) * metersPerDegreeLat  // Minus bo w Three.js Z rosnie "do nas"
    }));
}

/**
 * Sprawdza czy wspolrzedne sa w ukladzie WGS84 (wartosci -180..180, -90..90)
 * czy w EPSG:2180 (duze wartosci liczbowe).
 */
function detectCoordinateSystem(coordinates) {
    if (coordinates.length === 0) return 'unknown';

    const [x, y] = coordinates[0];
    // EPSG:2180 ma wartosci rzedu setek tysiecy
    if (Math.abs(x) > 1000 || Math.abs(y) > 1000) {
        return 'epsg2180';
    }
    return 'wgs84';
}

/**
 * Konwertuje wspolrzedne EPSG:2180 na lokalne metryczne.
 * EPSG:2180 juz jest w metrach, wiec wystarczy przesunac do srodka.
 */
function epsg2180ToLocal(coordinates) {
    if (coordinates.length === 0) return [];

    let sumX = 0, sumY = 0;
    for (const [x, y] of coordinates) {
        sumX += x;
        sumY += y;
    }
    const centerX = sumX / coordinates.length;
    const centerY = sumY / coordinates.length;

    return coordinates.map(([x, y]) => ({
        x: x - centerX,
        z: -(y - centerY)  // Minus bo os Y w EPSG:2180 rosnie na polnoc
    }));
}

// --- Rysowanie na scenie ---

/**
 * Rysuje granice dzialki na scenie 3D jako zamknieta linia.
 * localCoords: Array of {x, z}
 * color: kolor linii (hex)
 * isManual: czy to reczne rysowanie (do rozroznienia)
 */
function drawParcelBoundary(localCoords, color = 0x4fc3f7, isManual = false) {
    // Usun poprzednie granice tego samego typu
    if (isManual && drawingLines) {
        scene.remove(drawingLines);
        drawingLines.geometry.dispose();
        drawingLines.material.dispose();
        drawingLines = null;
    } else if (!isManual && parcelLines) {
        scene.remove(parcelLines);
        parcelLines.geometry.dispose();
        parcelLines.material.dispose();
        parcelLines = null;
    }

    if (localCoords.length < 2) return null;

    // Tworzymy punkty linii (Y = 0.1 zeby byla lekko nad gruntem)
    const points = localCoords.map(coord =>
        new THREE.Vector3(coord.x, 0.1, coord.z)
    );

    // Zamykamy polygon (ostatni punkt = pierwszy)
    if (points.length > 2) {
        points.push(points[0].clone());
    }

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
        color: color,
        linewidth: 2,
    });

    const line = new THREE.Line(geometry, material);

    if (isManual) {
        drawingLines = line;
    } else {
        parcelLines = line;
    }

    scene.add(line);
    return line;
}

// --- Integracja z ULDK API ---

/**
 * Pobiera geometrie dzialki z ULDK przez proxy backendowe.
 * parcelId: numer dzialki katastralnej (np. "141201_1.0001.6509")
 */
async function fetchParcelGeometry(parcelId) {
    const url = `/api/uldk?request=GetParcelById&id=${encodeURIComponent(parcelId)}&result=geom_wkt&srid=4326`;

    const response = await fetch(url);

    if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.message || `Blad HTTP: ${response.status}`);
    }

    const text = await response.text();

    // ULDK zwraca odpowiedz tekstowa - pierwsza linia to status/wynik
    // Format: "1\ngeometria_WKT" (gdzie 1 = sukces) lub "0\nbrak_wynikow"
    const lines = text.trim().split('\n');

    if (lines.length < 1) {
        throw new Error('Pusta odpowiedz z ULDK');
    }

    // Sprawdz czy odpowiedz zawiera geometrie
    // ULDK moze zwrocic blad lub "brak wynikow"
    const fullResponse = lines.join('\n');

    if (fullResponse.includes('ERROR') || fullResponse.includes('Blad')) {
        throw new Error(`ULDK: ${fullResponse}`);
    }

    // Szukamy WKT POLYGON w odpowiedzi
    const wktMatch = fullResponse.match(/POLYGON\s*\(\(.+?\)\)/i);
    if (!wktMatch) {
        // Moze geometria jest w ostatniej linii (format: status\ngeometria)
        const lastLine = lines[lines.length - 1].trim();
        if (lastLine.includes('POLYGON')) {
            return lastLine;
        }
        throw new Error('Nie znaleziono geometrii POLYGON w odpowiedzi ULDK');
    }

    return wktMatch[0];
}

/**
 * Glowna funkcja: pobiera i rysuje granice dzialki.
 */
async function loadAndDrawParcel(parcelId) {
    setParcelStatus('Pobieranie geometrii z ULDK...', '');

    try {
        const wkt = await fetchParcelGeometry(parcelId);
        const coordinates = parseWKT(wkt);

        if (coordinates.length < 3) {
            throw new Error('Za malo punktow w geometrii dzialki');
        }

        // Wykryj uklad wspolrzednych i przelicz
        const coordSystem = detectCoordinateSystem(coordinates);
        let localCoords;

        if (coordSystem === 'epsg2180') {
            localCoords = epsg2180ToLocal(coordinates);
        } else {
            localCoords = wgs84ToLocal(coordinates);
        }

        drawParcelBoundary(localCoords, 0x4fc3f7, false);

        // Zapisz wierzcholki do localStorage (bez duplikatu zamykajacego)
        const uniqueCoords = localCoords.slice(0, -1); // ostatni = pierwszy (zamkniecie)
        localStorage.setItem('parcel_vertices', JSON.stringify(uniqueCoords));

        // Wyemituj event aby inne komponenty mogly zareagowac
        window.dispatchEvent(new CustomEvent('parcelLoaded', { detail: { vertices: uniqueCoords } }));

        setParcelStatus(`Wczytano granice dzialki (${uniqueCoords.length} punktow)`, 'success');

    } catch (error) {
        setParcelStatus(`Blad: ${error.message}`, 'error');
    }
}

function setParcelStatus(text, type) {
    if (parcelStatus) {
        parcelStatus.textContent = text;
        parcelStatus.className = 'status-text' + (type ? ' ' + type : '');
    }
}

// --- Tryb recznego rysowania granic ---

/**
 * Raycasting - znajdowanie punktu na plaszczyznie gruntu
 * kliknietego myszka.
 */
function getGroundIntersection(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);

    const intersection = new THREE.Vector3();
    const ray = raycaster.ray;

    if (ray.intersectPlane(groundPlane, intersection)) {
        return intersection;
    }
    return null;
}

/**
 * Dodaje punkt do recznego rysowania.
 */
function addDrawingPoint(point) {
    drawingPoints.push({ x: point.x, z: point.z });

    // Dodaj wizualny marker (mala kulka)
    const markerGeom = new THREE.SphereGeometry(0.3, 8, 8);
    const markerMat = new THREE.MeshBasicMaterial({ color: 0x43a047 });
    const marker = new THREE.Mesh(markerGeom, markerMat);
    marker.position.copy(point);
    marker.position.y = 0.2;
    scene.add(marker);
    drawingMarkers.push(marker);

    // Rysuj dotychczasowa linie
    if (drawingPoints.length > 1) {
        drawParcelBoundary(drawingPoints, 0x43a047, true);
    }

    setDrawingStatus(`Punkty: ${drawingPoints.length} (min. 3 do zamkniecia)`, '');
}

/**
 * Zamyka polygon recznego rysowania.
 */
function finishDrawing() {
    if (drawingPoints.length < 3) {
        setDrawingStatus('Potrzeba min. 3 punkty do zamkniecia polygonu', 'error');
        return;
    }

    // Narysuj zamkniety polygon
    drawParcelBoundary(drawingPoints, 0x43a047, true);
    setDrawingStatus(`Polygon zamkniety (${drawingPoints.length} wierzcholkow)`, 'success');

    // Wylacz tryb rysowania
    exitDrawingMode();
}

/**
 * Anuluje reczne rysowanie.
 */
function cancelDrawing() {
    // Usun markery
    for (const marker of drawingMarkers) {
        scene.remove(marker);
        marker.geometry.dispose();
        marker.material.dispose();
    }
    drawingMarkers = [];
    drawingPoints = [];

    // Usun linie
    if (drawingLines) {
        scene.remove(drawingLines);
        drawingLines.geometry.dispose();
        drawingLines.material.dispose();
        drawingLines = null;
    }

    setDrawingStatus('Rysowanie anulowane', '');
    exitDrawingMode();
}

/**
 * Wlacza tryb rysowania.
 */
function enterDrawingMode() {
    isDrawingMode = true;
    drawingPoints = [];

    // Usun stare markery
    for (const marker of drawingMarkers) {
        scene.remove(marker);
        marker.geometry.dispose();
        marker.material.dispose();
    }
    drawingMarkers = [];

    // Pokaz/ukryj przyciski
    if (startDrawingBtn) startDrawingBtn.style.display = 'none';
    if (finishDrawingBtn) finishDrawingBtn.style.display = 'block';
    if (cancelDrawingBtn) cancelDrawingBtn.style.display = 'block';
    if (drawingIndicator) drawingIndicator.classList.add('active');

    // Wylacz OrbitControls na prawy przycisk (lewy do rysowania)
    controls.enableRotate = true;  // Obroty nadal dzialaja (prawy przycisk)

    setDrawingStatus('Kliknij na plaszczyznie aby dodac punkty', '');
}

/**
 * Wylacza tryb rysowania.
 */
function exitDrawingMode() {
    isDrawingMode = false;

    if (startDrawingBtn) startDrawingBtn.style.display = 'block';
    if (finishDrawingBtn) finishDrawingBtn.style.display = 'none';
    if (cancelDrawingBtn) cancelDrawingBtn.style.display = 'none';
    if (drawingIndicator) drawingIndicator.classList.remove('active');
}

function setDrawingStatus(text, type) {
    if (drawingStatus) {
        drawingStatus.textContent = text;
        drawingStatus.className = 'status-text' + (type ? ' ' + type : '');
    }
}

// --- Obsluga zdarzen ---

// Klikniecie na canvas - dodawanie punktu w trybie rysowania
if (renderer && renderer.domElement) {
    renderer.domElement.addEventListener('click', (event) => {
        if (!isDrawingMode) return;

        const point = getGroundIntersection(event);
        if (point) {
            addDrawingPoint(point);
        }
    });
}

// Klawisz ESC - anulowanie rysowania
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isDrawingMode) {
        cancelDrawing();
    }
});

// Przycisk: Pobierz granice z ULDK
if (fetchParcelBtn) {
    fetchParcelBtn.addEventListener('click', () => {
        const parcelId = parcelIdInput?.value?.trim();
        if (!parcelId) {
            setParcelStatus('Wpisz numer dzialki katastralnej', 'error');
            return;
        }
        loadAndDrawParcel(parcelId);
    });
}

// Przycisk: Rozpocznij rysowanie
if (startDrawingBtn) {
    startDrawingBtn.addEventListener('click', enterDrawingMode);
}

// Przycisk: Zamknij polygon
if (finishDrawingBtn) {
    finishDrawingBtn.addEventListener('click', finishDrawing);
}

// Przycisk: Anuluj rysowanie
if (cancelDrawingBtn) {
    cancelDrawingBtn.addEventListener('click', cancelDrawing);
}

// Eksport funkcji uzytecznych
export { parseWKT, wgs84ToLocal, epsg2180ToLocal, fetchParcelGeometry, loadAndDrawParcel };
