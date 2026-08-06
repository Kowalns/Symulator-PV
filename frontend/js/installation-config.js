/**
 * installation-config.js - Modul konfiguracji instalacji PV
 *
 * Odpowiada za:
 * - Wczytanie listy paneli z API (/api/panels)
 * - Obsluge formularza konfiguracji (slidery, selecty, inputy)
 * - Wysylanie konfiguracji do backendu (/api/installation/configure)
 * - Aktualizacje wizualizacji 3D paneli po otrzymaniu odpowiedzi
 * - Wyswietlenie podsumowania mocy i wymiarow instalacji
 */

import { renderPanels, clearPanels, focusOnObject, scene } from './viewer3d.js';

// Elementy DOM - formularz konfiguracji
const panelSelect = document.getElementById('panel-model-select');
const orientationSelect = document.getElementById('panel-orientation');
const tiltSlider = document.getElementById('tilt-angle-slider');
const tiltValue = document.getElementById('tilt-angle-value');
const clearanceSlider = document.getElementById('ground-clearance-slider');
const clearanceValue = document.getElementById('ground-clearance-value');
const colSpacingSlider = document.getElementById('col-spacing-slider');
const colSpacingValue = document.getElementById('col-spacing-value');
const panelCountInput = document.getElementById('panel-count');
const applyBtn = document.getElementById('apply-installation');
const statusDiv = document.getElementById('installation-status');
const summaryDiv = document.getElementById('installation-summary');
const summaryPower = document.getElementById('summary-power');
const summaryDimensions = document.getElementById('summary-dimensions');

// Dane paneli z backendu
let dostepnePanele = [];

/**
 * Wczytuje liste dostepnych modeli paneli z API.
 */
async function wczytajListePaneli() {
    try {
        const response = await fetch('/api/panels');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        dostepnePanele = data.panele || [];
        wypelnijSelectPaneli();
    } catch (error) {
        console.error('Blad wczytywania listy paneli:', error);
        panelSelect.innerHTML = '<option value="">Blad ladowania bazy paneli</option>';
    }
}

/**
 * Wypelnia dropdown lista paneli z bazy.
 */
function wypelnijSelectPaneli() {
    panelSelect.innerHTML = '';

    if (dostepnePanele.length === 0) {
        panelSelect.innerHTML = '<option value="">Brak paneli w bazie</option>';
        return;
    }

    for (const panel of dostepnePanele) {
        const option = document.createElement('option');
        option.value = panel.id;
        option.textContent = `${panel.producent} ${panel.model} (${panel.moc_wp}W)`;
        panelSelect.appendChild(option);
    }
}

/**
 * Aktualizuje wyswietlana wartosc slidera.
 */
function podepnijSlidery() {
    tiltSlider.addEventListener('input', () => {
        tiltValue.textContent = tiltSlider.value;
    });
    clearanceSlider.addEventListener('input', () => {
        clearanceValue.textContent = clearanceSlider.value;
    });
    colSpacingSlider.addEventListener('input', () => {
        colSpacingValue.textContent = colSpacingSlider.value;
    });
}

/**
 * Zbiera konfiguracje z formularza i wysyla do API.
 */
async function zastosujKonfiguracje() {
    const panelId = panelSelect.value;
    if (!panelId) {
        ustawStatus('Wybierz model panela', 'error');
        return;
    }

    const konfiguracja = {
        panel_id: panelId,
        orientacja: orientationSelect.value,
        kat_nachylenia: parseFloat(tiltSlider.value),
        azymut: 0,
        przeswit_nad_gruntem_cm: parseFloat(clearanceSlider.value),
        odstep_boczny_cm: parseFloat(colSpacingSlider.value),
        liczba_paneli: parseInt(panelCountInput.value),
    };

    ustawStatus('Obliczanie rozmieszczenia...', '');
    applyBtn.disabled = true;

    try {
        const response = await fetch('/api/installation/configure', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(konfiguracja),
        });

        const data = await response.json();

        if (!response.ok) {
            ustawStatus(data.message || 'Blad konfiguracji', 'error');
            return;
        }

        // Renderuj panele na scenie 3D
        renderPanels(data);

        // Pokaz podsumowanie
        wyswietlPodsumowanie(data);
        ustawStatus('Konfiguracja zastosowana pomyslnie', 'success');

        // Centruj kamere na panelach
        const panelsObj = scene.getObjectByName('panele_pv');
        if (panelsObj) {
            focusOnObject(panelsObj);
        }

    } catch (error) {
        console.error('Blad konfiguracji instalacji:', error);
        ustawStatus(`Blad polaczenia z serwerem: ${error.message}`, 'error');
    } finally {
        applyBtn.disabled = false;
    }
}

/**
 * Wyswietla podsumowanie instalacji (moc, wymiary).
 */
function wyswietlPodsumowanie(data) {
    summaryDiv.style.display = 'block';
    summaryPower.textContent = data.moc_calkowita_kwp.toFixed(2);

    const wym = data.wymiary_instalacji_m;
    summaryDimensions.textContent =
        `${wym.szerokosc.toFixed(1)}m x ${wym.glebokosc.toFixed(1)}m x ${wym.wysokosc.toFixed(1)}m (szer x glab x wys)`;
}

/**
 * Ustawia tekst statusu z odpowiednia klasa CSS.
 */
function ustawStatus(tekst, typ) {
    statusDiv.textContent = tekst;
    statusDiv.className = 'status-text' + (typ ? ' ' + typ : '');
}

// Inicjalizacja
podepnijSlidery();
wczytajListePaneli();
applyBtn.addEventListener('click', zastosujKonfiguracje);
