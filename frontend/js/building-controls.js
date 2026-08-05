// ===========================
// Modul kontroli budynku (building-controls.js)
//
// Ten modul odpowiada za:
// 1. Skalowanie modelu STL do rzeczywistych metrow (uzytkownik podaje wymiar)
// 2. Tryb pozycjonowania - przeciaganie budynku po dzialce
// 3. Obrot budynku wokol osi Y (pionowej)
//
// Dlaczego to potrzebne?
// - Model STL moze byc w dowolnych jednostkach (mm, cm, m) - zalezy od programu CAD
// - Dzialka z geoportalu ULDK jest w rzeczywistych metrach
// - Musimy dopasowac skale modelu do skali dzialki
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

// --- Zmienne modulu ---
let isDragging = false;         // czy aktualnie przeciagamy budynek
let isPositionMode = false;     // czy tryb pozycjonowania jest aktywny
let dragPlane = null;           // plaska plaszczyzna do obliczania pozycji myszy w 3D
let dragOffset = new THREE.Vector3(); // przesuniecie miedzy kliknieciem a srodkiem obiektu

/**
 * Oblicza wspolczynnik skali (scaleFactor) na podstawie rzeczywistego wymiaru budynku.
 * 
 * Jak to dziala:
 * - Model STL ma pewien rozmiar w swoich jednostkach (np. 12000 w mm)
 * - Uzytkownik mowi "moj budynek ma 12 metrow dlugosci"
 * - Obliczamy: scaleFactor = 12 / (aktualny rozmiar modelu w danym wymiarze)
 * - Po przeskalowaniu model bedzie mial dokladnie 12 jednostek (metrow) dlugosci
 * 
 * @param {THREE.Mesh} mesh - model 3D (mesh z geometria)
 * @param {number} realDimension - rzeczywisty wymiar w metrach (np. 12)
 * @param {string} axis - os wymiaru: 'x' (dlugosc/szerokosc), 'y' (wysokosc), 'z' (glebokosc/szerokosc)
 * @returns {number} nowy wspolczynnik skali (scaleFactor)
 */
export function calculateScaleFactor(mesh, realDimension, axis = 'x') {
    if (!mesh || !mesh.geometry) return 1;
    if (realDimension <= 0) return 1;

    // Obliczamy rozmiar oryginalnej geometrii (bez skali)
    // Musimy "cofnac" aktualna skale zeby dostac oryginalny rozmiar
    mesh.geometry.computeBoundingBox();
    const bbox = mesh.geometry.boundingBox;
    const size = new THREE.Vector3();
    bbox.getSize(size);

    // Rozmiar w wybranej osi (oryginalny, bez skali)
    let originalSize = 0;
    switch (axis) {
        case 'x': originalSize = size.x; break;
        case 'y': originalSize = size.y; break;
        case 'z': originalSize = size.z; break;
        default: originalSize = size.x;
    }

    if (originalSize <= 0) return 1;

    // Nowy wspolczynnik skali: rzeczywisty wymiar / rozmiar geometrii
    // Np. budynek 12m, geometria ma 12000 jednostek -> scale = 12/12000 = 0.001
    const newScale = realDimension / originalSize;
    return newScale;
}

/**
 * Stosuje nowy wspolczynnik skali do modelu i koryguje pozycje (stoi na ziemi).
 * 
 * @param {THREE.Mesh} mesh - model 3D
 * @param {number} scaleFactor - wspolczynnik skali
 */
export function applyScale(mesh, scaleFactor) {
    if (!mesh) return;

    // Ustawiamy skale (jednakowo na wszystkich osiach - zachowujemy proporcje)
    mesh.scale.set(scaleFactor, scaleFactor, scaleFactor);

    // Po zmianie skali upewniamy sie ze model stoi na ziemi (y >= 0)
    // Obliczamy nowy bounding box po przeskalowaniu
    const box = new THREE.Box3().setFromObject(mesh);
    const minY = box.min.y;

    // Jesli dolna krawedz jest ponizej ziemi, przesuwamy w gore
    if (minY < 0) {
        mesh.position.y -= minY;
    }
}

/**
 * Zwraca aktualne wymiary modelu w jednostkach sceny (metrach) po przeskalowaniu.
 * Przydatne do wyswietlenia uzytkownikowi informacji o rozmiarze.
 * 
 * @param {THREE.Mesh} mesh - model 3D
 * @returns {{x: number, y: number, z: number}|null} wymiary w metrach lub null
 */
export function getModelDimensions(mesh) {
    if (!mesh) return null;

    const box = new THREE.Box3().setFromObject(mesh);
    const size = new THREE.Vector3();
    box.getSize(size);

    return {
        x: Math.round(size.x * 100) / 100,  // zaokraglamy do 2 miejsc
        y: Math.round(size.y * 100) / 100,
        z: Math.round(size.z * 100) / 100
    };
}

// =====================
// SEKCJA 2: Obrot budynku
// =====================

/**
 * Obraca model budynku wokol osi Y (pionowej) o zadany kat.
 * Os Y w Three.js to "gora/dol", wiec obrot wokol Y = obrot na plaszczyznie.
 * 
 * @param {THREE.Mesh} mesh - model 3D
 * @param {number} angleDegrees - kat obrotu w stopniach (0-360)
 */
export function setRotation(mesh, angleDegrees) {
    if (!mesh) return;

    // Konwersja stopni na radiany (Three.js uzywa radianow)
    // 1 stopien = PI/180 radianow
    const radians = (angleDegrees * Math.PI) / 180;
    mesh.rotation.y = radians;
}

/**
 * Zwraca aktualny kat obrotu modelu w stopniach.
 * 
 * @param {THREE.Mesh} mesh - model 3D
 * @returns {number} kat w stopniach (0-360)
 */
export function getRotation(mesh) {
    if (!mesh) return 0;
    // Konwersja radianow na stopnie
    let degrees = (mesh.rotation.y * 180) / Math.PI;
    // Normalizujemy do zakresu 0-360
    degrees = ((degrees % 360) + 360) % 360;
    return Math.round(degrees * 10) / 10; // zaokraglamy do 1 miejsca
}

// =====================
// SEKCJA 3: Tryb pozycjonowania (przeciaganie)
// =====================

/**
 * Wlacza lub wylacza tryb pozycjonowania budynku.
 * W trybie pozycjonowania klikamy i przeciagamy budynek po plasczyznie.
 * 
 * @returns {boolean} nowy stan trybu (true = wlaczony)
 */
export function togglePositionMode() {
    isPositionMode = !isPositionMode;
    return isPositionMode;
}

/**
 * Sprawdza czy tryb pozycjonowania jest aktywny.
 * @returns {boolean}
 */
export function getPositionMode() {
    return isPositionMode;
}

/**
 * Ustawia tryb pozycjonowania na okreslona wartosc.
 * @param {boolean} active - czy tryb ma byc aktywny
 */
export function setPositionMode(active) {
    isPositionMode = active;
    if (!active) {
        isDragging = false;
    }
}

/**
 * Obsluguje nacisniecie przycisku myszy - sprawdza czy kliknieto na budynek.
 * Jesli tak, rozpoczyna przeciaganie.
 * 
 * @param {MouseEvent} event - zdarzenie myszy
 * @param {THREE.Mesh} buildingMesh - model budynku
 * @param {THREE.Camera} camera - kamera
 * @param {THREE.WebGLRenderer} renderer - renderer (do obliczenia pozycji myszy)
 * @returns {boolean} true jesli rozpoczeto przeciaganie
 */
export function handleMouseDown(event, buildingMesh, camera, renderer) {
    if (!isPositionMode || !buildingMesh) return false;

    // Obliczamy pozycje myszy w znormalizowanych wspolrzednych (-1 do 1)
    const rect = renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    // Raycaster - "strzela promieniem" z kamery przez pozycje myszy
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);

    // Sprawdzamy czy promien trafia w budynek
    const intersects = raycaster.intersectObject(buildingMesh);

    if (intersects.length > 0) {
        // Trafiono w budynek - rozpoczynamy przeciaganie
        isDragging = true;

        // Tworzymy niewidoczna plaszczyzne na wysokosci y=0 do sledzenia myszy
        // (przeciagamy budynek po tej plaszczyznie)
        dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

        // Obliczamy przesuniecie miedzy punktem klikniecia a pozycja budynku
        // Dzieki temu budynek nie "skacze" do pozycji kursora
        const intersectPoint = new THREE.Vector3();
        raycaster.ray.intersectPlane(dragPlane, intersectPoint);
        dragOffset.copy(buildingMesh.position).sub(intersectPoint);
        // Zachowujemy tylko X i Z (nie zmieniamy wysokosci)
        dragOffset.y = 0;

        return true;
    }

    return false;
}

/**
 * Obsluguje ruch myszy podczas przeciagania budynku.
 * Przesuwa budynek na nowa pozycje na plaszczyznie.
 * 
 * @param {MouseEvent} event - zdarzenie myszy
 * @param {THREE.Mesh} buildingMesh - model budynku
 * @param {THREE.Camera} camera - kamera
 * @param {THREE.WebGLRenderer} renderer - renderer
 * @returns {boolean} true jesli budynek zostal przesuniety
 */
export function handleMouseMove(event, buildingMesh, camera, renderer) {
    if (!isDragging || !buildingMesh || !dragPlane) return false;

    // Obliczamy pozycje myszy
    const rect = renderer.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1
    );

    // Rzucamy promien i szukamy przeciecia z plaszczyzna
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);

    const intersectPoint = new THREE.Vector3();
    raycaster.ray.intersectPlane(dragPlane, intersectPoint);

    if (intersectPoint) {
        // Przesuwamy budynek na nowa pozycje (z uwzglednieniem offsetu)
        buildingMesh.position.x = intersectPoint.x + dragOffset.x;
        buildingMesh.position.z = intersectPoint.z + dragOffset.z;
        // Nie zmieniamy position.y - budynek pozostaje na ziemi
    }

    return true;
}

/**
 * Obsluguje puszczenie przycisku myszy - konczy przeciaganie.
 * @returns {boolean} true jesli zakonczono przeciaganie
 */
export function handleMouseUp() {
    if (isDragging) {
        isDragging = false;
        return true;
    }
    return false;
}

/**
 * Sprawdza czy aktualnie trwa przeciaganie.
 * @returns {boolean}
 */
export function getIsDragging() {
    return isDragging;
}

/**
 * Ustawia pozycje budynku recznie (X, Z na plaszczyznie).
 * Przydatne gdy uzytkownik chce wpisac dokladna pozycje.
 * 
 * @param {THREE.Mesh} mesh - model budynku
 * @param {number} x - pozycja X (w metrach)
 * @param {number} z - pozycja Z (w metrach)
 */
export function setPosition(mesh, x, z) {
    if (!mesh) return;
    mesh.position.x = x;
    mesh.position.z = z;
}

/**
 * Zwraca aktualna pozycje budynku.
 * @param {THREE.Mesh} mesh - model budynku
 * @returns {{x: number, z: number}|null}
 */
export function getPosition(mesh) {
    if (!mesh) return null;
    return {
        x: Math.round(mesh.position.x * 100) / 100,
        z: Math.round(mesh.position.z * 100) / 100
    };
}
