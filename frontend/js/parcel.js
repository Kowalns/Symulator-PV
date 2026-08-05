// ===========================
// Modul granic dzialki
// Pobieranie z geoportalu ULDK, parsowanie WKT, konwersja wspolrzednych,
// rysowanie granic w scenie 3D, tryb recznego rysowania
//
// ULDK = Usluga Lokalizacji Dzialek Katastralnych
// WKT = Well-Known Text - tekstowy format zapisu ksztaltow geometrycznych
// EPSG:2180 = polski uklad wspolrzednych (metry) uzywany przez ULDK
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

// --- Zmienne modulu ---
let parcelLines = [];      // linie granic dzialki w scenie
let drawingPoints = [];    // punkty rysowane recznie
let drawingMarkers = [];   // znaczniki (kulki) przy punktach
let drawingLine = null;    // linia rysowana recznie
let isDrawingMode = false; // czy tryb rysowania jest aktywny

// =====================
// SEKCJA 1: API ULDK (geoportal)
// =====================

/**
 * Pobiera granice dzialki katastralnej z API geoportalu ULDK.
 * 
 * API ULDK zwraca geometrie (ksztalt) dzialki w formacie WKT
 * we wspolrzednych EPSG:2180 (polskie metry).
 * 
 * @param {string} parcelId - numer/identyfikator dzialki (np. "141201_1.0001.6509/2")
 * @returns {Promise<string>} - tekst WKT z geometria dzialki
 */
export async function fetchParcelFromULDK(parcelId) {
    // Budujemy URL do API ULDK
    // request=GetParcelById - szukamy po identyfikatorze
    // result=geom_wkt - chcemy geometrie w formacie WKT
    const url = `https://uldk.gugik.gov.pl/?request=GetParcelById&id=${encodeURIComponent(parcelId)}&result=geom_wkt`;

    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`Blad HTTP: ${response.status}`);
        }

        const text = await response.text();

        // ULDK zwraca odpowiedz ze statusem w pierwszej linii
        // Status 1 = sukces, inne = blad
        const lines = text.trim().split('\n');

        if (lines.length < 1) {
            throw new Error('Pusta odpowiedz z serwera ULDK');
        }

        // Pierwsza linia to status (np. "1" = OK, "-1" = blad)
        // Sprawdzamy czy odpowiedz zawiera geometrie WKT
        const fullText = text.trim();

        // Jesli odpowiedz zaczyna sie od "-1" lub "0" to blad
        if (fullText.startsWith('-1') || fullText.startsWith('0')) {
            throw new Error(
                'Nie znaleziono dzialki o podanym numerze. ' +
                'Sprawdz czy numer jest poprawny (np. 141201_1.0001.6509/2).'
            );
        }

        // Szukamy WKT w odpowiedzi - zwykle zaczyna sie od POLYGON lub MULTIPOLYGON
        // Format odpowiedzi ULDK: "1\nSRID=2180;POLYGON((...))""
        let wkt = fullText;

        // Usuwamy ewentualny prefix statusu
        if (wkt.includes(';')) {
            // Format: "1\nSRID=2180;POLYGON(...)" lub "SRID=2180;POLYGON(...)"
            wkt = wkt.substring(wkt.indexOf(';') + 1);
        } else if (wkt.includes('POLYGON') || wkt.includes('MULTIPOLYGON')) {
            // WKT bezposrednio w odpowiedzi
            const polyIndex = wkt.indexOf('POLYGON');
            const multiIndex = wkt.indexOf('MULTIPOLYGON');
            const startIndex = multiIndex >= 0 ? multiIndex : polyIndex;
            if (startIndex > 0) {
                wkt = wkt.substring(startIndex);
            }
        } else {
            throw new Error(
                'Odpowiedz z ULDK nie zawiera geometrii. ' +
                'Sprawdz numer dzialki (np. format: 141201_1.0001.6509/2).'
            );
        }

        // Walidacja - sprawdzamy czy wynik zaczyna sie od poprawnego typu geometrii
        wkt = wkt.trim();
        if (!wkt.startsWith('POLYGON') && !wkt.startsWith('MULTIPOLYGON')) {
            throw new Error(
                'Odpowiedz z ULDK nie zawiera poprawnej geometrii WKT. ' +
                'Otrzymano nieoczekiwany format danych.'
            );
        }

        return wkt;

    } catch (error) {
        if (error.message.includes('fetch')) {
            throw new Error(
                'Nie mozna polaczyc sie z serwerem ULDK (geoportal). ' +
                'Sprawdz polaczenie z internetem.'
            );
        }
        throw error;
    }
}

// =====================
// SEKCJA 2: Parsowanie WKT
// =====================

/**
 * Parsuje tekst WKT (Well-Known Text) i wyciaga z niego wspolrzedne punktow.
 * 
 * WKT to tekstowy format do zapisu ksztaltow, np:
 * POLYGON((x1 y1, x2 y2, x3 y3, x1 y1))
 * 
 * @param {string} wkt - tekst WKT z geometria
 * @returns {Array<Array<{x: number, y: number}>>} - tablica pierscieni, kazdy pierscien to tablica punktow
 */
export function parseWKT(wkt) {
    const rings = [];

    // Usuwamy prefix typu (POLYGON, MULTIPOLYGON, SRID itp.)
    let clean = wkt.trim();

    // Obslugujemy MULTIPOLYGON - parsujemy WSZYSTKIE polygony (nie tylko pierwszy)
    if (clean.startsWith('MULTIPOLYGON')) {
        // MULTIPOLYGON(((x y, ...)), ((x y, ...)))
        clean = clean.replace('MULTIPOLYGON', '').trim();
        // Usuwamy zewnetrzne nawiasy multipolygonu
        if (clean.startsWith('(') && clean.endsWith(')')) {
            clean = clean.slice(1, -1).trim();
        }

        // Dzielimy na poszczegolne polygony - rozdzielone sa przez ")),(("
        // Kazdy polygon wyglada tak: ((x y, x y, ...))
        // Szukamy wzorca: pary nawiasow oddzielone przecinkiem
        const polygonRegex = /\(\(([^)]*(?:\)[^)]*)*)\)/g;
        let polyMatch;

        while ((polyMatch = polygonRegex.exec(clean)) !== null) {
            const polyContent = polyMatch[0];
            // Wyciagamy pierscienie z tego polygonu
            const ringRegex = /\(([^)]+)\)/g;
            let ringMatch;
            while ((ringMatch = ringRegex.exec(polyContent)) !== null) {
                const coordText = ringMatch[1];
                const points = coordText.split(',').map(pair => {
                    const parts = pair.trim().split(/\s+/);
                    return {
                        x: parseFloat(parts[0]),
                        y: parseFloat(parts[1])
                    };
                }).filter(p => !isNaN(p.x) && !isNaN(p.y));

                if (points.length > 0) {
                    rings.push(points);
                }
            }
        }

        // Fallback - jesli regex nie zlapala nic, parsujemy tak jak wczesniej
        if (rings.length === 0) {
            const ringRegex = /\(([^)]+)\)/g;
            let match;
            while ((match = ringRegex.exec(clean)) !== null) {
                const coordText = match[1];
                const points = coordText.split(',').map(pair => {
                    const parts = pair.trim().split(/\s+/);
                    return {
                        x: parseFloat(parts[0]),
                        y: parseFloat(parts[1])
                    };
                }).filter(p => !isNaN(p.x) && !isNaN(p.y));

                if (points.length > 0) {
                    rings.push(points);
                }
            }
        }
    } else if (clean.startsWith('POLYGON')) {
        // POLYGON((x y, ...))
        clean = clean.replace('POLYGON', '').trim();
        // Usuwamy zewnetrzny nawias
        if (clean.startsWith('(') && clean.endsWith(')')) {
            clean = clean.slice(1, -1).trim();
        }

        // Teraz mamy cos jak: (x1 y1, x2 y2, ...), (x1 y1, x2 y2, ...)
        // Kazdy nawias to "pierscien" (ring) - zewnetrzna granica lub dziura

        // Wyciagamy zawartosc z nawiasow
        const ringRegex = /\(([^)]+)\)/g;
        let match;

        while ((match = ringRegex.exec(clean)) !== null) {
            const coordText = match[1];
            const points = coordText.split(',').map(pair => {
                const parts = pair.trim().split(/\s+/);
                return {
                    x: parseFloat(parts[0]),
                    y: parseFloat(parts[1])
                };
            }).filter(p => !isNaN(p.x) && !isNaN(p.y));

            if (points.length > 0) {
                rings.push(points);
            }
        }
    } else {
        // Brak rozpoznanego typu - probujemy parsowac pierscienie bezposrednio
        const ringRegex = /\(([^)]+)\)/g;
        let match;

        while ((match = ringRegex.exec(clean)) !== null) {
            const coordText = match[1];
            const points = coordText.split(',').map(pair => {
                const parts = pair.trim().split(/\s+/);
                return {
                    x: parseFloat(parts[0]),
                    y: parseFloat(parts[1])
                };
            }).filter(p => !isNaN(p.x) && !isNaN(p.y));

            if (points.length > 0) {
                rings.push(points);
            }
        }
    }

    // Jesli nie znalezlismy pierscieni (brak nawiasow), probujemy parsowac calosc
    if (rings.length === 0 && clean.includes(',')) {
        const points = clean.split(',').map(pair => {
            const parts = pair.trim().split(/\s+/);
            return {
                x: parseFloat(parts[0]),
                y: parseFloat(parts[1])
            };
        }).filter(p => !isNaN(p.x) && !isNaN(p.y));

        if (points.length > 0) {
            rings.push(points);
        }
    }

    return rings;
}

// =====================
// SEKCJA 3: Konwersja wspolrzednych EPSG:2180 na lokalne metry
// =====================

/**
 * Konwertuje wspolrzedne z EPSG:2180 (polskie metry) na lokalne wspolrzedne 3D.
 * 
 * EPSG:2180 to uklad wspolrzednych uzywany w Polsce - wartosci sa w metrach,
 * ale sa to bardzo duze liczby (np. X: 5500000, Y: 7500000).
 * 
 * Zeby wyswietlic dzialke w scenie 3D, musimy:
 * 1. Obliczyc srodek dzialki
 * 2. Przesunac wszystkie punkty tak, zeby srodek byl w punkcie (0, 0)
 * 3. Ewentualnie przeskalowac jesli dzialka jest bardzo duza
 * 
 * @param {Array<{x: number, y: number}>} points - punkty w EPSG:2180
 * @returns {Array<{x: number, z: number}>} - punkty w lokalnych wspolrzednych 3D (x, z na plasczyznie)
 */
export function convertEPSG2180ToLocal(points) {
    if (points.length === 0) return [];

    // Obliczamy srodek (centroid) wszystkich punktow
    let sumX = 0, sumY = 0;
    for (const p of points) {
        sumX += p.x;
        sumY += p.y;
    }
    const centerX = sumX / points.length;
    const centerY = sumY / points.length;

    // Przesuwamy punkty wzgledem srodka - teraz wartosci sa bliskie 0
    // W scenie Three.js: x = wschod/zachod, z = polnoc/poludnie (y to gora/dol)
    const localPoints = points.map(p => ({
        x: p.x - centerX,     // EPSG:2180 X -> Three.js x (bo X w 2180 to "na wschod")
        z: -(p.y - centerY)   // EPSG:2180 Y -> Three.js -z (bo Y w 2180 to "na polnoc", a z w Three.js to "do przodu")
    }));

    return localPoints;
}

// =====================
// SEKCJA 4: Rysowanie granic dzialki w scenie 3D
// =====================

/**
 * Rysuje granice dzialki w scenie 3D jako kolorowe linie na plasczyznie (y=0).
 * 
 * @param {THREE.Scene} scene - scena Three.js
 * @param {Array<Array<{x: number, z: number}>>} rings - pierscienie dzialki (lokalne wspolrzedne)
 * @param {number} color - kolor linii (hex, np. 0x00ff00 = zielony)
 */
export function drawParcelBoundary(scene, rings, color = 0x00ff88) {
    // Najpierw usuwamy stare granice
    clearParcelLines(scene);

    for (const ring of rings) {
        if (ring.length < 2) continue;

        // Tworzymy material linii - kolor i grubosc
        const material = new THREE.LineBasicMaterial({
            color: color,
            linewidth: 2 // uwaga: na wielu urzadzeniach grubosc linii nie dziala >1
        });

        // Tworzymy geometrie linii - zbior punktow polaczonych liniami
        const points = ring.map(p => new THREE.Vector3(p.x, 0.1, p.z)); // y=0.1 zeby bylo tuz nad ziemia

        // Zamykamy kontur (ostatni punkt = pierwszy)
        if (ring.length > 2) {
            points.push(points[0].clone());
        }

        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(geometry, material);
        line.name = 'parcel-boundary';
        scene.add(line);
        parcelLines.push(line);
    }
}

/**
 * Usuwa wszystkie linie granic dzialki ze sceny.
 * @param {THREE.Scene} scene - scena Three.js
 */
export function clearParcelLines(scene) {
    for (const line of parcelLines) {
        scene.remove(line);
        line.geometry.dispose();
        line.material.dispose();
    }
    parcelLines = [];
}

// =====================
// SEKCJA 5: Reczne rysowanie granic
// =====================

/**
 * Wlacza/wylacza tryb recznego rysowania granic dzialki.
 * W tym trybie uzytkownik klika na plasczyzne gruntu zeby dodawac punkty.
 * 
 * @returns {boolean} - nowy stan trybu (true = wlaczony)
 */
export function toggleDrawingMode() {
    isDrawingMode = !isDrawingMode;
    return isDrawingMode;
}

/**
 * Sprawdza czy tryb rysowania jest aktywny.
 * @returns {boolean}
 */
export function getDrawingMode() {
    return isDrawingMode;
}

/**
 * Dodaje punkt do rysowanego konturu dzialki.
 * Wywolywa sie po kliknieciu na plasczyzne gruntu w trybie rysowania.
 * 
 * @param {THREE.Scene} scene - scena Three.js
 * @param {THREE.Vector3} point - pozycja klikniecia w 3D
 */
export function addDrawingPoint(scene, point) {
    // Dodajemy punkt do listy
    drawingPoints.push(new THREE.Vector3(point.x, 0.1, point.z));

    // Rysujemy mala kulke w miejscu klikniecia (znacznik)
    const markerGeometry = new THREE.SphereGeometry(0.3, 8, 8);
    const markerMaterial = new THREE.MeshBasicMaterial({ color: 0xff4444 });
    const marker = new THREE.Mesh(markerGeometry, markerMaterial);
    marker.position.set(point.x, 0.3, point.z);
    marker.name = 'drawing-marker';
    scene.add(marker);
    drawingMarkers.push(marker);

    // Aktualizujemy linie laczaca punkty
    updateDrawingLine(scene);
}

/**
 * Aktualizuje linie laczaca narysowane punkty (podglad przed zamknieciem).
 * @param {THREE.Scene} scene - scena Three.js
 */
function updateDrawingLine(scene) {
    // Usuwamy stara linie
    if (drawingLine) {
        scene.remove(drawingLine);
        drawingLine.geometry.dispose();
        drawingLine.material.dispose();
        drawingLine = null;
    }

    if (drawingPoints.length < 2) return;

    // Rysujemy nowa linie przez wszystkie punkty
    const material = new THREE.LineBasicMaterial({ color: 0xff4444 });
    const geometry = new THREE.BufferGeometry().setFromPoints(drawingPoints);
    drawingLine = new THREE.Line(geometry, material);
    drawingLine.name = 'drawing-line';
    scene.add(drawingLine);
}

/**
 * Zamyka kontur (polygon) - laczy ostatni punkt z pierwszym
 * i zapisuje jako granice dzialki.
 * 
 * @param {THREE.Scene} scene - scena Three.js
 */
export function closeDrawingPolygon(scene) {
    if (drawingPoints.length < 3) {
        return false; // potrzebujemy minimum 3 punkty zeby zamknac polygon
    }

    // Usuwamy stare elementy rysowania
    if (drawingLine) {
        scene.remove(drawingLine);
        drawingLine.geometry.dispose();
        drawingLine.material.dispose();
        drawingLine = null;
    }

    for (const marker of drawingMarkers) {
        scene.remove(marker);
        marker.geometry.dispose();
        marker.material.dispose();
    }
    drawingMarkers = [];

    // Rysujemy finalny kontur jako granice dzialki (zielona linia)
    const ring = drawingPoints.map(p => ({ x: p.x, z: p.z }));
    drawParcelBoundary(scene, [ring], 0x44ff44);

    // Resetujemy punkty rysowania
    drawingPoints = [];
    isDrawingMode = false;

    return true;
}

/**
 * Czysci wszystko - linie granic i punkty rysowania.
 * @param {THREE.Scene} scene - scena Three.js
 */
export function clearAll(scene) {
    clearParcelLines(scene);

    // Usuwamy elementy rysowania
    if (drawingLine) {
        scene.remove(drawingLine);
        drawingLine.geometry.dispose();
        drawingLine.material.dispose();
        drawingLine = null;
    }

    for (const marker of drawingMarkers) {
        scene.remove(marker);
        marker.geometry.dispose();
        marker.material.dispose();
    }
    drawingMarkers = [];
    drawingPoints = [];
    isDrawingMode = false;
}

/**
 * Glowna funkcja - pobiera dzialke z ULDK i rysuje ja w scenie.
 * Laczy kroki: API -> parsowanie WKT -> konwersja wspolrzednych -> rysowanie.
 * 
 * @param {string} parcelId - numer dzialki
 * @param {THREE.Scene} scene - scena Three.js
 * @returns {Promise<void>}
 */
export async function loadAndDrawParcel(parcelId, scene) {
    // 1. Pobieramy geometrie z ULDK
    const wkt = await fetchParcelFromULDK(parcelId);

    // 2. Parsujemy WKT na wspolrzedne
    const rings = parseWKT(wkt);

    if (rings.length === 0) {
        throw new Error('Nie udalo sie odczytac geometrii dzialki z odpowiedzi ULDK.');
    }

    // 3. Konwertujemy kazdy pierscien z EPSG:2180 na lokalne metry
    const localRings = rings.map(ring => convertEPSG2180ToLocal(ring));

    // 4. Rysujemy granice
    drawParcelBoundary(scene, localRings, 0x00ff88);
}
