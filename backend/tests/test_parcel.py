"""
Testy dla funkcjonalnosci proxy ULDK i parsowania geometrii dzialek.

Testuje:
- Walidacja parametrow proxy ULDK
- Parsowanie WKT POLYGON na wspolrzedne
- Konwersja wspolrzednych WGS84 i EPSG:2180 na lokalne metryczne
- Obsluga bledow (brak parametrow, niepoprawne WKT, bledy sieci)
"""

import io
import json
import unittest
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from urllib.parse import urlencode, urlparse, parse_qs
import math
import sys

# Dodanie sciezki projektu
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import PVSimulatorHandler


class MockHTTPRequest:
    """Pomocnicza klasa do tworzenia mockowanych zapytan HTTP."""

    def __init__(self, method, path, body=None, headers=None):
        self.method = method
        self.path = path
        self.body = body or b""
        self.headers = headers or {}


class TestULDKProxyValidation(unittest.TestCase):
    """Testy walidacji parametrow proxy ULDK."""

    def setUp(self):
        """Przygotowanie serwera testowego."""
        self.server = HTTPServer(("127.0.0.1", 0), PVSimulatorHandler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.handle_request)
        self.thread.daemon = True

    def tearDown(self):
        """Zamykanie serwera testowego."""
        self.server.server_close()

    def _make_request(self, path):
        """Wykonuje zapytanie GET do serwera testowego."""
        import urllib.request
        self.thread.start()
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode("utf-8"), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8"), e.headers

    def test_uldk_missing_request_param(self):
        """Brak parametru 'request' powinien zwrocic blad 400."""
        status, body, _ = self._make_request("/api/uldk?id=test")
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn("error", data)
        self.assertIn("request", data["message"].lower())

    def test_uldk_no_params(self):
        """Zapytanie bez parametrow powinno zwrocic blad 400."""
        status, body, _ = self._make_request("/api/uldk")
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn("error", data)

    @patch("backend.main.urlopen")
    def test_uldk_valid_request(self, mock_urlopen):
        """Poprawne zapytanie z parametrem 'request' powinno przejsc do ULDK."""
        # Mockujemy odpowiedz ULDK
        mock_response = MagicMock()
        mock_response.read.return_value = b"1\nPOLYGON((20.0 50.0, 20.1 50.0, 20.1 50.1, 20.0 50.1, 20.0 50.0))"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        status, body, headers = self._make_request(
            "/api/uldk?request=GetParcelById&id=141201_1.0001.6509&result=geom_wkt&srid=4326"
        )

        self.assertEqual(status, 200)
        self.assertIn("POLYGON", body)
        # Sprawdz ze urlopen zostal wywolany z poprawnym URL
        call_args = mock_urlopen.call_args
        called_request = call_args[0][0]
        self.assertIn("uldk.gugik.gov.pl", called_request.full_url)
        self.assertIn("GetParcelById", called_request.full_url)

    @patch("backend.main.urlopen")
    def test_uldk_allowed_params_only(self, mock_urlopen):
        """Proxy powinno przekazac tylko dozwolone parametry."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"1\ntest"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        # Dodajemy niedozwolony parametr 'evil'
        status, _, _ = self._make_request(
            "/api/uldk?request=GetParcelById&id=test&evil=hack&srid=4326"
        )

        self.assertEqual(status, 200)
        call_args = mock_urlopen.call_args
        called_url = call_args[0][0].full_url
        self.assertNotIn("evil", called_url)
        self.assertIn("srid=4326", called_url)

    @patch("backend.main.urlopen")
    def test_uldk_network_error(self, mock_urlopen):
        """Blad sieci przy laczeniu z ULDK powinien zwrocic 502."""
        mock_urlopen.side_effect = URLError("Connection refused")

        status, body, _ = self._make_request(
            "/api/uldk?request=GetParcelById&id=test"
        )

        self.assertEqual(status, 502)
        data = json.loads(body)
        self.assertIn("error", data)

    @patch("backend.main.urlopen")
    def test_uldk_xy_parameter(self, mock_urlopen):
        """Parametr 'xy' powinien byc przekazany do ULDK."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"1\nPOLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        status, _, _ = self._make_request(
            "/api/uldk?request=GetParcelByXY&xy=486000,637000&result=geom_wkt"
        )

        self.assertEqual(status, 200)
        call_args = mock_urlopen.call_args
        called_url = call_args[0][0].full_url
        self.assertIn("xy=", called_url)


class TestWKTParsing(unittest.TestCase):
    """Testy parsowania formatu WKT POLYGON."""

    def test_simple_polygon(self):
        """Parsowanie prostego POLYGON z 4 wierzcholkami."""
        wkt = "POLYGON((20.0 50.0, 20.1 50.0, 20.1 50.1, 20.0 50.1, 20.0 50.0))"
        coords = self._parse_wkt(wkt)
        self.assertEqual(len(coords), 5)  # 4 wierzcholki + zamkniecie
        self.assertAlmostEqual(coords[0][0], 20.0)
        self.assertAlmostEqual(coords[0][1], 50.0)

    def test_polygon_with_spaces(self):
        """Parsowanie POLYGON z dodatkowymi spacjami."""
        wkt = "POLYGON(( 20.0 50.0 , 20.1 50.0 , 20.1 50.1 , 20.0 50.0 ))"
        coords = self._parse_wkt(wkt)
        self.assertGreater(len(coords), 2)

    def test_polygon_with_srid_prefix(self):
        """Parsowanie WKT z prefiksem SRID."""
        wkt = "SRID=4326;POLYGON((20.0 50.0, 20.1 50.0, 20.1 50.1, 20.0 50.0))"
        coords = self._parse_wkt(wkt)
        self.assertEqual(len(coords), 4)
        self.assertAlmostEqual(coords[0][0], 20.0)

    def test_invalid_wkt_no_polygon(self):
        """Brak slowa POLYGON powinien dac blad."""
        wkt = "POINT(20.0 50.0)"
        with self.assertRaises(ValueError):
            self._parse_wkt(wkt)

    def test_empty_wkt(self):
        """Pusty string powinien dac blad."""
        with self.assertRaises(ValueError):
            self._parse_wkt("")

    def test_epsg2180_coordinates(self):
        """Parsowanie wspolrzednych w ukladzie EPSG:2180 (duze wartosci)."""
        wkt = "POLYGON((486000 637000, 486100 637000, 486100 637100, 486000 637100, 486000 637000))"
        coords = self._parse_wkt(wkt)
        self.assertEqual(len(coords), 5)
        self.assertAlmostEqual(coords[0][0], 486000.0)
        self.assertAlmostEqual(coords[0][1], 637000.0)

    @staticmethod
    def _parse_wkt(wkt_string):
        """
        Implementacja parsowania WKT - taka sama logika jak w parcel.js.
        Przeniesiona tutaj do testowania po stronie backendu.
        """
        import re

        wkt = wkt_string.strip()
        if not wkt:
            raise ValueError("Pusty string WKT")

        # Usuwanie prefiksu SRID
        if wkt.startswith('SRID='):
            idx = wkt.index(';')
            wkt = wkt[idx + 1:]

        # Szukanie POLYGON
        match = re.search(r'POLYGON\s*\(\((.+?)\)\)', wkt, re.IGNORECASE)
        if not match:
            raise ValueError("Nie rozpoznano formatu WKT - oczekiwano POLYGON")

        coords_string = match.group(1)
        pairs = coords_string.split(',')

        coordinates = []
        for pair in pairs:
            parts = pair.strip().split()
            if len(parts) < 2:
                raise ValueError(f"Nieprawidlowa para wspolrzednych: '{pair}'")
            coordinates.append((float(parts[0]), float(parts[1])))

        return coordinates


class TestCoordinateConversion(unittest.TestCase):
    """Testy konwersji wspolrzednych na lokalne metryczne."""

    def test_wgs84_to_local_center(self):
        """Srodek dzialki powinien wypasc w (0, 0)."""
        # Kwadrat 0.001 stopnia (ok. 100m)
        coords = [
            (20.0, 50.0),
            (20.001, 50.0),
            (20.001, 50.001),
            (20.0, 50.001),
        ]
        local = self._wgs84_to_local(coords)

        # Srednia x i z powinna byc bliska 0
        avg_x = sum(c['x'] for c in local) / len(local)
        avg_z = sum(c['z'] for c in local) / len(local)
        self.assertAlmostEqual(avg_x, 0.0, places=3)
        self.assertAlmostEqual(avg_z, 0.0, places=3)

    def test_wgs84_to_local_scale(self):
        """Roznica 0.001 stopnia ~= 70-110 metrow."""
        coords = [
            (20.0, 50.0),
            (20.001, 50.0),
            (20.001, 50.001),
            (20.0, 50.001),
        ]
        local = self._wgs84_to_local(coords)

        # Szerokosc dzialki (os X)
        width = abs(local[1]['x'] - local[0]['x'])
        # 0.001 stopnia dlugosci na 50N ~= 71.7 m
        self.assertGreater(width, 50)
        self.assertLess(width, 120)

        # Wysokosc dzialki (os Z)
        height = abs(local[2]['z'] - local[1]['z'])
        # 0.001 stopnia szerokosci ~= 111.3 m
        self.assertGreater(height, 80)
        self.assertLess(height, 140)

    def test_epsg2180_to_local(self):
        """Konwersja EPSG:2180 - juz jest w metrach, wiec prosty offset."""
        coords = [
            (486000, 637000),
            (486100, 637000),
            (486100, 637100),
            (486000, 637100),
        ]
        local = self._epsg2180_to_local(coords)

        # Roznica 100m powinna byc zachowana
        width = abs(local[1]['x'] - local[0]['x'])
        self.assertAlmostEqual(width, 100.0, places=1)

    def test_epsg2180_centered(self):
        """Wynik EPSG:2180 powinien byc wycentrowany wokol (0,0)."""
        coords = [
            (486000, 637000),
            (486100, 637000),
            (486100, 637100),
            (486000, 637100),
        ]
        local = self._epsg2180_to_local(coords)

        avg_x = sum(c['x'] for c in local) / len(local)
        avg_z = sum(c['z'] for c in local) / len(local)
        self.assertAlmostEqual(avg_x, 0.0, places=1)
        self.assertAlmostEqual(avg_z, 0.0, places=1)

    def test_detect_wgs84(self):
        """Rozpoznawanie ukladu WGS84 (male wartosci)."""
        coords = [(20.0, 50.0), (20.1, 50.1)]
        system = self._detect_system(coords)
        self.assertEqual(system, 'wgs84')

    def test_detect_epsg2180(self):
        """Rozpoznawanie ukladu EPSG:2180 (duze wartosci)."""
        coords = [(486000, 637000), (486100, 637100)]
        system = self._detect_system(coords)
        self.assertEqual(system, 'epsg2180')

    @staticmethod
    def _wgs84_to_local(coordinates):
        """Konwersja WGS84 na lokalne metryczne (identyczna logika jak parcel.js)."""
        sum_lon = sum(c[0] for c in coordinates)
        sum_lat = sum(c[1] for c in coordinates)
        center_lon = sum_lon / len(coordinates)
        center_lat = sum_lat / len(coordinates)

        meters_per_degree_lat = 111320
        meters_per_degree_lon = 111320 * math.cos(center_lat * math.pi / 180)

        result = []
        for lon, lat in coordinates:
            result.append({
                'x': (lon - center_lon) * meters_per_degree_lon,
                'z': -(lat - center_lat) * meters_per_degree_lat
            })
        return result

    @staticmethod
    def _epsg2180_to_local(coordinates):
        """Konwersja EPSG:2180 na lokalne (przesuniecie do srodka)."""
        sum_x = sum(c[0] for c in coordinates)
        sum_y = sum(c[1] for c in coordinates)
        center_x = sum_x / len(coordinates)
        center_y = sum_y / len(coordinates)

        result = []
        for x, y in coordinates:
            result.append({
                'x': x - center_x,
                'z': -(y - center_y)
            })
        return result

    @staticmethod
    def _detect_system(coordinates):
        """Wykrywanie ukladu wspolrzednych."""
        if not coordinates:
            return 'unknown'
        x, y = coordinates[0]
        if abs(x) > 1000 or abs(y) > 1000:
            return 'epsg2180'
        return 'wgs84'


class TestSTLServing(unittest.TestCase):
    """Testy serwowania pliku Dom.STL."""

    def setUp(self):
        """Przygotowanie serwera testowego."""
        self.server = HTTPServer(("127.0.0.1", 0), PVSimulatorHandler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.handle_request)
        self.thread.daemon = True

    def tearDown(self):
        """Zamykanie serwera testowego."""
        self.server.server_close()

    def test_stl_file_served(self):
        """Plik Dom.STL powinien byc dostepny pod /models/Dom.STL."""
        import urllib.request
        self.thread.start()

        url = f"http://127.0.0.1:{self.port}/models/Dom.STL"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                content = resp.read()
                # Dom.STL jest binarny i ma 2684 bajtow
                self.assertGreater(len(content), 0)
                content_type = resp.headers.get("Content-Type", "")
                self.assertIn("application/sla", content_type)
        except urllib.error.HTTPError as e:
            self.fail(f"Nie udalo sie pobrac Dom.STL: {e}")


if __name__ == "__main__":
    unittest.main()
