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

// Eksport obiektow sceny - inne moduly beda z nich korzystac
export { scene, camera, renderer, controls, container, groundPlane, focusOnObject };
export { THREE };
