/**
 * viewer3d.js - Inicjalizacja i zarzadzanie scena Three.js
 *
 * Odpowiada za:
 * - Tworzenie sceny 3D (kamera, swiatla, renderer)
 * - OrbitControls (obracanie kamery myszka)
 * - Siatka gruntu (GridHelper) jako punkt odniesienia
 * - Responsywnosc (dostosowanie do rozmiaru okna)
 * - Eksport globalnych obiektow sceny do uzytku przez inne moduly
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Elementy DOM
const container = document.getElementById('canvas-container');

// Scena Three.js
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1a2e);

// Kamera perspektywiczna
const camera = new THREE.PerspectiveCamera(
    60,                                         // Kat widzenia (FOV)
    container.clientWidth / container.clientHeight, // Proporcje
    0.1,                                        // Bliska plaszczyzna obciecia
    10000                                       // Daleka plaszczyzna obciecia
);
camera.position.set(30, 25, 30);
camera.lookAt(0, 0, 0);

// Renderer WebGL
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setPixelRatio(window.devicePixelRatio);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
container.appendChild(renderer.domElement);

// OrbitControls - obracanie, przybliżanie, przesuwanie kamery myszka
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;          // Plynne zatrzymywanie
controls.dampingFactor = 0.08;
controls.screenSpacePanning = true;     // Przesuwanie w plaszczyznie ekranu
controls.minDistance = 2;
controls.maxDistance = 500;
controls.maxPolarAngle = Math.PI / 2;   // Nie pozwol zejsc pod ziemie

// Swiatla
const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
scene.add(ambientLight);

const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
directionalLight.position.set(50, 80, 50);
directionalLight.castShadow = true;
directionalLight.shadow.mapSize.width = 2048;
directionalLight.shadow.mapSize.height = 2048;
directionalLight.shadow.camera.near = 0.5;
directionalLight.shadow.camera.far = 200;
directionalLight.shadow.camera.left = -50;
directionalLight.shadow.camera.right = 50;
directionalLight.shadow.camera.top = 50;
directionalLight.shadow.camera.bottom = -50;
scene.add(directionalLight);

// Dodatkowe swiatlo z drugiej strony (zeby model nie byl ciemny z tylu)
const fillLight = new THREE.DirectionalLight(0x4fc3f7, 0.3);
fillLight.position.set(-30, 20, -30);
scene.add(fillLight);

// Siatka gruntu - sluzy jako punkt odniesienia
const gridHelper = new THREE.GridHelper(100, 50, 0x0f3460, 0x0a2040);
scene.add(gridHelper);

// Plaszczyzna gruntu (niewidoczna, do raycastingu przy rysowaniu)
const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

// Petla renderowania
function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
}
animate();

// Responsywnosc - dostosowanie do zmiany rozmiaru okna
function onResize() {
    const width = container.clientWidth;
    const height = container.clientHeight;

    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
}
window.addEventListener('resize', onResize);

// Obserwator zmian rozmiaru kontenera (np. po otwarciu/zamknieciu panelu)
if (typeof ResizeObserver !== 'undefined') {
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(container);
}

/**
 * Centruje kamere na podanym obiekcie 3D.
 * Ustawia controls.target na srodek obiektu i dostosowuje odleglosc.
 */
function focusOnObject(object3d) {
    const box = new THREE.Box3().setFromObject(object3d);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());

    const maxDim = Math.max(size.x, size.y, size.z);
    const distance = maxDim * 2.5;

    controls.target.copy(center);
    camera.position.set(
        center.x + distance * 0.7,
        center.y + distance * 0.5,
        center.z + distance * 0.7
    );
    controls.update();
}

// --- Drag & drop usuniety - pozycjonowanie wylacznie przez odleglosci od granic ---

/**
 * Stub: registerDraggable - juz nie rejestruje przeciagania.
 * Zachowany dla kompatybilnosci importow.
 */
function registerDraggable(object3d, callbacks = {}) {
    // no-op: drag & drop usuniety, pozycja z API /api/parcel/position
}

/**
 * Stub: unregisterDraggable - juz nie wyrejestrowuje.
 */
function unregisterDraggable(object3d) {
    // no-op
}

// Eksport obiektow sceny - inne moduly beda z nich korzystac
export { scene, camera, renderer, controls, container, groundPlane, focusOnObject };
export { THREE };
export { registerDraggable, unregisterDraggable };

/**
 * Grupa 3D przechowujaca panele PV na scenie.
 * Usuwana i odtwarzana przy kazdej zmianie konfiguracji.
 */
let panelsGroup = null;

/**
 * Renderuje panele PV na scenie 3D na podstawie danych z backendu.
 *
 * Parametry:
 *   layoutData - obiekt z API /api/installation/configure zawierajacy:
 *     .panele[] - lista pozycji paneli (x, y, z, szerokosc_m, wysokosc_m, kat_nachylenia)
 *     .config.kat_nachylenia - kat nachylenia
 *
 * Kazdy panel rysowany jest jako plaski prostopadloscian (BoxGeometry)
 * w kolorze ciemnoniebieskim, nachylony pod odpowiednim katem.
 */
function renderPanels(layoutData) {
    // Usun poprzednie panele z sceny
    if (panelsGroup) {
        unregisterDraggable(panelsGroup);
        scene.remove(panelsGroup);
        panelsGroup.traverse((child) => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
        });
    }

    panelsGroup = new THREE.Group();
    panelsGroup.name = "panele_pv";

    if (!layoutData || !layoutData.panele || layoutData.panele.length === 0) {
        return;
    }

    // Material panela - ciemnoniebieski z polyskiem (symulacja szkla)
    const panelMaterial = new THREE.MeshPhongMaterial({
        color: 0x1a237e,
        specular: 0x4fc3f7,
        shininess: 60,
        side: THREE.DoubleSide,
    });

    // Material ramki panela
    const frameMaterial = new THREE.MeshPhongMaterial({
        color: 0x424242,
        shininess: 30,
    });

    const kat_rad = THREE.MathUtils.degToRad(layoutData.panele[0].kat_nachylenia);

    for (const panelData of layoutData.panele) {
        const panelGroup = new THREE.Group();

        // Grubosc panela (ok 3.5 cm)
        const grubosc = 0.035;

        // Geometria panela (plaska plytka)
        const geometry = new THREE.BoxGeometry(
            panelData.szerokosc_m,
            panelData.wysokosc_m,
            grubosc
        );

        const panelMesh = new THREE.Mesh(geometry, panelMaterial);
        panelMesh.castShadow = true;
        panelMesh.receiveShadow = true;
        panelGroup.add(panelMesh);

        // Ramka panela (nieco wieksza, cienka)
        const frameGeometry = new THREE.BoxGeometry(
            panelData.szerokosc_m + 0.04,
            panelData.wysokosc_m + 0.04,
            grubosc + 0.005
        );
        const frameMesh = new THREE.Mesh(frameGeometry, frameMaterial);
        frameMesh.position.z = -0.003;
        panelGroup.add(frameMesh);

        // Panel jest nachylony: obracamy go wokol osi X
        // W Three.js: rotacja X obraca wokol lokalnej osi X
        // Panel leza poczatkowo w plaszczyznie XY, nachylamy go
        panelGroup.rotation.x = -(Math.PI / 2 - kat_rad);

        // Pozycja panela (dane z backendu w metrach)
        panelGroup.position.set(panelData.x, panelData.y, panelData.z);

        panelsGroup.add(panelGroup);
    }

    // Ustaw pozycje grupy paneli z hidden inputs panel-pos-x / panel-pos-z
    const panelPosXEl = document.getElementById('panel-pos-x');
    const panelPosZEl = document.getElementById('panel-pos-z');
    if (panelPosXEl) {
        const px = parseFloat(panelPosXEl.value);
        if (!isNaN(px)) panelsGroup.position.x = px;
    }
    if (panelPosZEl) {
        const pz = parseFloat(panelPosZEl.value);
        if (!isNaN(pz)) panelsGroup.position.z = pz;
    }

    scene.add(panelsGroup);
}

/**
 * Usuwa panele PV ze sceny.
 */
function clearPanels() {
    if (panelsGroup) {
        // Wyrejestruj z systemu przeciagania
        unregisterDraggable(panelsGroup);
        scene.remove(panelsGroup);
        panelsGroup.traverse((child) => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) child.material.dispose();
        });
        panelsGroup = null;
    }
}

export { renderPanels, clearPanels };
