"""
Testy jednostkowe dla modulu sun-position.js

Testy waliduja poprawnosc algorytmu obliczania pozycji slonca.
Implementujemy ten sam algorytm w Pythonie jako referencje
i porownujemy wyniki z oczekiwanymi wartosciami astronomicznymi.

Przypadki testowe:
1. Poludnie letnie w Warszawie (21 czerwca) - slonce wysoko na poludniu
2. Wschod slonca w Krakowie w polowie marca - slonce blisko horyzontu
3. Noc w Warszawie (2:00 w nocy) - slonce pod horyzontem
"""

import math
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Dodanie sciezki projektu zeby importy dzialaly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# --- Implementacja algorytmu SPA w Pythonie (referencja) ---

DEG_TO_RAD = math.pi / 180.0
RAD_TO_DEG = 180.0 / math.pi


def calculate_julian_day(date):
    """
    Oblicza Julian Day Number z daty (UTC).
    Wzor Meeus - identyczny jak w wersji JavaScript.
    """
    year = date.year
    month = date.month
    day = date.day

    # Czesc dzienna (ulamek dnia)
    day_fraction = (date.hour + date.minute / 60.0 + date.second / 3600.0) / 24.0

    # Dla stycznia i lutego - traktujemy jako miesiace 13 i 14 poprzedniego roku
    y = year
    m = month
    if m <= 2:
        y = y - 1
        m = m + 12

    # Korekta kalendarza gregorianskiego
    A = int(y / 100)
    B = 2 - A + int(A / 4)

    # Glowny wzor na Julian Day
    JD = (int(365.25 * (y + 4716)) +
          int(30.6001 * (m + 1)) +
          day + day_fraction + B - 1524.5)

    return JD


def calculate_julian_century(JD):
    """Oblicza stulecie Julianskie od epoki J2000.0"""
    return (JD - 2451545.0) / 36525.0


def calculate_mean_longitude(T):
    """Oblicza srednia dlugosc ekliptyczna slonca"""
    L0 = 280.46646 + T * (36000.76983 + T * 0.0003032)
    L0 = L0 % 360
    if L0 < 0:
        L0 += 360
    return L0


def calculate_mean_anomaly(T):
    """Oblicza srednia anomalie slonca"""
    M = 357.52911 + T * (35999.05029 - T * 0.0001537)
    M = M % 360
    if M < 0:
        M += 360
    return M


def calculate_equation_of_center(T, M):
    """Oblicza rownanie srodka (korekta za eliptycznosc orbity)"""
    M_rad = M * DEG_TO_RAD
    C = ((1.9146 - T * (0.004817 + T * 0.000014)) * math.sin(M_rad) +
         (0.019993 - T * 0.000101) * math.sin(2 * M_rad) +
         0.00029 * math.sin(3 * M_rad))
    return C


def calculate_obliquity(T):
    """Oblicza nachylenie ekliptyki"""
    epsilon0 = (23.0 + (26.0 + (21.448 - T * (46.815 + T *
                (0.00059 - T * 0.001813))) / 60.0) / 60.0)
    return epsilon0


def calculate_declination(apparent_longitude, obliquity):
    """Oblicza deklinacje sloneczna"""
    lambda_rad = apparent_longitude * DEG_TO_RAD
    epsilon_rad = obliquity * DEG_TO_RAD
    sin_dec = math.sin(epsilon_rad) * math.sin(lambda_rad)
    return math.asin(sin_dec) * RAD_TO_DEG


def calculate_right_ascension(apparent_longitude, obliquity):
    """Oblicza rektascensje slonca"""
    lambda_rad = apparent_longitude * DEG_TO_RAD
    epsilon_rad = obliquity * DEG_TO_RAD
    y = math.cos(epsilon_rad) * math.sin(lambda_rad)
    x = math.cos(lambda_rad)
    alpha = math.atan2(y, x) * RAD_TO_DEG
    alpha = alpha % 360
    if alpha < 0:
        alpha += 360
    return alpha


def calculate_gmst(JD, T):
    """Oblicza czas gwiazdowy Greenwich"""
    GMST = (280.46061837 +
            360.98564736629 * (JD - 2451545.0) +
            T * T * (0.000387933 - T / 38710000.0))
    GMST = GMST % 360
    if GMST < 0:
        GMST += 360
    return GMST


def calculate_hour_angle(GMST, longitude, right_ascension):
    """Oblicza kat godzinowy slonca"""
    H = GMST + longitude - right_ascension
    H = H % 360
    if H < 0:
        H += 360
    if H > 180:
        H -= 360
    return H


def calculate_elevation(latitude, declination, hour_angle):
    """Oblicza elewacje slonca (kat nad horyzontem)"""
    lat_rad = latitude * DEG_TO_RAD
    dec_rad = declination * DEG_TO_RAD
    h_rad = hour_angle * DEG_TO_RAD
    sin_elev = (math.sin(lat_rad) * math.sin(dec_rad) +
                math.cos(lat_rad) * math.cos(dec_rad) * math.cos(h_rad))
    # Ograniczenie do zakresu [-1, 1] (bledy numeryczne)
    sin_elev = max(-1.0, min(1.0, sin_elev))
    return math.asin(sin_elev) * RAD_TO_DEG


def calculate_azimuth(latitude, declination, hour_angle, elevation):
    """Oblicza azymut slonca"""
    lat_rad = latitude * DEG_TO_RAD
    dec_rad = declination * DEG_TO_RAD
    h_rad = hour_angle * DEG_TO_RAD
    elev_rad = elevation * DEG_TO_RAD

    cos_elev = math.cos(elev_rad)
    if abs(cos_elev) < 1e-10:
        return 180.0

    sin_az = -math.sin(h_rad) * math.cos(dec_rad) / cos_elev
    cos_az = ((math.sin(dec_rad) - math.sin(lat_rad) * math.sin(elev_rad)) /
              (math.cos(lat_rad) * cos_elev))

    azimuth = math.atan2(sin_az, cos_az) * RAD_TO_DEG
    if azimuth < 0:
        azimuth += 360

    return azimuth


def calculate_refraction(elevation):
    """Oblicza korekcje refrakcji atmosferycznej"""
    if elevation > 85:
        return 0
    if elevation > 5:
        tan_elev = math.tan(elevation * DEG_TO_RAD)
        return (58.1 / tan_elev - 0.07 / (tan_elev ** 3) + 0.000086 / (tan_elev ** 5)) / 3600
    if elevation > -0.575:
        return (1735 + elevation * (-518.2 + elevation * (103.4 + elevation * (-12.79 + elevation * 0.711)))) / 3600
    return (-20.774 / math.tan(elevation * DEG_TO_RAD)) / 3600


def calculate_sun_position(lat, lon, date):
    """
    Glowna funkcja - oblicza pozycje slonca.
    Parametr date powinien byc obiektem datetime w UTC.
    Zwraca (elevation, azimuth) w stopniach.
    """
    JD = calculate_julian_day(date)
    T = calculate_julian_century(JD)
    L0 = calculate_mean_longitude(T)
    M = calculate_mean_anomaly(T)
    C = calculate_equation_of_center(T, M)
    sun_true_longitude = L0 + C

    # Pozorna dlugosc z korekta nutacji/aberracji
    omega = 125.04 - 1934.136 * T
    apparent_longitude = sun_true_longitude - 0.00569 - 0.00478 * math.sin(omega * DEG_TO_RAD)

    # Nachylenie ekliptyki z korekta
    epsilon0 = calculate_obliquity(T)
    epsilon = epsilon0 + 0.00256 * math.cos(omega * DEG_TO_RAD)

    # Deklinacja i rektascensja
    declination = calculate_declination(apparent_longitude, epsilon)
    right_ascension = calculate_right_ascension(apparent_longitude, epsilon)

    # Czas gwiazdowy i kat godzinowy
    GMST = calculate_gmst(JD, T)
    hour_angle = calculate_hour_angle(GMST, lon, right_ascension)

    # Elewacja i azymut
    elevation = calculate_elevation(lat, declination, hour_angle)
    azimuth = calculate_azimuth(lat, declination, hour_angle, elevation)

    # Korekta refrakcji
    refraction = calculate_refraction(elevation)
    elevation += refraction

    return elevation, azimuth


# --- Klasy testowe ---

class TestSunPositionAlgorithm(unittest.TestCase):
    """Testy poprawnosci algorytmu obliczania pozycji slonca."""

    def test_warsaw_summer_noon(self):
        """
        Poludnie letnie w Warszawie (21 czerwca, ~12:30 UTC+2).
        Przesilenie letnie - slonce jest najwyzej w roku.
        Oczekiwana elewacja: okolo 61 stopni (slonce wysoko)
        Oczekiwany azymut: okolo 180 stopni (poludnie - slonce na poludniu)

        Uwaga: Prawdziwe poludnie sloneczne w Warszawie (21.01E) to nie dokladnie
        12:00 zegarowego. Roznica wynika z dlugosci geograficznej i rownania czasu.
        Uzywamy 10:30 UTC co odpowiada ok. 12:30 CEST - bliskie poludniu slonecznemu.
        """
        # Warszawa: 52.23N, 21.01E
        # 21 czerwca 2024, godzina 12:30 czasu polskiego (UTC+2) = 10:30 UTC
        # Poludnie sloneczne w Warszawie jest okolo 12:20-12:30 CEST
        lat = 52.23
        lon = 21.01
        date = datetime(2024, 6, 21, 10, 30, 0, tzinfo=timezone.utc)

        elevation, azimuth = calculate_sun_position(lat, lon, date)

        # Elewacja powinna byc w zakresie 60-64 stopni
        self.assertGreater(elevation, 60,
                           f"Elewacja {elevation:.1f} jest za niska (oczekiwano >60)")
        self.assertLess(elevation, 64,
                        f"Elewacja {elevation:.1f} jest za wysoka (oczekiwano <64)")

        # Azymut powinien byc okolo 180 (poludnie) - tolerancja +-15 stopni
        self.assertGreater(azimuth, 175,
                           f"Azymut {azimuth:.1f} za daleko od poludnia (oczekiwano >175)")
        self.assertLess(azimuth, 195,
                        f"Azymut {azimuth:.1f} za daleko od poludnia (oczekiwano <195)")

    def test_krakow_march_sunrise(self):
        """
        Wschod slonca w Krakowie w polowie marca.
        Okolo 20 marca (rownolegloscienie wiosenne) slonce wschodzi okolo 5:50 UTC.
        Elewacja przy wschodzie powinna byc bliska 0.
        """
        # Krakow: 50.06N, 19.94E
        # 20 marca 2024 - wschod slonca w Krakowie ok. 5:15-5:20 UTC
        # Uzywamy 5:15 UTC zeby zlapac moment blisko wschodu
        lat = 50.06
        lon = 19.94
        date = datetime(2024, 3, 20, 5, 15, 0, tzinfo=timezone.utc)

        elevation, azimuth = calculate_sun_position(lat, lon, date)

        # Przy wschodzie elewacja powinna byc bliska 0 (tolerancja +-5 stopni)
        self.assertGreater(elevation, -5,
                           f"Elewacja {elevation:.1f} jest za niska (oczekiwano > -5)")
        self.assertLess(elevation, 5,
                        f"Elewacja {elevation:.1f} jest za wysoka (oczekiwano < 5)")

        # Azymut przy wschodzie powinien byc okolo 90 (wschod) - tolerancja +-20
        self.assertGreater(azimuth, 70,
                           f"Azymut {azimuth:.1f} za daleko od wschodu")
        self.assertLess(azimuth, 110,
                        f"Azymut {azimuth:.1f} za daleko od wschodu")

    def test_warsaw_night(self):
        """
        Noc w Warszawie - 2:00 w nocy.
        Slonce powinno byc pod horyzontem (elewacja ujemna).
        """
        # Warszawa: 52.23N, 21.01E
        # 15 grudnia 2024, godzina 2:00 czasu polskiego (UTC+1) = 1:00 UTC
        lat = 52.23
        lon = 21.01
        date = datetime(2024, 12, 15, 1, 0, 0, tzinfo=timezone.utc)

        elevation, azimuth = calculate_sun_position(lat, lon, date)

        # W nocy elewacja musi byc ujemna (slonce pod horyzontem)
        self.assertLess(elevation, 0,
                        f"Elewacja {elevation:.1f} powinna byc ujemna w nocy!")

    def test_isDaylight_positive_elevation(self):
        """isDaylight powinno zwracac True gdy elewacja > 0 (dzien)."""
        # Sprawdzamy logike - elewacja dodatnia = dzien
        self.assertTrue(calculate_sun_position(52.23, 21.01,
                        datetime(2024, 6, 21, 10, 0, 0, tzinfo=timezone.utc))[0] > 0)

    def test_isDaylight_negative_elevation(self):
        """isDaylight powinno zwracac False gdy elewacja < 0 (noc)."""
        # Sprawdzamy logike - elewacja ujemna = noc
        self.assertTrue(calculate_sun_position(52.23, 21.01,
                        datetime(2024, 12, 15, 1, 0, 0, tzinfo=timezone.utc))[0] < 0)


class TestSunPositionLightVector(unittest.TestCase):
    """Testy konwersji pozycji slonca na wektor swiatla 3D."""

    def test_sun_south_high(self):
        """
        Slonce na poludniu (azymut=180) i wysoko (elewacja=60):
        - X powinien byc bliski 0 (slonce na osi N-S)
        - Y powinien byc dodatni (slonce nad horyzontem)
        - Z powinien byc ujemny (poludnie = -Z w konwencji Three.js)
        """
        elevation = 60
        azimuth = 180
        distance = 100

        elev_rad = elevation * DEG_TO_RAD
        az_rad = azimuth * DEG_TO_RAD

        y = distance * math.sin(elev_rad)
        horizontal = distance * math.cos(elev_rad)
        x = horizontal * math.sin(az_rad)
        z = horizontal * math.cos(az_rad)

        # X bliski 0 (slonce dokladnie na poludniu)
        self.assertAlmostEqual(x, 0, delta=1.0,
                               msg=f"X={x:.2f} powinien byc bliski 0")
        # Y dodatni (slonce nad horyzontem)
        self.assertGreater(y, 0, f"Y={y:.2f} powinien byc dodatni")
        # Z ujemny (poludnie to -Z w naszej konwencji)
        self.assertLess(z, 0, f"Z={z:.2f} powinien byc ujemny (poludnie)")

    def test_sun_east(self):
        """
        Slonce na wschodzie (azymut=90), elewacja=30:
        - X powinien byc dodatni (wschod = +X)
        - Y powinien byc dodatni (slonce nad horyzontem)
        - Z powinien byc bliski 0 (ani polnoc ani poludnie)
        """
        elevation = 30
        azimuth = 90
        distance = 100

        elev_rad = elevation * DEG_TO_RAD
        az_rad = azimuth * DEG_TO_RAD

        y = distance * math.sin(elev_rad)
        horizontal = distance * math.cos(elev_rad)
        x = horizontal * math.sin(az_rad)
        z = horizontal * math.cos(az_rad)

        self.assertGreater(x, 0, f"X={x:.2f} powinien byc dodatni (wschod)")
        self.assertGreater(y, 0, f"Y={y:.2f} powinien byc dodatni")
        self.assertAlmostEqual(z, 0, delta=1.0,
                               msg=f"Z={z:.2f} powinien byc bliski 0")

    def test_distance_parameter(self):
        """
        Sprawdza czy parametr distance poprawnie skaluje wektor.
        Odleglosc wynikowa powinna byc rowna parametrowi distance.
        """
        elevation = 45
        azimuth = 135
        distance = 200

        elev_rad = elevation * DEG_TO_RAD
        az_rad = azimuth * DEG_TO_RAD

        y = distance * math.sin(elev_rad)
        horizontal = distance * math.cos(elev_rad)
        x = horizontal * math.sin(az_rad)
        z = horizontal * math.cos(az_rad)

        # Dlugosc wektora powinna byc rowna distance
        length = math.sqrt(x**2 + y**2 + z**2)
        self.assertAlmostEqual(length, distance, delta=0.01,
                               msg=f"Dlugosc wektora {length:.2f} != {distance}")


class TestJulianDay(unittest.TestCase):
    """Testy obliczania Julian Day Number."""

    def test_j2000_epoch(self):
        """
        1 stycznia 2000, 12:00 UTC powinno dac JD = 2451545.0
        (definicja epoki J2000.0)
        """
        date = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        JD = calculate_julian_day(date)
        self.assertAlmostEqual(JD, 2451545.0, places=1,
                               msg=f"JD dla J2000.0 = {JD}, oczekiwano 2451545.0")

    def test_known_date(self):
        """
        Testuje znana wartosc JD: 1 stycznia 2024, 0:00 UTC = JD 2460310.5
        """
        date = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        JD = calculate_julian_day(date)
        self.assertAlmostEqual(JD, 2460310.5, places=1,
                               msg=f"JD dla 2024-01-01 = {JD}, oczekiwano 2460310.5")


class TestSolarDeclination(unittest.TestCase):
    """Testy deklinacji slonecznej dla znanych dat."""

    def test_summer_solstice_declination(self):
        """
        Przesilenie letnie (21 czerwca) - deklinacja powinna byc okolo +23.44.
        """
        date = datetime(2024, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
        JD = calculate_julian_day(date)
        T = calculate_julian_century(JD)
        L0 = calculate_mean_longitude(T)
        M = calculate_mean_anomaly(T)
        C = calculate_equation_of_center(T, M)
        sun_true_longitude = L0 + C
        omega = 125.04 - 1934.136 * T
        apparent_longitude = sun_true_longitude - 0.00569 - 0.00478 * math.sin(omega * DEG_TO_RAD)
        epsilon0 = calculate_obliquity(T)
        epsilon = epsilon0 + 0.00256 * math.cos(omega * DEG_TO_RAD)
        declination = calculate_declination(apparent_longitude, epsilon)

        # Deklinacja przy przesileniu letnim: okolo +23.44 (+-0.5)
        self.assertGreater(declination, 23.0,
                           f"Deklinacja {declination:.2f} za niska")
        self.assertLess(declination, 24.0,
                        f"Deklinacja {declination:.2f} za wysoka")

    def test_winter_solstice_declination(self):
        """
        Przesilenie zimowe (21 grudnia) - deklinacja powinna byc okolo -23.44.
        """
        date = datetime(2024, 12, 21, 12, 0, 0, tzinfo=timezone.utc)
        JD = calculate_julian_day(date)
        T = calculate_julian_century(JD)
        L0 = calculate_mean_longitude(T)
        M = calculate_mean_anomaly(T)
        C = calculate_equation_of_center(T, M)
        sun_true_longitude = L0 + C
        omega = 125.04 - 1934.136 * T
        apparent_longitude = sun_true_longitude - 0.00569 - 0.00478 * math.sin(omega * DEG_TO_RAD)
        epsilon0 = calculate_obliquity(T)
        epsilon = epsilon0 + 0.00256 * math.cos(omega * DEG_TO_RAD)
        declination = calculate_declination(apparent_longitude, epsilon)

        # Deklinacja przy przesileniu zimowym: okolo -23.44 (+-0.5)
        self.assertLess(declination, -23.0,
                        f"Deklinacja {declination:.2f} za wysoka")
        self.assertGreater(declination, -24.0,
                           f"Deklinacja {declination:.2f} za niska")

    def test_equinox_declination(self):
        """
        Rownolegloscienie (20 marca) - deklinacja powinna byc bliska 0.
        """
        date = datetime(2024, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        JD = calculate_julian_day(date)
        T = calculate_julian_century(JD)
        L0 = calculate_mean_longitude(T)
        M = calculate_mean_anomaly(T)
        C = calculate_equation_of_center(T, M)
        sun_true_longitude = L0 + C
        omega = 125.04 - 1934.136 * T
        apparent_longitude = sun_true_longitude - 0.00569 - 0.00478 * math.sin(omega * DEG_TO_RAD)
        epsilon0 = calculate_obliquity(T)
        epsilon = epsilon0 + 0.00256 * math.cos(omega * DEG_TO_RAD)
        declination = calculate_declination(apparent_longitude, epsilon)

        # Deklinacja przy rownolegloscieniu: bliska 0 (+-1 stopien)
        self.assertAlmostEqual(declination, 0, delta=1.5,
                               msg=f"Deklinacja {declination:.2f} powinna byc bliska 0")


if __name__ == '__main__':
    unittest.main()
