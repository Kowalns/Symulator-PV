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

// --- System przeciagania obiektow (drag & drop) ---

/**
 * Rejestr obiektow ktore mozna przeciagac myszka.
 * Kazdy wpis: { object3d, onDrag(pozycja), onDragStart(), onDragEnd() }
 */
const draggableObjects = [];

/**
 * Rejestruje obiekt 3D jako "przeciagalny" na scenie.
 * @param {THREE.Object3D} object3d - obiekt do przeciagania
 * @param {Object} callbacks - { onDrag(pos), onDragStart(), onDragEnd() }
 */
function registerDraggable(object3d, callbacks = {}) {
    // Usun stary wpis jesli istnieje (np. po ponownym zaladowaniu modelu)
    const idx = draggableObjects.findIndex(d => d.object3d === object3d);
    if (idx !== -1) draggableObjects.splice(idx, 1);
    draggableObjects.push({
        object3d,
        onDrag: callbacks.onDrag || null,
        onDragStart: callbacks.onDragStart || null,
        onDragEnd: callbacks.onDragEnd || null,
    });
}

/**
 * Wyrejestrowuje obiekt z systemu przeciagania (np. po usunieciu ze sceny).
 */
function unregisterDraggable(object3d) {
    const idx = draggableObjects.findIndex(d => d.object3d === object3d);
    if (idx !== -1) draggableObjects.splice(idx, 1);
}

// Raycaster do wykrywania klikniec na obiekty
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

// Stan przeciagania
let isDragging = false;
let dragTarget = null;       // aktualnie przeciagany wpis z draggableObjects
let dragOffset = new THREE.Vector3(); // przesuniecie miedzy kursorem a srodkiem obiektu
let dragPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0); // plaszczyzna gruntu Y=0

// Zapamietanie oryginalnych kolorow emissive podswietlonego obiektu
let highlightedMeshes = [];

/**
 * Podswietla obiekt (ustawia emissive na jasny kolor).
 */
function highlightObject(object3d) {
    clearHighlight();
    object3d.traverse((child) => {
        if (child.isMesh && child.material) {
            const mat = child.material;
            if (mat.emissive) {
                highlightedMeshes.push({ mesh: child, originalEmissive: mat.emissive.getHex() });
                mat.emissive.setHex(0x444444);
            }
        }
    });
}

/**
 * Usuwa podswietlenie (przywraca oryginalne emissive).
 */
function clearHighlight() {
    for (const entry of highlightedMeshes) {
        if (entry.mesh.material && entry.mesh.material.emissive) {
            entry.mesh.material.emissive.setHex(entry.originalEmissive);
        }
    }
    highlightedMeshes = [];
}

/**
 * Oblicza pozycje myszy w ukladzie znormalizowanym (-1..1) wzgledem renderera.
 */
function updateMouse(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}

/**
 * Rzutuje pozycje myszy na plaszczyzne gruntu (Y=0).
 * Zwraca punkt przeciecia lub null.
 */
function getGroundIntersection() {
    raycaster.setFromCamera(mouse, camera);
    const intersection = new THREE.Vector3();
    const hit = raycaster.ray.intersectPlane(dragPlane, intersection);
    return hit ? intersection : null;
}

/**
 * Sprawdza czy kliknieto na ktorykolwiek z zarejestrowanych obiektow.
 * Zwraca wpis z draggableObjects lub null.
 */
function findDraggableUnderMouse() {
    raycaster.setFromCamera(mouse, camera);

    // Zbierz wszystkie meshe z zarejestrowanych obiektow
    for (const entry of draggableObjects) {
        const meshes = [];
        entry.object3d.traverse((child) => {
            if (child.isMesh) meshes.push(child);
        });
        const intersects = raycaster.intersectObjects(meshes, false);
        if (intersects.length > 0) {
            return entry;
        }
    }
    return null;
}

// --- Obsluga zdarzen myszy dla przeciagania ---

function onPointerDown(event) {
    // Tylko lewy przycisk myszy
    if (event.button !== 0) return;

    updateMouse(event);
    const target = findDraggableUnderMouse();

    if (target) {
        // Znaleziono obiekt do przeciagania
        isDragging = true;
        dragTarget = target;

        // Wylacz OrbitControls podczas przeciagania
        controls.enabled = false;

        // Podswietl obiekt
        highlightObject(target.object3d);

        // Oblicz offset: roznica miedzy pozycja obiektu a punktem klikniecia na gruncie
        const groundPoint = getGroundIntersection();
        if (groundPoint) {
            dragOffset.copy(target.object3d.position).sub(groundPoint);
            // Zachowaj Y obiektu (nie zmieniamy wysokosci)
            dragOffset.y = 0;
        }

        // Callback poczatku przeciagania
        if (target.onDragStart) target.onDragStart();

        event.preventDefault();
        event.stopPropagation();
    }
}

function onPointerMove(event) {
    if (!isDragging || !dragTarget) return;

    updateMouse(event);
    const groundPoint = getGroundIntersection();

    if (groundPoint) {
        // Przesun obiekt do nowej pozycji na gruncie (zachowujac Y)
        const newX = groundPoint.x + dragOffset.x;
        const newZ = groundPoint.z + dragOffset.z;

        dragTarget.object3d.position.x = newX;
        dragTarget.object3d.position.z = newZ;

        // Callback w trakcie przeciagania (np. aktualizacja formularza)
        if (dragTarget.onDrag) {
            dragTarget.onDrag({ x: newX, z: newZ });
        }
    }

    event.preventDefault();
}

function onPointerUp(event) {
    if (!isDragging) return;

    // Przywroc OrbitControls
    controls.enabled = true;

    // Usun podswietlenie
    clearHighlight();

    // Callback konca przeciagania
    if (dragTarget && dragTarget.onDragEnd) {
        dragTarget.onDragEnd();
    }

    isDragging = false;
    dragTarget = null;

    event.preventDefault();
}

// Podlaczenie zdarzen do renderera (canvas)
renderer.domElement.addEventListener('pointerdown', onPointerDown, false);
renderer.domElement.addEventListener('pointermove', onPointerMove, false);
renderer.domElement.addEventListener('pointerup', onPointerUp, false);

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
