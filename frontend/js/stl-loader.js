// ===========================
// Modul ladowania plikow STL
// Parsuje pliki STL (ASCII i binarne) i tworzy z nich obiekty 3D
//
// STL to popularny format plikow 3D - przechowuje ksztalt jako zbior trojkatow.
// Kazdy trojkat (face/sciana) ma 3 wierzcholki (verteksy) i wektor normalny.
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { STLLoader } from 'https://unpkg.com/three@0.160.0/examples/jsm/loaders/STLLoader.js';

// Zmienna przechowujaca aktualnie zaladowany model
let currentModel = null;

/**
 * Laduje plik STL wybrany przez uzytkownika i dodaje go do sceny 3D.
 * 
 * Jak to dziala:
 * 1. Uzytkownik wybiera plik przez <input type="file">
 * 2. FileReader czyta zawartosc pliku (jako ArrayBuffer - surowe bajty)
 * 3. STLLoader z Three.js parsuje bajty i tworzy geometrie (zbior trojkatow)
 * 4. Tworzymy material (kolor/wyglad) i mesh (polaczenie geometrii z materialem)
 * 5. Dodajemy mesh do sceny 3D
 * 
 * @param {File} file - plik STL wybrany przez uzytkownika
 * @param {THREE.Scene} scene - scena Three.js do ktorej dodajemy model
 * @param {Function} onSuccess - funkcja wywolywana po udanym zaladowaniu (dostaje mesh)
 * @param {Function} onError - funkcja wywolywana w razie bledu
 */
export function loadSTLFile(file, scene, onSuccess, onError) {
    // Sprawdzamy czy plik ma rozszerzenie .stl
    if (!file.name.toLowerCase().endsWith('.stl')) {
        onError('Wybrany plik nie jest plikiem STL. Wybierz plik z rozszerzeniem .stl');
        return;
    }

    // FileReader - obiekt do czytania plikow z dysku uzytkownika
    const reader = new FileReader();

    // Co robimy po przeczytaniu pliku
    reader.onload = function(event) {
        try {
            const contents = event.target.result; // surowe dane pliku (ArrayBuffer)

            // STLLoader z Three.js - parsuje dane STL na geometrie
            const loader = new STLLoader();
            const geometry = loader.parse(contents);

            // Usuwamy stary model jesli jakis byl zaladowany wczesniej
            if (currentModel) {
                scene.remove(currentModel);
                currentModel.geometry.dispose();
                currentModel.material.dispose();
                currentModel = null;
            }

            // --- Centrowanie modelu ---
            // Obliczamy srodek geometrii i przesuwamy ja tak, zeby srodek byl w punkcie (0,0,0)
            geometry.computeBoundingBox();
            const boundingBox = geometry.boundingBox;
            const center = new THREE.Vector3();
            boundingBox.getCenter(center);
            geometry.translate(-center.x, -center.y, -center.z);

            // Przesuwamy model tak zeby "stal" na ziemi (dolna krawedz na y=0)
            geometry.computeBoundingBox(); // przeliczamy po przesunieciu
            const minY = geometry.boundingBox.min.y;
            geometry.translate(0, -minY, 0);

            // --- Skalowanie ---
            // Sprawdzamy rozmiar modelu i skalujemy go zeby mial sensowny rozmiar w scenie
            geometry.computeBoundingBox();
            const size = new THREE.Vector3();
            geometry.boundingBox.getSize(size);
            const maxDimension = Math.max(size.x, size.y, size.z);

            // Docelowy rozmiar - okolo 20 jednostek (metrow w naszej scenie)
            const targetSize = 20;
            let scaleFactor = 1;
            if (maxDimension > 0) {
                scaleFactor = targetSize / maxDimension;
            }

            // --- Material ---
            // Material okreslajacy wyglad modelu (kolor, polyskowosc itp.)
            const material = new THREE.MeshPhongMaterial({
                color: 0xcc8844,        // kolor ceglasty (jak dom)
                specular: 0x222222,     // kolor odblaskow
                shininess: 30,          // polyskowosc (0 = matowy, 100 = lsniacy)
                flatShading: true       // ostre krawedzie (typowe dla modeli STL)
            });

            // --- Mesh ---
            // Mesh = geometria (ksztalt) + material (wyglad) razem
            const mesh = new THREE.Mesh(geometry, material);
            mesh.scale.set(scaleFactor, scaleFactor, scaleFactor);
            mesh.castShadow = true;    // obiekt rzuca cien
            mesh.receiveShadow = true; // obiekt przyjmuje cienie
            mesh.name = 'stl-model';   // nazwa do identyfikacji

            // Dodajemy do sceny
            scene.add(mesh);
            currentModel = mesh;

            // Wywolujemy callback sukcesu
            onSuccess(mesh);

        } catch (error) {
            onError('Blad podczas parsowania pliku STL: ' + error.message);
        }
    };

    // Obsluga bledu odczytu pliku
    reader.onerror = function() {
        onError('Nie udalo sie odczytac pliku. Sprawdz czy plik nie jest uszkodzony.');
    };

    // Rozpoczynamy czytanie pliku jako ArrayBuffer (surowe bajty)
    reader.readAsArrayBuffer(file);
}

/**
 * Usuwa aktualnie zaladowany model STL ze sceny.
 * @param {THREE.Scene} scene - scena Three.js
 */
export function removeCurrentModel(scene) {
    if (currentModel) {
        scene.remove(currentModel);
        currentModel.geometry.dispose();
        currentModel.material.dispose();
        currentModel = null;
    }
}

/**
 * Zwraca aktualnie zaladowany model (lub null jesli brak).
 * @returns {THREE.Mesh|null}
 */
export function getCurrentModel() {
    return currentModel;
}
