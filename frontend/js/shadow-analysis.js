// ===========================
// Modul analizy zacienienia paneli PV (shadow-analysis.js)
//
// Ten modul oblicza ile energii tracimy przez zacienienie paneli
// fotowoltaicznych w skali roku. Algorytm:
// 1. Dla kazdego dnia roku (co 5 dni = 73 probki)
//    i kazdej godziny dnia (6:00-20:00 co 1h = 15 probek):
//    - Oblicz pozycje slonca (azymut i elewacja)
//    - Jesli slonce jest pod horyzontem - pomijamy
//    - Rzuc promien od pozycji panela W KIERUNKU slonca
//    - Jesli promien trafia w budynek = panel jest zacieniony
//    - Waz wynik irradiacja (wyzsze slonce = wiecej energii)
// 2. Zagreguj wyniki: procent energii utraconej przez zacienienie
//    miesiecznie i rocznie.
//
// Obliczenia sa podzielone na chunki (porcje) z setTimeout,
// zeby nie blokowac interfejsu uzytkownika (przegladarka
// nie zamraza sie podczas dlugich obliczen).
//
// Eksportowane funkcje:
// - analyzeShadowImpact(...) - uruchamia pelna analize (async)
// - getMonthlyLosses() - zwraca tablice 12 strat miesiecznych (%)
// - getAnnualLoss() - zwraca roczna strate (%)
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';
import { calculateSunPosition, isDaylight } from './sun-position.js';

// --- Stale konfiguracyjne ---

// Co ile dni roku probkujemy (5 = 73 probki w roku)
const DAY_STEP = 5;

// Zakres godzin do analizy (6:00 - 20:00 wlacznie)
const HOUR_START = 6;
const HOUR_END = 20;

// Ile dni przetwarzamy w jednym chunku (porcji)
// Wiecej = szybciej, ale interfejs moze lagowac
const CHUNK_SIZE = 10;

// --- Stan modulu (wyniki ostatniej analizy) ---
let monthlyLosses = new Array(12).fill(0);
let annualLoss = 0;
let isRunning = false;

/**
 * Oblicza wage irradiacji na podstawie elewacji slonca.
 *
 * Im wyzej slonce na niebie, tym wiecej energii dociera do panela.
 * Uzywamy prostego modelu: energia ~ sin(elewacja).
 * Przy elewacji 90 stopni (slonce w zenicie) energia jest maksymalna.
 * Przy elewacji 0 stopni (horyzont) energia jest minimalna.
 *
 * @param {number} elevation - elewacja slonca w stopniach (0-90)
 * @returns {number} waga irradiacji (0-1)
 */
function getIrradianceWeight(elevation) {
    // sin(elevation) daje wartosc od 0 (horyzont) do 1 (zenit)
    // To przyblizenie modelu "air mass" - im nizej slonce,
    // tym wieksza droga promieni przez atmosfere i mniej energii
    const elevRad = elevation * (Math.PI / 180);
    return Math.max(0, Math.sin(elevRad));
}

/**
 * Oblicza kierunek od panela DO slonca jako wektor 3D.
 *
 * Zeby sprawdzic czy panel jest zacieniony, rzucamy promien
 * z pozycji panela w kierunku slonca. Jesli promien trafia
 * w budynek po drodze - panel jest zacieniony.
 *
 * Konwencja kierunkow (Three.js):
 * - Y = gora (pion)
 * - Azymut 0 = polnoc = kierunek +Z
 * - Azymut 90 = wschod = kierunek +X
 * - Azymut 180 = poludnie = kierunek -Z
 * - Azymut 270 = zachod = kierunek -X
 *
 * @param {number} elevation - elewacja slonca w stopniach
 * @param {number} azimuth - azymut slonca w stopniach (0-360)
 * @returns {THREE.Vector3} znormalizowany wektor kierunku do slonca
 */
function getDirectionToSun(elevation, azimuth) {
    const elevRad = elevation * (Math.PI / 180);
    const azRad = azimuth * (Math.PI / 180);

    // Skladowa pionowa (Y) - im wyzsze slonce, tym bardziej w gore
    const y = Math.sin(elevRad);

    // Rzut na plaszczyzne pozioma
    const horizontal = Math.cos(elevRad);

    // Skladowa X (wschod-zachod) = horizontal * sin(azymut)
    const x = horizontal * Math.sin(azRad);

    // Skladowa Z (polnoc-poludnie) = horizontal * cos(azymut)
    const z = horizontal * Math.cos(azRad);

    // Normalizujemy wektor (dlugosc = 1)
    const direction = new THREE.Vector3(x, y, z);
    direction.normalize();
    return direction;
}

/**
 * Sprawdza czy panel jest zacieniony w danym momencie.
 *
 * Rzuca promien (ray) z pozycji panela w kierunku slonca.
 * Jesli promien trafia w budynek (mesh) po drodze - panel jest zacieniony.
 *
 * @param {THREE.Raycaster} raycaster - obiekt do rzucania promieni
 * @param {THREE.Vector3} panelPosition - pozycja panela w przestrzeni 3D
 * @param {THREE.Vector3} directionToSun - kierunek do slonca (znormalizowany)
 * @param {THREE.Mesh} buildingMesh - model budynku (przeszkoda)
 * @returns {boolean} true jesli panel jest zacieniony (promien trafia w budynek)
 */
function isPanelShaded(raycaster, panelPosition, directionToSun, buildingMesh) {
    // Ustawiamy poczatek promienia na pozycje panela
    // (przesuwamy lekko w gore zeby promien nie startował z wnetrza ziemi)
    const origin = panelPosition.clone();
    origin.y += 0.1; // maly offset w gore

    // Ustawiamy raycaster - punkt startu i kierunek
    raycaster.set(origin, directionToSun);

    // Sprawdzamy czy promien trafia w budynek
    // intersectObject zwraca tablice punktow przeciecia
    const intersects = raycaster.intersectObject(buildingMesh, true);

    // Jesli sa jakies przeciecia - panel jest zacieniony
    return intersects.length > 0;
}

/**
 * Przetwarza jeden chunk (porcje) dni roku.
 *
 * Dla kazdego dnia w chunku i kazdej godziny dnia:
 * - Oblicza pozycje slonca
 * - Sprawdza zacienienie
 * - Akumuluje wyniki
 *
 * @param {object} params - parametry analizy
 * @param {number} params.lat - szerokosc geograficzna
 * @param {number} params.lon - dlugosc geograficzna
 * @param {THREE.Mesh} params.buildingMesh - model budynku
 * @param {THREE.Vector3} params.panelPosition - pozycja panela
 * @param {THREE.Raycaster} params.raycaster - obiekt raycaster
 * @param {number[]} params.days - tablica dni roku do przetworzenia
 * @param {number[]} params.monthlyShaded - akumulator: energia zacieniona na miesiac
 * @param {number[]} params.monthlyTotal - akumulator: energia calkowita na miesiac
 * @returns {{monthlyShaded: number[], monthlyTotal: number[]}} zaktualizowane akumulatory
 */
function processChunk(params) {
    const { lat, lon, buildingMesh, panelPosition, raycaster, days,
            monthlyShaded, monthlyTotal } = params;

    for (const dayOfYear of days) {
        // Tworzymy date dla tego dnia roku (rok 2024 - rok przestepny, obejmuje 366 dni)
        const date = new Date(2024, 0, 1);
        date.setDate(date.getDate() + dayOfYear - 1);
        const month = date.getMonth(); // 0-11

        // Dla kazdej godziny dnia (6:00 - 20:00)
        for (let hour = HOUR_START; hour <= HOUR_END; hour++) {
            // Ustawiamy godzine
            const sunDate = new Date(2024, date.getMonth(), date.getDate(), hour, 0, 0);

            // Obliczamy pozycje slonca
            const sunPos = calculateSunPosition(lat, lon, sunDate);

            // Pomijamy jesli noc (slonce pod horyzontem)
            if (!isDaylight(sunPos.elevation)) {
                continue;
            }

            // Waga irradiacji - wyzsze slonce = wiecej energii
            const weight = getIrradianceWeight(sunPos.elevation);

            // Dodajemy do calkowitej energii tego miesiaca
            monthlyTotal[month] += weight;

            // Sprawdzamy zacienienie
            const dirToSun = getDirectionToSun(sunPos.elevation, sunPos.azimuth);
            const shaded = isPanelShaded(raycaster, panelPosition, dirToSun, buildingMesh);

            if (shaded) {
                // Panel jest zacieniony - dodajemy stracona energie
                monthlyShaded[month] += weight;
            }
        }
    }

    return { monthlyShaded, monthlyTotal };
}

/**
 * Glowna funkcja analizy zacienienia paneli PV.
 *
 * Oblicza ile energii tracimy przez zacienienie w skali roku.
 * Algorytm probkuje kazdy dzien roku (co 5 dni) i kazda godzine dnia
 * (6:00-20:00), sprawdzajac czy promien sloneczny dociera do panela
 * czy jest blokowany przez budynek.
 *
 * Obliczenia sa podzielone na chunki (porcje) z setTimeout,
 * zeby nie blokowac interfejsu uzytkownika.
 *
 * @param {number} lat - szerokosc geograficzna (stopnie, N dodatnie)
 * @param {number} lon - dlugosc geograficzna (stopnie, E dodatnie)
 * @param {THREE.Mesh} buildingMesh - model 3D budynku (przeszkoda zacienajaca)
 * @param {THREE.Vector3} panelPosition - pozycja panela PV w przestrzeni 3D
 * @param {{width: number, height: number}} panelSize - rozmiar panela (metry)
 * @param {THREE.Scene} scene - scena Three.js
 * @param {THREE.Camera} camera - kamera Three.js
 * @param {THREE.WebGLRenderer} renderer - renderer Three.js
 * @param {function} onProgress - callback posteptu (0-100)
 * @returns {Promise<{annualLoss: number, monthlyLosses: number[]}>} wyniki analizy
 */
export async function analyzeShadowImpact(lat, lon, buildingMesh, panelPosition, panelSize, scene, camera, renderer, onProgress) {
    // Zabezpieczenie przed wielokrotnym uruchomieniem
    if (isRunning) {
        throw new Error('Analiza jest juz w trakcie!');
    }
    isRunning = true;

    // Resetujemy wyniki
    monthlyLosses = new Array(12).fill(0);
    annualLoss = 0;

    // Tworzymy raycaster (obiekt do rzucania promieni)
    const raycaster = new THREE.Raycaster();

    // Przygotowujemy liste dni roku do przeanalizowania
    // Co DAY_STEP dni (np. co 5 dni = 73 probki w roku)
    const allDays = [];
    for (let day = 1; day <= 365; day += DAY_STEP) {
        allDays.push(day);
    }

    // Dzielimy dni na chunki (porcje) do przetwarzania
    const chunks = [];
    for (let i = 0; i < allDays.length; i += CHUNK_SIZE) {
        chunks.push(allDays.slice(i, i + CHUNK_SIZE));
    }

    // Akumulatory wynikow dla kazdego miesiaca
    let monthlyShaded = new Array(12).fill(0); // energia stracona (zacieniona)
    let monthlyTotal = new Array(12).fill(0);  // energia calkowita (potencjalna)

    // Przetwarzamy chunki asynchronicznie (z setTimeout)
    // Dzieki temu przegladarka nie zamraza sie podczas obliczen
    return new Promise((resolve, reject) => {
        let chunkIndex = 0;

        function processNextChunk() {
            try {
                if (chunkIndex >= chunks.length) {
                    // Zakonczono - obliczamy wyniki koncowe
                    finishAnalysis(monthlyShaded, monthlyTotal);
                    isRunning = false;
                    resolve({
                        annualLoss: annualLoss,
                        monthlyLosses: [...monthlyLosses]
                    });
                    return;
                }

                // Przetwarzamy aktualny chunk
                const result = processChunk({
                    lat,
                    lon,
                    buildingMesh,
                    panelPosition,
                    raycaster,
                    days: chunks[chunkIndex],
                    monthlyShaded,
                    monthlyTotal
                });

                monthlyShaded = result.monthlyShaded;
                monthlyTotal = result.monthlyTotal;

                chunkIndex++;

                // Raportujemy postep (0-100%)
                const progress = Math.round((chunkIndex / chunks.length) * 100);
                if (onProgress) {
                    onProgress(progress);
                }

                // Oddajemy kontrole przegladarce (setTimeout z 0ms)
                // Dzieki temu UI nie zamraza sie
                setTimeout(processNextChunk, 0);

            } catch (error) {
                isRunning = false;
                reject(error);
            }
        }

        // Startujemy przetwarzanie
        processNextChunk();
    });
}

/**
 * Oblicza koncowe wyniki analizy z akumulatorow.
 *
 * Dla kazdego miesiaca: strata = (energia_zacieniona / energia_calkowita) * 100%
 * Roczna strata to srednia wazona (miesiace z wieksza irradiacja waza wiecej).
 *
 * @param {number[]} monthlyShaded - energia stracona na miesiac
 * @param {number[]} monthlyTotal - energia calkowita na miesiac
 */
function finishAnalysis(monthlyShaded, monthlyTotal) {
    let totalShaded = 0;
    let totalEnergy = 0;

    for (let month = 0; month < 12; month++) {
        if (monthlyTotal[month] > 0) {
            // Strata procentowa dla danego miesiaca
            monthlyLosses[month] = (monthlyShaded[month] / monthlyTotal[month]) * 100;
        } else {
            monthlyLosses[month] = 0;
        }

        // Akumulujemy do rocznej sumy
        totalShaded += monthlyShaded[month];
        totalEnergy += monthlyTotal[month];
    }

    // Roczna strata procentowa
    if (totalEnergy > 0) {
        annualLoss = (totalShaded / totalEnergy) * 100;
    } else {
        annualLoss = 0;
    }
}

/**
 * Zwraca miesieczne straty energii z ostatniej analizy.
 *
 * Tablica 12 wartosci (styczen = indeks 0, grudzien = indeks 11).
 * Kazda wartosc to procent energii utraconej przez zacienienie.
 * Np. [2.1, 3.5, 5.2, ...] oznacza: w styczniu tracimy 2.1%,
 * w lutym 3.5%, w marcu 5.2% itd.
 *
 * @returns {number[]} tablica 12 strat miesiecznych w procentach
 */
export function getMonthlyLosses() {
    return [...monthlyLosses];
}

/**
 * Zwraca roczna strate energii z ostatniej analizy.
 *
 * To srednia wazona - miesiace z wieksza irradiacja (lato)
 * waza wiecej niz miesiace zimowe.
 *
 * @returns {number} roczna strata w procentach
 */
export function getAnnualLoss() {
    return annualLoss;
}
