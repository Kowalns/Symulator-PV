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

# Dodajemy katalog glowny projektu do sciezki importow
# (zeby Python mogl znalezc moduly backend.api, backend.services itp.)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.handlers import handle_health, handle_simulate


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
        - wszystko inne -> szuka pliku w katalogu frontend/
        """
        if self.path == "/api/health":
            status_code, response = handle_health()
            self._send_json_response(status_code, response)
        else:
            # Serwowanie plikow statycznych (HTML, CSS, JS)
            super().do_GET()

    def do_POST(self):
        """
        Obsluga zapytan POST (np. wyslanie formularza z frontendu).

        - /api/simulate -> przeprowadza symulacje PV
        - wszystko inne -> blad 404 (nie znaleziono)
        """
        if self.path == "/api/simulate":
            # Odczytanie ciala zapytania (danych wyslanych przez frontend)
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else None

            status_code, response = handle_simulate(body)
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
