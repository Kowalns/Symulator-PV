/**
 * stl-loader.js - Ladowanie i wyswietlanie plikow STL na scenie 3D
 *
 * Obsluguje format binarny STL (Dom.STL jest binarny).
 * Funkcje:
 * - loadSTLFromURL(url) - ladowanie z serwera (np. /models/Dom.STL)
 * - loadSTLFromFile(file) - ladowanie z dysku uzytkownika (File API)
 * - Auto-centrowanie modelu wzgledem geometrii
 * - Auto-skalowanie do rozsadnego rozmiaru na scenie
 * - Material Phong z cieniowaniem
 */

import { THREE, scene, focusOnObject } from './viewer3d.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

// Referencja do aktualnie wczytanego modelu
let currentModel = null;

// Loader STL z Three.js
const loader = new STLLoader();

// Element statusu
const statusEl = document.getElementById('stl-status');
const infoEl = document.getElementById('scene-info');

/**
 * Aktualizuje tekst statusu STL
 */
function setStatus(text, type = '') {
    if (statusEl) {
        statusEl.textContent = text;
        statusEl.className = 'status-text' + (type ? ' ' + type : '');
    }
}

/**
 * Wyswietla informacje o wczytanym modelu
 * Eksportuje wymiary do window.__stlBoundingBox aby non-module script mogl je odczytac
 */
function showModelInfo(geometry) {
    if (!infoEl) return;

    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    const size = new THREE.Vector3();
    box.getSize(size);

    // Przelicz wymiary na metry jesli sa w mm
    let sx = size.x, sy = size.y, sz = size.z;
    const maxRaw = Math.max(sx, sy, sz);
    if (maxRaw > 100) {
        sx /= 1000; sy /= 1000; sz /= 1000;
    }

    // Po ewentualnym obrocie Z-up -> Y-up: wysokosc to Y albo Z (mniejszy z nich)
    const wysokosc = Math.min(sy, sz);
    const szer = sx;
    const gleb = Math.max(sy, sz) === wysokosc ? Math.min(sy, sz) : Math.max(sy, sz);

    infoEl.innerHTML = `
        <strong>Model wczytany</strong><br>
        Trojkaty: ${geometry.attributes.position.count / 3}<br>
        Wymiary: ${szer.toFixed(1)} x ${(sy > sz ? sz : sy).toFixed(1)} x ${wysokosc.toFixed(1)} m
    `;

    // Eksportuj wymiary do globalnego obiektu - uzywane przez formularz budynku
    // Po obrocie (Z-up -> Y-up): X=szerokosc, Z=glebokosc, Y=wysokosc (w ukladzie Three.js)
    window.__stlBoundingBox = {
        szerokosc: parseFloat(szer.toFixed(1)),
        glebokosc: parseFloat((maxRaw > 100 ? Math.max(size.y, size.z)/1000 : Math.max(size.y, size.z)).toFixed(1)),
        wysokosc: parseFloat((maxRaw > 100 ? Math.min(size.y, size.z)/1000 : Math.min(size.y, size.z)).toFixed(1))
    };

    // Pre-fill pola formularza budynku (jesli istnieja)
    var budSzer = document.getElementById('bud-szerokosc');
    var budGleb = document.getElementById('bud-glebokosc');
    var budWys = document.getElementById('bud-wysokosc');
    if (budSzer) budSzer.value = window.__stlBoundingBox.szerokosc;
    if (budGleb) budGleb.value = window.__stlBoundingBox.glebokosc;
    if (budWys) budWys.value = window.__stlBoundingBox.wysokosc;
}

/**
 * Tworzy mesh z geometrii STL - material Phong z cieniowaniem.
 * Auto-centruje model (przesuwa do srodka geometrii).
 */
function createMeshFromGeometry(geometry) {
    // Usuniecie poprzedniego modelu
    if (currentModel) {
        scene.remove(currentModel);
        currentModel.geometry.dispose();
        currentModel.material.dispose();
        currentModel = null;
    }

    // Centrowanie geometrii
    geometry.computeBoundingBox();
    geometry.center();

    // Material Phong - ladne cieniowanie z odbiciami
    const material = new THREE.MeshPhongMaterial({
        color: 0xb0bec5,
        specular: 0x222222,
        shininess: 30,
        flatShading: false,
    });

    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // Wykrycie orientacji modelu i jednostek:
    // 1. Jesli wymiary > 100 to plik jest w milimetrach - skalujemy /1000
    // 2. W plikach CAD os Z jest czesto "gora" - wykrywamy i obracamy
    const boxCheck = new THREE.Box3().setFromObject(mesh);
    const sizeCheck = boxCheck.getSize(new THREE.Vector3());
    const maxDim = Math.max(sizeCheck.x, sizeCheck.y, sizeCheck.z);

    // Wykrycie milimetrow: jesli max wymiar > 100 to raczej mm, nie metry
    // (dom 20m = 20000mm; dom w metrach max ~30)
    if (maxDim > 100) {
        const scale = 1.0 / 1000.0;  // mm -> m
        mesh.scale.set(scale, scale, scale);
        mesh.updateMatrixWorld(true);
    }

    // Po przeskalowaniu sprawdz orientacje
    const boxAfterScale = new THREE.Box3().setFromObject(mesh);
    const sizeScaled = boxAfterScale.getSize(new THREE.Vector3());

    // Wykrycie Z-up: jesli Z jest NAJMNIEJSZYM wymiarem a jest "rozsadna wysokosc" (3-15m)
    // to Z to wysokosc i trzeba obrocic (Z-up -> Y-up w Three.js)
    // Albo odwrotnie: jesli Y jest wyraznie wieksze niz powinno byc na "wysokosc"
    // (wieksze niz X i Z) to model lezy na boku
    const minDimScaled = Math.min(sizeScaled.x, sizeScaled.y, sizeScaled.z);

    if (sizeScaled.z === minDimScaled && sizeScaled.z < sizeScaled.x * 0.6) {
        // Z jest najmniejszy i znacznie mniejszy niz X/Y = Z to wysokosc, trzeba obrocic
        mesh.rotation.x = -Math.PI / 2;
        mesh.updateMatrixWorld(true);
    } else if (sizeScaled.y > sizeScaled.x && sizeScaled.y > sizeScaled.z) {
        // Y jest najwiekszy wymiar - model "stoi na scianie" w Three.js
        mesh.rotation.x = -Math.PI / 2;
        mesh.updateMatrixWorld(true);
    }

    // Ustawienie modelu na plaszczyznie gruntu (Y=0)
    const finalBox = new THREE.Box3().setFromObject(mesh);
    mesh.position.y -= finalBox.min.y;

    scene.add(mesh);
    currentModel = mesh;

    // Wyswietl informacje i wycentruj kamere
    showModelInfo(geometry);
    focusOnObject(mesh);

    return mesh;
}

/**
 * Laduje plik STL z podanego URL (np. /models/Dom.STL z naszego serwera).
 */
function loadSTLFromURL(url) {
    setStatus('Ladowanie modelu...', '');

    return new Promise((resolve, reject) => {
        loader.load(
            url,
            (geometry) => {
                const mesh = createMeshFromGeometry(geometry);
                setStatus('Model wczytany pomyslnie', 'success');
                resolve(mesh);
            },
            (progress) => {
                if (progress.total > 0) {
                    const percent = Math.round((progress.loaded / progress.total) * 100);
                    setStatus(`Ladowanie: ${percent}%`, '');
                }
            },
            (error) => {
                setStatus(`Blad ladowania: ${error.message || error}`, 'error');
                reject(error);
            }
        );
    });
}

/**
 * Laduje plik STL z obiektu File (wybrany przez uzytkownika z dysku).
 */
function loadSTLFromFile(file) {
    setStatus('Wczytywanie pliku...', '');

    return new Promise((resolve, reject) => {
        const reader = new FileReader();

        reader.onload = (event) => {
            try {
                const geometry = loader.parse(event.target.result);
                const mesh = createMeshFromGeometry(geometry);
                setStatus(`Wczytano: ${file.name}`, 'success');
                resolve(mesh);
            } catch (error) {
                setStatus(`Blad parsowania STL: ${error.message}`, 'error');
                reject(error);
            }
        };

        reader.onerror = () => {
            setStatus('Blad odczytu pliku', 'error');
            reject(new Error('Nie udalo sie odczytac pliku'));
        };

        reader.readAsArrayBuffer(file);
    });
}

// --- Obsluga przyciskow w panelu ---

// Przycisk: Wczytaj domyslny model (Dom.STL z serwera)
const loadDefaultBtn = document.getElementById('load-default-stl');
if (loadDefaultBtn) {
    loadDefaultBtn.addEventListener('click', () => {
        loadSTLFromURL('/models/Dom.STL');
    });
}

// Input: Wczytaj plik STL z dysku
const fileInput = document.getElementById('stl-file-input');
if (fileInput) {
    fileInput.addEventListener('change', (event) => {
        const file = event.target.files[0];
        if (file) {
            loadSTLFromFile(file);
        }
    });
}

// Przycisk: Obroc model 90 stopni wokol osi X (poloz/postaw)
const rotateXBtn = document.getElementById('rotate-model-x');
if (rotateXBtn) {
    rotateXBtn.addEventListener('click', () => {
        if (!currentModel) return;
        currentModel.rotation.x += Math.PI / 2;
        currentModel.updateMatrixWorld(true);
        // Ponowne ustawienie na grunt
        const box = new THREE.Box3().setFromObject(currentModel);
        currentModel.position.y -= box.min.y;
        showModelInfo(currentModel.geometry);
    });
}

// Przycisk: Obroc model 90 stopni wokol osi Y (obrot w lewo/prawo)
const rotateZBtn = document.getElementById('rotate-model-z');
if (rotateZBtn) {
    rotateZBtn.addEventListener('click', () => {
        if (!currentModel) return;
        currentModel.rotation.y += Math.PI / 2;
        currentModel.updateMatrixWorld(true);
        // Ponowne ustawienie na grunt
        const box = new THREE.Box3().setFromObject(currentModel);
        currentModel.position.y -= box.min.y;
        showModelInfo(currentModel.geometry);
    });
}

// Suwak: Obrot budynku wokol osi pionowej (azymut - strony swiata)
const azymutSlider = document.getElementById('budynek-azymut-slider');
const azymutValue = document.getElementById('budynek-azymut-value');
let baseRotationY = 0; // bazowy obrot po ustawieniu modelu

if (azymutSlider) {
    azymutSlider.addEventListener('input', () => {
        if (!currentModel) return;
        const degrees = parseInt(azymutSlider.value);
        azymutValue.textContent = degrees;
        // Obrot wokol osi Y (pionowej w Three.js)
        currentModel.rotation.y = baseRotationY + (degrees * Math.PI / 180);
        currentModel.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(currentModel);
        currentModel.position.y -= box.min.y;
    });
}

// Eksport funkcji do uzytku przez inne moduly
export { loadSTLFromURL, loadSTLFromFile, currentModel };
