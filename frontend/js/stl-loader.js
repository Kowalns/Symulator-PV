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

import { THREE, scene, focusOnObject, unregisterDraggable } from './viewer3d.js';
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
    // Usuniecie poprzedniego modelu (grupy)
    if (currentModel) {
        unregisterDraggable(currentModel);
        scene.remove(currentModel);
        // Usun meshe wewnatrz grupy
        currentModel.traverse((child) => {
            if (child.isMesh) {
                child.geometry.dispose();
                child.material.dispose();
            }
        });
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

    // Opakowujemy mesh w grupe - zeby moc niezaleznie obracac:
    // - mesh.rotation.x = korekcja orientacji (Z-up -> Y-up)
    // - group.rotation.y = azymut (strony swiata) - obraca wokol pionu
    const group = new THREE.Group();
    group.add(mesh);

    // Wykrycie orientacji modelu i jednostek:
    const boxCheck = new THREE.Box3().setFromObject(mesh);
    const sizeCheck = boxCheck.getSize(new THREE.Vector3());
    const maxDim = Math.max(sizeCheck.x, sizeCheck.y, sizeCheck.z);

    // Wykrycie milimetrow: jesli max wymiar > 100 to raczej mm, nie metry
    if (maxDim > 100) {
        const scale = 1.0 / 1000.0;  // mm -> m
        mesh.scale.set(scale, scale, scale);
        mesh.updateMatrixWorld(true);
    }

    // Po przeskalowaniu sprawdz orientacje
    const boxAfterScale = new THREE.Box3().setFromObject(mesh);
    const sizeScaled = boxAfterScale.getSize(new THREE.Vector3());

    // Wykrycie Z-up i obrót korekcyjny na MESHU (nie na grupie)
    const minDimScaled = Math.min(sizeScaled.x, sizeScaled.y, sizeScaled.z);

    if (sizeScaled.z === minDimScaled && sizeScaled.z < sizeScaled.x * 0.6) {
        mesh.rotation.x = -Math.PI / 2;
        mesh.updateMatrixWorld(true);
    } else if (sizeScaled.y > sizeScaled.x && sizeScaled.y > sizeScaled.z) {
        mesh.rotation.x = -Math.PI / 2;
        mesh.updateMatrixWorld(true);
    }

    // Ustawienie grupy na plaszczyznie gruntu (Y=0)
    const finalBox = new THREE.Box3().setFromObject(group);
    group.position.y -= finalBox.min.y;

    scene.add(group);
    currentModel = group;  // grupa jest "modelem" do przesuwania i obracania

    // Pozycja budynku z hidden inputs bud-x/bud-z (obliczona przez API)
    const budXInput = document.getElementById('bud-x');
    const budZInput = document.getElementById('bud-z');
    if (budXInput) {
        const bx = parseFloat(budXInput.value);
        if (!isNaN(bx)) group.position.x = bx;
    }
    if (budZInput) {
        const bz = parseFloat(budZInput.value);
        if (!isNaN(bz)) group.position.z = bz;
    }

    // Wyswietl informacje i wycentruj kamere
    showModelInfo(geometry);
    focusOnObject(group);

    return group;
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
        // Obracamy mesh wewnatrz grupy (korekcja orientacji)
        const mesh = currentModel.children[0];
        if (mesh) {
            mesh.rotation.x += Math.PI / 2;
            mesh.updateMatrixWorld(true);
        }
        // Ponowne ustawienie grupy na grunt
        const box = new THREE.Box3().setFromObject(currentModel);
        currentModel.position.y -= box.min.y;
        if (currentModel.children[0]) showModelInfo(currentModel.children[0].geometry);
    });
}

// Przycisk: Obroc model 90 stopni wokol osi Y (obrot w lewo/prawo)
const rotateZBtn = document.getElementById('rotate-model-z');
if (rotateZBtn) {
    rotateZBtn.addEventListener('click', () => {
        if (!currentModel) return;
        // Obrot wokol osi Y na GRUPIE (azymut)
        currentModel.rotation.y += Math.PI / 2;
        currentModel.updateMatrixWorld(true);
        const box = new THREE.Box3().setFromObject(currentModel);
        currentModel.position.y -= box.min.y;
    });
}

// Suwak: Obrot budynku wokol osi pionowej (azymut - strony swiata)
const azymutSlider = document.getElementById('budynek-azymut-slider');
const azymutValue = document.getElementById('budynek-azymut-value');

if (azymutSlider) {
    azymutSlider.addEventListener('input', () => {
        if (!currentModel) return;
        const degrees = parseInt(azymutSlider.value);
        azymutValue.textContent = degrees;
        // Obrot wokol osi Y na GRUPIE (nie na meshu) - obraca poprawnie wokol pionu
        currentModel.rotation.y = degrees * Math.PI / 180;
        currentModel.updateMatrixWorld(true);
        // Nie trzeba poprawiac Y bo obrot wokol pionu nie zmienia wysokosci
    });
}

// === Nasluchiwanie zmian pola bud-x/bud-z aby przesunac model 3D ===
// Gdy uzytkownik zmienia odleglosc od granic, przeliczPozycje() aktualizuje bud-x/bud-z
// i dispatcha event 'input' - tutaj reagujemy przesuwajac model na scenie.
const budXInput = document.getElementById('bud-x');
const budZInput = document.getElementById('bud-z');

function przesunModelDoHiddenInputs() {
    // Flaga zapobiegajaca petli: zmiana pola -> przesuniecie -> drag callback -> zmiana pola
    if (window.__aktualizacjaBudynkuWToku) return;
    if (!currentModel) return;

    window.__aktualizacjaBudynkuWToku = true;

    const nowyX = parseFloat(budXInput?.value);
    const nowyZ = parseFloat(budZInput?.value);

    if (!isNaN(nowyX)) currentModel.position.x = nowyX;
    if (!isNaN(nowyZ)) currentModel.position.z = nowyZ;

    window.__aktualizacjaBudynkuWToku = false;
}

if (budXInput) {
    budXInput.addEventListener('input', przesunModelDoHiddenInputs);
    budXInput.addEventListener('change', przesunModelDoHiddenInputs);
}
if (budZInput) {
    budZInput.addEventListener('input', przesunModelDoHiddenInputs);
    budZInput.addEventListener('change', przesunModelDoHiddenInputs);
}

// Eksport funkcji do uzytku przez inne moduly
export { loadSTLFromURL, loadSTLFromFile, currentModel };
