// ===========================
// Modul obliczania pozycji slonca (sun-position.js)
//
// Ten modul oblicza gdzie dokladnie na niebie jest slonce
// w danym momencie i miejscu na Ziemi.
//
// Uzywamy uproszczonego algorytmu SPA (Solar Position Algorithm).
// SPA to standardowy sposob obliczania pozycji slonca,
// opracowany przez NREL (National Renewable Energy Laboratory).
//
// Eksportowane funkcje:
// - calculateSunPosition(lat, lon, date) - oblicza kat i kierunek slonca
// - sunPositionToLightPosition(elevation, azimuth, distance) - konwertuje na Vector3
// - isDaylight(elevation) - sprawdza czy jest dzien
//
// Dokladnosc: blad < 1 stopnia dla lat 2020-2050
// ===========================

import * as THREE from 'https://unpkg.com/three@0.160.0/build/three.module.js';

// --- Stale matematyczne ---
const DEG_TO_RAD = Math.PI / 180;  // przelicznik stopni na radiany
const RAD_TO_DEG = 180 / Math.PI;  // przelicznik radianow na stopnie

/**
 * Oblicza Julian Day Number (Dzien Julianski) z daty.
 *
 * Julian Day to ciagla numeracja dni uzywana w astronomii.
 * Dzieki niej latwo liczyc roznice miedzy datami
 * (nie trzeba martwic sie o miesiace, lata przestepne itd.)
 *
 * Wzor pochodzi z "Astronomical Algorithms" Jean Meeus.
 *
 * @param {Date} date - obiekt daty JavaScript (UTC)
 * @returns {number} Julian Day Number
 */
function calculateJulianDay(date) {
    // Pobieramy rok, miesiac i dzien w UTC
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth() + 1; // getUTCMonth zwraca 0-11
    const day = date.getUTCDate();

    // Czesc dzienna (ulamek dnia na podstawie godziny)
    const hours = date.getUTCHours();
    const minutes = date.getUTCMinutes();
    const seconds = date.getUTCSeconds();
    const dayFraction = (hours + minutes / 60 + seconds / 3600) / 24;

    // Wzor Meeus - dla miesiecy styczen i luty traktujemy je
    // jako miesiace 13 i 14 poprzedniego roku
    let y = year;
    let m = month;
    if (m <= 2) {
        y = y - 1;
        m = m + 12;
    }

    // Korekta kalendarza gregorianskiego (po 15 pazdziernika 1582)
    const A = Math.floor(y / 100);
    const B = 2 - A + Math.floor(A / 4);

    // Glowny wzor na Julian Day
    const JD = Math.floor(365.25 * (y + 4716)) +
               Math.floor(30.6001 * (m + 1)) +
               day + dayFraction + B - 1524.5;

    return JD;
}

/**
 * Oblicza stulecie Julianskie (Julian Century) od epoki J2000.0
 *
 * J2000.0 to punkt odniesienia w astronomii - 1 stycznia 2000, 12:00 UTC.
 * Stulecie Julianskie to ulamek stulecia od tego momentu.
 * Np. T = 0.24 oznacza ze minelo 24% stulecia od J2000.0
 *
 * @param {number} JD - Julian Day Number
 * @returns {number} stulecie Julianskie (T)
 */
function calculateJulianCentury(JD) {
    // 2451545.0 to JD dla 1 stycznia 2000, 12:00 UTC (epoka J2000.0)
    // 36525.0 to liczba dni w stuleciu Julianskim
    return (JD - 2451545.0) / 36525.0;
}

/**
 * Oblicza srednia dlugosc ekliptyczna slonca (mean longitude).
 *
 * Dlugosc ekliptyczna to kat mierzony wzdluz ekliptyki
 * (plaszczyznay orbity Ziemi wokol Slonca).
 *
 * @param {number} T - stulecie Julianskie
 * @returns {number} srednia dlugosc w stopniach (0-360)
 */
function calculateMeanLongitude(T) {
    // Wzor wielomianowy - wspolczynniki z algorytmu SPA
    let L0 = 280.46646 + T * (36000.76983 + T * 0.0003032);
    // Normalizacja do zakresu 0-360
    L0 = L0 % 360;
    if (L0 < 0) L0 += 360;
    return L0;
}

/**
 * Oblicza srednia anomalie slonca (mean anomaly).
 *
 * Anomalia to kat ktory opisuje gdzie Ziemia jest na swojej orbicie.
 * "Srednia" oznacza ze zakladamy ruch jednostajny (bez uwzglednienia
 * eliptycznosci orbity).
 *
 * @param {number} T - stulecie Julianskie
 * @returns {number} srednia anomalia w stopniach
 */
function calculateMeanAnomaly(T) {
    let M = 357.52911 + T * (35999.05029 - T * 0.0001537);
    M = M % 360;
    if (M < 0) M += 360;
    return M;
}

/**
 * Oblicza rownanie srodka (equation of center).
 *
 * Rownanie srodka koryguje pozycje slonca o wplyw
 * eliptycznosci orbity Ziemi. Ziemia nie krazy idealnie po kole,
 * wiec slonce nie porusza sie rownomiernie po niebie.
 *
 * @param {number} T - stulecie Julianskie
 * @param {number} M - srednia anomalia w stopniach
 * @returns {number} korekta w stopniach
 */
function calculateEquationOfCenter(T, M) {
    const Mrad = M * DEG_TO_RAD;
    // Szereg trygonometryczny - kazdy kolejny czlon jest coraz mniejszy
    const C = (1.9146 - T * (0.004817 + T * 0.000014)) * Math.sin(Mrad) +
              (0.019993 - T * 0.000101) * Math.sin(2 * Mrad) +
              0.00029 * Math.sin(3 * Mrad);
    return C;
}

/**
 * Oblicza mimosrod orbity Ziemi (eccentricity).
 *
 * Mimosrod mowi jak bardzo orbita rozni sie od idealnego kola.
 * 0 = idealne kolo, 1 = parabola. Dla Ziemi to okolo 0.0167.
 *
 * @param {number} T - stulecie Julianskie
 * @returns {number} mimosrod (bezwymiarowy)
 */
function calculateEccentricity(T) {
    return 0.016708634 - T * (0.000042037 + T * 0.0000001267);
}

/**
 * Oblicza nachylenie ekliptyki (obliquity of the ecliptic).
 *
 * Nachylenie ekliptyki to kat miedzy osią obrotu Ziemi
 * a prostopadla do plaszczyzny orbity. To przez ten kat mamy pory roku!
 * Wynosi okolo 23.44 stopni.
 *
 * @param {number} T - stulecie Julianskie
 * @returns {number} nachylenie w stopniach
 */
function calculateObliquity(T) {
    // Srednie nachylenie (bez nutacji - drobnych drgan osi Ziemi)
    const epsilon0 = 23.0 + (26.0 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60.0) / 60.0;
    return epsilon0;
}

/**
 * Oblicza deklinacje sloneczna (solar declination).
 *
 * Deklinacja to kat miedzy promieniami slonecznymi a plaszyzna rownika.
 * Zmienia sie w ciagu roku od -23.44 do +23.44 stopni.
 * - Latem deklinacja jest dodatnia (slonce wysoko na polkuli polnocnej)
 * - Zima deklinacja jest ujemna (slonce nisko)
 *
 * @param {number} apparentLongitude - pozorna dlugosc slonca w stopniach
 * @param {number} obliquity - nachylenie ekliptyki w stopniach
 * @returns {number} deklinacja w stopniach
 */
function calculateDeclination(apparentLongitude, obliquity) {
    const lambdaRad = apparentLongitude * DEG_TO_RAD;
    const epsilonRad = obliquity * DEG_TO_RAD;
    const sinDec = Math.sin(epsilonRad) * Math.sin(lambdaRad);
    return Math.asin(sinDec) * RAD_TO_DEG;
}

/**
 * Oblicza rektascensje slonca (right ascension).
 *
 * Rektascensja to odpowiednik dlugosci geograficznej na sferze niebieskiej.
 * Mowi nam "gdzie na osi wschod-zachod" jest slonce wzgledem gwiazd.
 *
 * @param {number} apparentLongitude - pozorna dlugosc slonca w stopniach
 * @param {number} obliquity - nachylenie ekliptyki w stopniach
 * @returns {number} rektascensja w stopniach
 */
function calculateRightAscension(apparentLongitude, obliquity) {
    const lambdaRad = apparentLongitude * DEG_TO_RAD;
    const epsilonRad = obliquity * DEG_TO_RAD;
    const y = Math.cos(epsilonRad) * Math.sin(lambdaRad);
    const x = Math.cos(lambdaRad);
    let alpha = Math.atan2(y, x) * RAD_TO_DEG;
    // Normalizacja do 0-360
    alpha = alpha % 360;
    if (alpha < 0) alpha += 360;
    return alpha;
}

/**
 * Oblicza czas gwiazdowy Greenwich (Greenwich Mean Sidereal Time).
 *
 * Czas gwiazdowy mowi nam ktore gwiazdy sa aktualnie nad
 * poludnikiem zerowym (Greenwich). Potrzebujemy go zeby obliczyc
 * kat godzinowy slonca.
 *
 * @param {number} JD - Julian Day Number
 * @param {number} T - stulecie Julianskie
 * @returns {number} czas gwiazdowy w stopniach (0-360)
 */
function calculateGMST(JD, T) {
    // Wzor na GMST w stopniach
    let GMST = 280.46061837 +
               360.98564736629 * (JD - 2451545.0) +
               T * T * (0.000387933 - T / 38710000.0);
    // Normalizacja do 0-360
    GMST = GMST % 360;
    if (GMST < 0) GMST += 360;
    return GMST;
}

/**
 * Oblicza kat godzinowy slonca (hour angle).
 *
 * Kat godzinowy mowi jak daleko slonce jest od poludnika obserwatora.
 * - H = 0 oznacza ze slonce jest dokladnie na poludniu (kulminacja)
 * - H < 0 oznacza ze slonce jest na wschodzie (przed poludniem)
 * - H > 0 oznacza ze slonce jest na zachodzie (po poludniu)
 *
 * @param {number} GMST - czas gwiazdowy Greenwich w stopniach
 * @param {number} longitude - dlugosc geograficzna obserwatora (stopnie, E dodatnie)
 * @param {number} rightAscension - rektascensja slonca w stopniach
 * @returns {number} kat godzinowy w stopniach
 */
function calculateHourAngle(GMST, longitude, rightAscension) {
    // Lokalny czas gwiazdowy = GMST + dlugosc geograficzna
    let H = GMST + longitude - rightAscension;
    // Normalizacja do zakresu -180 do +180
    H = H % 360;
    if (H < 0) H += 360;
    if (H > 180) H -= 360;
    return H;
}

/**
 * Oblicza elewacje slonca (solar elevation / altitude).
 *
 * Elewacja to kat slonca nad horyzontem:
 * - 0 stopni = slonce dokladnie na horyzoncie (wschod/zachod)
 * - 90 stopni = slonce w zenicie (prosto nad glowa)
 * - wartosci ujemne = slonce pod horyzontem (noc)
 *
 * @param {number} latitude - szerokosc geograficzna obserwatora w stopniach
 * @param {number} declination - deklinacja slonca w stopniach
 * @param {number} hourAngle - kat godzinowy w stopniach
 * @returns {number} elewacja w stopniach
 */
function calculateElevation(latitude, declination, hourAngle) {
    const latRad = latitude * DEG_TO_RAD;
    const decRad = declination * DEG_TO_RAD;
    const hRad = hourAngle * DEG_TO_RAD;

    // Wzor na elewacje slonca (transformacja wspolrzednych)
    const sinElev = Math.sin(latRad) * Math.sin(decRad) +
                    Math.cos(latRad) * Math.cos(decRad) * Math.cos(hRad);

    return Math.asin(sinElev) * RAD_TO_DEG;
}

/**
 * Oblicza azymut slonca (solar azimuth).
 *
 * Azymut to kierunek na kompasie skad swieci slonce:
 * - 0 (360) stopni = polnoc
 * - 90 stopni = wschod
 * - 180 stopni = poludnie
 * - 270 stopni = zachod
 *
 * @param {number} latitude - szerokosc geograficzna obserwatora w stopniach
 * @param {number} declination - deklinacja slonca w stopniach
 * @param {number} hourAngle - kat godzinowy w stopniach
 * @param {number} elevation - elewacja slonca w stopniach
 * @returns {number} azymut w stopniach (0-360, od polnocy zgodnie z ruchem wskazowek)
 */
function calculateAzimuth(latitude, declination, hourAngle, elevation) {
    const latRad = latitude * DEG_TO_RAD;
    const decRad = declination * DEG_TO_RAD;
    const hRad = hourAngle * DEG_TO_RAD;
    const elevRad = elevation * DEG_TO_RAD;

    // Obliczamy azymut na podstawie kata godzinowego i deklinacji
    // sin(azymut) = -sin(H) * cos(dec) / cos(elev)
    // cos(azymut) = (sin(dec) - sin(lat) * sin(elev)) / (cos(lat) * cos(elev))
    const cosElev = Math.cos(elevRad);

    // Zabezpieczenie przed dzieleniem przez zero (slonce w zenicie)
    if (Math.abs(cosElev) < 1e-10) {
        return 180.0; // w zenicie azymut jest nieokreslony, przyjmujemy poludnie
    }

    const sinAz = -Math.sin(hRad) * Math.cos(decRad) / cosElev;
    const cosAz = (Math.sin(decRad) - Math.sin(latRad) * Math.sin(elevRad)) /
                  (Math.cos(latRad) * cosElev);

    // atan2 daje nam kat w pelnym zakresie -180..+180
    let azimuth = Math.atan2(sinAz, cosAz) * RAD_TO_DEG;

    // Normalizacja do 0-360 (od polnocy zgodnie z ruchem wskazowek zegara)
    if (azimuth < 0) azimuth += 360;

    return azimuth;
}

/**
 * Oblicza korekcje refrakcji atmosferycznej.
 *
 * Atmosfera Ziemi "zalamuje" (odgina) promienie sloneczne,
 * przez co slonce wyglada jakby bylo wyzej niz jest naprawde.
 * Efekt jest najsilniejszy przy horyzoncie (ok. 0.5 stopnia).
 *
 * @param {number} elevation - elewacja geometryczna (bez refrakcji) w stopniach
 * @returns {number} korekcja refrakcji w stopniach (do dodania do elewacji)
 */
function calculateRefraction(elevation) {
    if (elevation > 85) {
        return 0; // blisko zenitu refrakcja jest znikoma
    }
    if (elevation > 5) {
        // Wzor przyblizony dla elewacji powyzej 5 stopni
        const tanElev = Math.tan(elevation * DEG_TO_RAD);
        return (58.1 / tanElev - 0.07 / Math.pow(tanElev, 3) + 0.000086 / Math.pow(tanElev, 5)) / 3600;
    }
    if (elevation > -0.575) {
        // Wzor dla niskich elewacji (blisko horyzontu)
        return (1735 + elevation * (-518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711)))) / 3600;
    }
    // Ponizej horyzontu - minimalna korekta
    return (-20.774 / Math.tan(elevation * DEG_TO_RAD)) / 3600;
}

/**
 * Glowna funkcja obliczajaca pozycje slonca.
 *
 * Na podstawie lokalizacji (szerokosc/dlugosc geograficzna) i daty/godziny
 * oblicza dokladna pozycje slonca na niebie.
 *
 * @param {number} lat - szerokosc geograficzna w stopniach (N dodatnie, S ujemne)
 * @param {number} lon - dlugosc geograficzna w stopniach (E dodatnie, W ujemne)
 * @param {Date} date - obiekt daty JavaScript (z czasem)
 * @returns {{elevation: number, azimuth: number}} - pozycja slonca w stopniach
 *   - elevation: kat nad horyzontem (ujemny = pod horyzontem = noc)
 *   - azimuth: kierunek od polnocy zgodnie z ruchem wskazowek (0=N, 90=E, 180=S, 270=W)
 */
export function calculateSunPosition(lat, lon, date) {
    // Krok 1: Oblicz Dzien Julianski
    const JD = calculateJulianDay(date);

    // Krok 2: Oblicz stulecie Julianskie (czas od epoki J2000.0)
    const T = calculateJulianCentury(JD);

    // Krok 3: Srednia dlugosc ekliptyczna slonca
    const L0 = calculateMeanLongitude(T);

    // Krok 4: Srednia anomalia slonca
    const M = calculateMeanAnomaly(T);

    // Krok 5: Rownanie srodka (korekta za eliptycznosc orbity)
    const C = calculateEquationOfCenter(T, M);

    // Krok 6: Prawdziwa dlugosc slonca = srednia + korekta
    const sunTrueLongitude = L0 + C;

    // Krok 7: Pozorna dlugosc slonca (z korekta nutacji i aberracji)
    // Omega to dlugosc wezla wzstepujacego orbity Ksiezyca
    const omega = 125.04 - 1934.136 * T;
    const apparentLongitude = sunTrueLongitude - 0.00569 - 0.00478 * Math.sin(omega * DEG_TO_RAD);

    // Krok 8: Nachylenie ekliptyki (z korekta nutacji)
    const epsilon0 = calculateObliquity(T);
    const epsilon = epsilon0 + 0.00256 * Math.cos(omega * DEG_TO_RAD);

    // Krok 9: Deklinacja sloneczna
    const declination = calculateDeclination(apparentLongitude, epsilon);

    // Krok 10: Rektascensja slonca
    const rightAscension = calculateRightAscension(apparentLongitude, epsilon);

    // Krok 11: Czas gwiazdowy Greenwich
    const GMST = calculateGMST(JD, T);

    // Krok 12: Kat godzinowy
    const hourAngle = calculateHourAngle(GMST, lon, rightAscension);

    // Krok 13: Elewacja slonca (kat nad horyzontem)
    let elevation = calculateElevation(lat, declination, hourAngle);

    // Krok 14: Azymut slonca (kierunek na kompasie)
    const azimuth = calculateAzimuth(lat, declination, hourAngle, elevation);

    // Krok 15: Korekta refrakcji atmosferycznej
    // (dodajemy ja do elewacji - slonce wyglada wyzej niz jest naprawde)
    const refraction = calculateRefraction(elevation);
    elevation = elevation + refraction;

    return {
        elevation: elevation,
        azimuth: azimuth
    };
}

/**
 * Konwertuje pozycje slonca (katy) na wspolrzedne 3D dla swiatla Three.js.
 *
 * W Three.js uzywamy DirectionalLight - swiatlo kierunkowe ktore
 * nasleduje promienie sloneczne. Musimy ustawic jego pozycje tak
 * zeby promienie padaly pod wlasciwym katem.
 *
 * Konwencja:
 * - Y = gora (pion)
 * - Azymut 0 = polnoc = kierunek +Z
 * - Azymut 90 = wschod = kierunek +X
 * - Azymut 180 = poludnie = kierunek -Z
 * - Azymut 270 = zachod = kierunek -X
 *
 * @param {number} elevation - elewacja slonca w stopniach (0-90)
 * @param {number} azimuth - azymut slonca w stopniach (0-360)
 * @param {number} [distance=100] - odleglosc swiatla od centrum sceny
 * @returns {THREE.Vector3} pozycja swiatla w przestrzeni 3D
 */
export function sunPositionToLightPosition(elevation, azimuth, distance = 100) {
    // Konwersja katow na radiany
    const elevRad = elevation * DEG_TO_RAD;
    const azRad = azimuth * DEG_TO_RAD;

    // Obliczenie wspolrzednych kartezjanskich ze sferycznych
    // Y = gora = distance * sin(elevation)
    const y = distance * Math.sin(elevRad);

    // Rzut na plaszczyzne pozioma
    const horizontalDistance = distance * Math.cos(elevRad);

    // X = wschod = horizontalDistance * sin(azimuth)
    const x = horizontalDistance * Math.sin(azRad);

    // Z = polnoc = horizontalDistance * cos(azimuth)
    const z = horizontalDistance * Math.cos(azRad);

    return new THREE.Vector3(x, y, z);
}

/**
 * Sprawdza czy jest dzien (slonce nad horyzontem).
 *
 * @param {number} elevation - elewacja slonca w stopniach
 * @returns {boolean} true jesli slonce jest nad horyzontem (dzien), false jesli noc
 */
export function isDaylight(elevation) {
    return elevation > 0;
}
