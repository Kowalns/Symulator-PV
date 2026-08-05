"""
Glowny plik serwera - uruchamia aplikacje webowa symulatora PV.

Serwer obsluguje:
1. Statyczne pliki frontendowe (HTML, CSS, JS) - z katalogu frontend/
2. API endpoints (endpointy - adresy pod ktore frontend wysyla zapytania):
   - GET /api/health - sprawdzenie czy serwer dziala
   - POST /api/simulate - przeprowadzenie symulacji PV

Uzycie:
    python3 backend/main.py

Serwer uruchomi sie na porcie 8000: http://localhost:8000
"""

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Dodajemy katalog glowny projektu do sciezki importow
# (zeby Python mogl znalezc moduly backend.api, backend.services itp.)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.handlers import (
    handle_health,
    handle_simulate,
    handle_get_panels,
    handle_get_inverters,
    handle_get_batteries,
    handle_installation_configure,
    handle_shading_simulate,
    handle_energy_profile,
    handle_economics_analyze,
    handle_get_tariffs,
    handle_report_generate,
    handle_scenarios_compare,
)


# Port na ktorym serwer nasluchiuje (domyslnie 8000)
PORT = int(os.environ.get("PORT", 8000))

# Sciezka do katalogu z plikami frontendu
FRONTEND_DIR = PROJECT_ROOT / "frontend"


class PVSimulatorHandler(SimpleHTTPRequestHandler):
    """
    Handler HTTP - obsluguje zapytania przychodzace do serwera.

    Dziedziczy (rozszerza) SimpleHTTPRequestHandler, ktory juz umie
    serwowac pliki statyczne. My dodajemy obsluge API.
    """

    def __init__(self, *args, **kwargs):
        """Ustawia katalog frontendu jako zrodlo plikow statycznych."""
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        """
        Obsluga zapytan GET (np. otwarcie strony w przegladarce).

        - /api/health -> zwraca status serwera
        - /api/uldk -> proxy do ULDK API (geoportal)
        - /api/panels -> zwraca liste dostepnych paneli PV
        - /api/inverters -> zwraca liste dostepnych falownikow
        - /api/batteries -> zwraca liste dostepnych magazynow energii
        - /models/Dom.STL -> serwuje plik STL budynku
        - wszystko inne -> szuka pliku w katalogu frontend/
        """
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            status_code, response = handle_health()
            self._send_json_response(status_code, response)
        elif parsed.path == "/api/uldk":
            self._handle_uldk_proxy(parsed.query)
        elif parsed.path == "/api/panels":
            status_code, response = handle_get_panels()
            self._send_json_response(status_code, response)
        elif parsed.path == "/api/inverters":
            status_code, response = handle_get_inverters()
            self._send_json_response(status_code, response)
        elif parsed.path == "/api/batteries":
            status_code, response = handle_get_batteries()
            self._send_json_response(status_code, response)
        elif parsed.path == "/api/tariffs":
            status_code, response = handle_get_tariffs()
            self._send_json_response(status_code, response)
        elif parsed.path == "/models/Dom.STL":
            self._serve_stl_file()
        else:
            # Serwowanie plikow statycznych (HTML, CSS, JS)
            super().do_GET()

    def do_POST(self):
        """
        Obsluga zapytan POST (np. wyslanie formularza z frontendu).

        - /api/simulate -> przeprowadza symulacje PV
        - /api/installation/configure -> konfiguruje instalacje i oblicza rozmieszczenie
        - /api/shading/simulate -> symulacja zacienienia i produkcji rocznej
        - wszystko inne -> blad 404 (nie znaleziono)
        """
        if self.path == "/api/simulate":
            # Odczytanie ciala zapytania (danych wyslanych przez frontend)
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_simulate(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/installation/configure":
            # Konfiguracja instalacji PV - oblicza rozmieszczenie paneli
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_installation_configure(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/shading/simulate":
            # Symulacja zacienienia - oblicza roczna produkcje z uwzglednieniem cienia
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_shading_simulate(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/energy-profile":
            # Profil zuzycia energii - generuje godzinowe zuzycie na rok
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_energy_profile(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/economics/analyze":
            # Analiza ekonomiczna - bilansowanie produkcji vs zuzycia
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_economics_analyze(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/report/generate":
            # Generowanie raportu - kompletna analiza instalacji PV
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_report_generate(body)
            self._send_json_response(status_code, response)
        elif self.path == "/api/scenarios/compare":
            # Porownanie scenariuszy - side-by-side tabela
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_scenarios_compare(body)
            self._send_json_response(status_code, response)
        else:
            self._send_json_response(404, {
                "error": "Nie znaleziono",
                "message": f"Endpoint {self.path} nie istnieje",
            })

    def do_OPTIONS(self):
        """
        Obsluga zapytan OPTIONS - potrzebne dla CORS.

        CORS (Cross-Origin Resource Sharing) to mechanizm bezpieczenstwa
        przegladarki. Pozwala frontendowi komunikowac sie z backendem
        nawet jesli sa na roznych adresach (np. podczas developmentu).
        """
        self.send_response(204)
        self._add_cors_headers()
        self.end_headers()

    def _handle_uldk_proxy(self, query_string: str):
        """
        Proxy do ULDK API (Uniwersalny Lokalizator Dzialek Katastralnych).

        Przekazuje zapytanie do uldk.gugik.gov.pl i zwraca odpowiedz.
        Dzialamy jako proxy zeby uniknac problemow z CORS w przegladarce.

        Dozwolone parametry: request, id, xy, result, srid
        """
        params = parse_qs(query_string)

        # Walidacja - musi byc przynajmniej parametr 'request'
        if "request" not in params:
            self._send_json_response(400, {
                "error": "Brak parametru",
                "message": "Parametr 'request' jest wymagany"
            })
            return

        # Dozwolone parametry do przekazania do ULDK
        allowed_params = ["request", "id", "xy", "result", "srid"]
        uldk_params = []
        for key in allowed_params:
            if key in params:
                # parse_qs zwraca listy wartosci - bierzemy pierwsza
                value = params[key][0]
                uldk_params.append(f"{key}={value}")

        uldk_url = f"https://uldk.gugik.gov.pl/?{('&').join(uldk_params)}"

        try:
            req = Request(uldk_url, headers={"User-Agent": "Symulator-PV/1.0"})
            with urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8", errors="replace")

            # Zwracamy odpowiedz jako tekst (ULDK zwraca plain text)
            response_body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(response_body)))
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(response_body)

        except HTTPError as e:
            self._send_json_response(502, {
                "error": "Blad ULDK",
                "message": f"Serwer ULDK zwrocil blad: {e.code}"
            })
        except (URLError, TimeoutError) as e:
            self._send_json_response(502, {
                "error": "Blad polaczenia",
                "message": f"Nie udalo sie polaczyc z serwerem ULDK: {e}"
            })

    def _serve_stl_file(self):
        """
        Serwuje plik Dom.STL (model 3D budynku) z katalogu glownego projektu.

        Plik jest binarny (format STL), wiec ustawiamy odpowiedni Content-Type.
        """
        stl_path = PROJECT_ROOT / "Dom.STL"

        if not stl_path.exists():
            self._send_json_response(404, {
                "error": "Nie znaleziono pliku",
                "message": "Plik Dom.STL nie istnieje w katalogu projektu"
            })
            return

        try:
            with open(stl_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", "application/sla")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Disposition", "inline; filename=\"Dom.STL\"")
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(content)

        except IOError as e:
            self._send_json_response(500, {
                "error": "Blad odczytu pliku",
                "message": f"Nie udalo sie odczytac pliku STL: {e}"
            })

    def _send_json_response(self, status_code: int, data: dict):
        """
        Wysyla odpowiedz JSON do klienta (frontendu).

        Parametry:
            status_code: kod HTTP (200 = ok, 400 = blad klienta, 500 = blad serwera)
            data: slownik ktory zostanie zamieniony na JSON
        """
        response_body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(response_body)

    def _add_cors_headers(self):
        """Dodaje naglowki CORS - pozwala na zapytania z innych adresow."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        """Nadpisujemy logowanie - wypisujemy po polsku."""
        print(f"[Serwer] {args[0]}")


def main():
    """Uruchamia serwer HTTP."""
    server = HTTPServer(("0.0.0.0", PORT), PVSimulatorHandler)
    print(f"=== Symulator PV - Serwer ===")
    print(f"Serwer uruchomiony na: http://localhost:{PORT}")
    print(f"Katalog frontendu: {FRONTEND_DIR}")
    print(f"Aby zatrzymac serwer, nacisnij Ctrl+C")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Serwer] Zatrzymano serwer.")
        server.shutdown()


if __name__ == "__main__":
    main()
