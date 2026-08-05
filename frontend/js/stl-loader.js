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
 */
function showModelInfo(geometry) {
    if (!infoEl) return;

    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    const size = new THREE.Vector3();
    box.getSize(size);

    infoEl.innerHTML = `
        <strong>Model wczytany</strong><br>
        Trojkaty: ${geometry.attributes.position.count / 3}<br>
        Wymiary: ${size.x.toFixed(1)} x ${size.y.toFixed(1)} x ${size.z.toFixed(1)} m
    `;
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

    // Auto-skalowanie jesli model jest za duzy lub za maly
    const box = new THREE.Box3().setFromObject(mesh);
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);

    // Docelowy rozmiar: okolo 20 jednostek (metrow)
    if (maxDim > 100 || maxDim < 1) {
        const scale = 20 / maxDim;
        mesh.scale.set(scale, scale, scale);
    }

    // Ustawienie modelu na plaszczyznie gruntu (Y=0)
    const scaledBox = new THREE.Box3().setFromObject(mesh);
    mesh.position.y -= scaledBox.min.y;

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

// Eksport funkcji do uzytku przez inne moduly
export { loadSTLFromURL, loadSTLFromFile, currentModel };
