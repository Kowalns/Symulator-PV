// ===========================
// Modul widoku 3D - Three.js
// Inicjalizacja sceny, kamery, swiatel, renderera i kontrolek OrbitControls
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { OrbitControls } from 'https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js';

// --- Zmienne globalne modulu ---
let scene, camera, renderer, controls;
let groundPlane; // plaszczyzna gruntu (ziemia)
let gridHelper; // siatka pomocnicza (zeby widziec skale)

/**
 * Inicjalizuje scene 3D - tworzy wszystko co potrzebne do wyswietlenia widoku 3D.
 * @param {HTMLElement} container - element HTML w ktorym ma byc renderowany widok 3D
 * @returns {Object} obiekt z referencjami do sceny, kamery, renderera i kontrolek
 */
export function initScene(container) {
    // --- Scena ---
    // Scena to "swiat 3D" w ktorym umieszczamy obiekty
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e); // ciemne tlo

    // --- Kamera ---
    // Kamera perspektywiczna - symuluje ludzkie widzenie (obiekty dalej sa mniejsze)
    const width = container.clientWidth;
    const height = container.clientHeight;
    camera = new THREE.PerspectiveCamera(
        60,             // kat widzenia (FOV) w stopniach
        width / height, // proporcje (aspect ratio)
        0.1,            // minimalna odleglosc renderowania
        10000           // maksymalna odleglosc renderowania
    );
    // Ustawiamy kamere w pozycji patrzacej z gory pod katem
    camera.position.set(30, 40, 30);
    camera.lookAt(0, 0, 0);

    // --- Renderer ---
    // Renderer zamienia scene 3D na obraz 2D widoczny na ekranie
    renderer = new THREE.WebGLRenderer({ antialias: true }); // antialias = wygladzanie krawedzi
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio); // ostrosc na ekranach Retina
    renderer.shadowMap.enabled = true; // wlaczamy cienie
    container.appendChild(renderer.domElement);

    // --- Swiatla ---
    // Swiatlo otoczenia (ambient) - delikatne swiatlo ze wszystkich stron
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);

    // Swiatlo kierunkowe (jak slonce) - daje cienie
    const directionalLight = new THREE.DirectionalLight(0xffffff, 1.0);
    directionalLight.position.set(50, 80, 50);
    directionalLight.castShadow = true;
    directionalLight.shadow.mapSize.width = 2048;
    directionalLight.shadow.mapSize.height = 2048;
    scene.add(directionalLight);

    // Drugie slabsze swiatlo z drugiej strony (zeby nie bylo calkiem ciemno)
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-30, 40, -30);
    scene.add(fillLight);

    // --- Plaszczyzna gruntu ---
    // Siatka (grid) na ziemi - pomaga zobaczyc skale i orientacje
    gridHelper = new THREE.GridHelper(
        100,    // rozmiar siatki (100 x 100 metrow)
        100,    // ilosc podzialek (co 1 metr)
        0x444466, // kolor glownych linii
        0x333355  // kolor drugorzednych linii
    );
    scene.add(gridHelper);

    // Niewidoczna plaszczyzna do wykrywania klikniec (raycasting)
    const planeGeometry = new THREE.PlaneGeometry(200, 200);
    const planeMaterial = new THREE.MeshBasicMaterial({
        visible: false,
        side: THREE.DoubleSide
    });
    groundPlane = new THREE.Mesh(planeGeometry, planeMaterial);
    groundPlane.rotation.x = -Math.PI / 2; // obracamy zeby lezala plasko
    groundPlane.position.y = 0;
    scene.add(groundPlane);

    // --- OrbitControls ---
    // Kontrolki do obracania, przybilzania i przesuwania widoku myszka
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;  // plynne wygaszanie ruchu
    controls.dampingFactor = 0.1;
    controls.minDistance = 2;       // minimalne przyblizenie
    controls.maxDistance = 500;     // maksymalne oddalenie
    controls.maxPolarAngle = Math.PI / 2 - 0.01; // nie pozwalamy kamery pod ziemie

    // --- Petla renderowania ---
    // Funkcja wywolywana ~60 razy na sekunde - odswierza widok
    function animate() {
        requestAnimationFrame(animate);
        controls.update(); // aktualizacja kontrolek (potrzebne dla damping)
        renderer.render(scene, camera);
    }
    animate();

    // --- Zmiana rozmiaru okna ---
    // Kiedy uzytkownik zmienia rozmiar okna, dostosowujemy widok
    window.addEventListener('resize', () => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
    });

    return { scene, camera, renderer, controls, groundPlane };
}

/**
 * Zwraca referencje do sceny Three.js
 */
export function getScene() {
    return scene;
}

/**
 * Zwraca referencje do kamery
 */
export function getCamera() {
    return camera;
}

/**
 * Zwraca referencje do kontrolek orbit
 */
export function getControls() {
    return controls;
}

/**
 * Zwraca referencje do plaszczyzny gruntu (do wykrywania klikniec)
 */
export function getGroundPlane() {
    return groundPlane;
}

/**
 * Zwraca referencje do renderera
 */
export function getRenderer() {
    return renderer;
}

/**
 * Centruje kamere na podanym obiekcie 3D (np. zaladowanym modelu STL).
 * Automatycznie dobiera odleglosc kamery zeby obiekt byl dobrze widoczny.
 * @param {THREE.Object3D} object - obiekt 3D na ktorym chcemy skupic kamere
 */
export function focusOnObject(object) {
    // Obliczamy "bounding box" - prostopadloscian otaczajacy caly obiekt
    const box = new THREE.Box3().setFromObject(object);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());

    // Najwiekszy wymiar obiektu
    const maxDim = Math.max(size.x, size.y, size.z);
    // Odleglosc kamery - wystarczajaca zeby widziec caly obiekt
    const distance = maxDim * 2.5;

    // Ustawiamy punkt na ktory patrzy kamera
    controls.target.copy(center);

    // Ustawiamy pozycje kamery
    camera.position.set(
        center.x + distance * 0.5,
        center.y + distance * 0.7,
        center.z + distance * 0.5
    );

    controls.update();
}
