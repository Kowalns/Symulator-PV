"""
Testy jednostkowe dla modulu granic dzialki.

Logika pobierania i wyswietlania granic dzialki jest zaimplementowana
po stronie frontendu (JavaScript), ale tutaj testujemy:
- Poprawnosc istnienia plikow frontendowych
- Strukture pliku viewer.html (czy zawiera wymagane elementy)
- Poprawnosc linkow do widoku 3D

Te testy sprawdzaja integralnosc plikow - czy wszystko jest na swoim miejscu.
"""

import os
import sys
import unittest
from pathlib import Path

# Sciezka do katalogu glownego projektu
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestViewerFilesExist(unittest.TestCase):
    """Sprawdza czy wszystkie pliki potrzebne do widoku 3D istnieja."""

    def test_viewer_html_exists(self):
        """Plik viewer.html musi istniec w katalogu frontend/."""
        path = PROJECT_ROOT / 'frontend' / 'viewer.html'
        self.assertTrue(path.exists(), f'Brak pliku: {path}')

    def test_viewer3d_js_exists(self):
        """Plik viewer3d.js musi istniec - zawiera inicjalizacje sceny 3D."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'viewer3d.js'
        self.assertTrue(path.exists(), f'Brak pliku: {path}')

    def test_stl_loader_js_exists(self):
        """Plik stl-loader.js musi istniec - obsluguje import plikow STL."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'stl-loader.js'
        self.assertTrue(path.exists(), f'Brak pliku: {path}')

    def test_parcel_js_exists(self):
        """Plik parcel.js musi istniec - obsluguje granice dzialek."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        self.assertTrue(path.exists(), f'Brak pliku: {path}')

    def test_viewer_css_exists(self):
        """Plik viewer.css musi istniec - style widoku 3D."""
        path = PROJECT_ROOT / 'frontend' / 'css' / 'viewer.css'
        self.assertTrue(path.exists(), f'Brak pliku: {path}')


class TestViewerHTMLStructure(unittest.TestCase):
    """Sprawdza czy viewer.html zawiera wymagane elementy."""

    @classmethod
    def setUpClass(cls):
        """Wczytuje zawartosc pliku viewer.html raz dla wszystkich testow."""
        viewer_path = PROJECT_ROOT / 'frontend' / 'viewer.html'
        with open(viewer_path, 'r', encoding='utf-8') as f:
            cls.html_content = f.read()

    def test_has_threejs_import(self):
        """Viewer musi ladowac Three.js z CDN."""
        self.assertIn('unpkg.com/three@0.160.0', self.html_content)

    def test_has_module_type_script(self):
        """Skrypty musza byc ladowane jako ES modules (type='module')."""
        self.assertIn('type="module"', self.html_content)

    def test_has_stl_file_input(self):
        """Musi byc element do wyboru pliku STL."""
        self.assertIn('stl-file-input', self.html_content)

    def test_has_parcel_input(self):
        """Musi byc pole do wpisania numeru dzialki."""
        self.assertIn('parcel-id-input', self.html_content)

    def test_has_draw_button(self):
        """Musi byc przycisk do recznego rysowania."""
        self.assertIn('toggle-draw-btn', self.html_content)

    def test_has_close_polygon_button(self):
        """Musi byc przycisk do zamykania konturu."""
        self.assertIn('close-polygon-btn', self.html_content)

    def test_has_viewer_container(self):
        """Musi byc kontener na scene 3D."""
        self.assertIn('viewer-container', self.html_content)

    def test_has_polish_language(self):
        """Strona musi byc w jezyku polskim."""
        self.assertIn('lang="pl"', self.html_content)

    def test_has_viewer3d_import(self):
        """Musi importowac modul viewer3d.js."""
        self.assertIn('viewer3d.js', self.html_content)

    def test_has_stl_loader_import(self):
        """Musi importowac modul stl-loader.js."""
        self.assertIn('stl-loader.js', self.html_content)

    def test_has_parcel_import(self):
        """Musi importowac modul parcel.js."""
        self.assertIn('parcel.js', self.html_content)

    def test_has_back_link(self):
        """Musi byc link powrotny do strony glownej."""
        self.assertIn('index.html', self.html_content)


class TestIndexHTMLLink(unittest.TestCase):
    """Sprawdza czy strona glowna zawiera link do widoku 3D."""

    @classmethod
    def setUpClass(cls):
        """Wczytuje zawartosc pliku index.html."""
        index_path = PROJECT_ROOT / 'frontend' / 'index.html'
        with open(index_path, 'r', encoding='utf-8') as f:
            cls.html_content = f.read()

    def test_index_has_viewer_link(self):
        """Strona glowna musi miec link do viewer.html."""
        self.assertIn('viewer.html', self.html_content)

    def test_index_link_has_description(self):
        """Link musi miec opis (zeby uzytkownik wiedzial co to)."""
        self.assertIn('Widok 3D', self.html_content)


class TestJavaScriptFileContent(unittest.TestCase):
    """Sprawdza zawartosc plikow JavaScript - czy maja wymagane elementy."""

    def test_viewer3d_has_scene_init(self):
        """viewer3d.js musi eksportowac funkcje initScene."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'viewer3d.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('export function initScene', content)

    def test_viewer3d_has_orbit_controls(self):
        """viewer3d.js musi uzywac OrbitControls."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'viewer3d.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('OrbitControls', content)

    def test_stl_loader_has_load_function(self):
        """stl-loader.js musi eksportowac funkcje ladowania STL."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'stl-loader.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('export function loadSTLFile', content)

    def test_parcel_has_fetch_function(self):
        """parcel.js musi eksportowac funkcje pobierania dzialki z ULDK."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('export async function fetchParcelFromULDK', content)

    def test_parcel_has_wkt_parser(self):
        """parcel.js musi eksportowac funkcje parsowania WKT."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('export function parseWKT', content)

    def test_parcel_has_drawing_mode(self):
        """parcel.js musi miec obsluge trybu rysowania."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('toggleDrawingMode', content)

    def test_parcel_has_close_polygon(self):
        """parcel.js musi miec funkcje zamykania konturu."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('export function closeDrawingPolygon', content)

    def test_parcel_has_uldk_url(self):
        """parcel.js musi uzywac poprawnego URL do API ULDK."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('uldk.gugik.gov.pl', content)

    def test_parcel_has_coordinate_conversion(self):
        """parcel.js musi miec konwersje wspolrzednych EPSG:2180."""
        path = PROJECT_ROOT / 'frontend' / 'js' / 'parcel.js'
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('convertEPSG2180ToLocal', content)


if __name__ == '__main__':
    unittest.main()
