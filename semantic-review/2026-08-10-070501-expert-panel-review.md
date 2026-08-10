# Panel Ekspertów — Analiza Krytyczna Symulatora PV

## Podsumowanie

Symulator PV realizuje pełny łańcuch obliczeniowy: pozycja słońca → zacienienie → wydajność paneli → bilans energetyczny → analiza ekonomiczna. Kod jest czytelny i dobrze udokumentowany, ale zawiera liczne uproszczenia fizyczne i inżynierskie, które mogą prowadzić do błędów szacunków rzędu 10-30% w zależności od scenariusza.

---


### 1. Specjalista elektryk (instalacje elektryczne PV, falowniki, okablowanie, zabezpieczenia)

#### Zastrzeżenia:

1. **Brak modelowania łańcuchów string i konfiguracji MPPT** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: Symulator traktuje każdy panel niezależnie i sumuje ich moc. W rzeczywistości panele są połączone szeregowo w stringi, a cały string jest ograniczony przez najsłabsze ogniwo. Gdy jeden panel jest zacieniony, cały string traci moc (nawet z bypass diodami — tracisz 1/3 mocy stringa, nie tylko tego panela).
   - Jak powinno być: Modelowanie na poziomie stringa: identyfikacja które panele są w jednym stringu, obliczenie prądu ograniczającego dla stringa, uwzględnienie wpływu mismatch na MPPT falownika.
   - Dlaczego to ważne: Przy częściowym zacienieniu 2-3 paneli w jednym stringu realna strata mocy może być 2-3x większa niż wynika z prostego sumowania strat per panel. Dla instalacji 10+ paneli w jednym stringu to fundamentalny błąd.

2. **Brak modelu falownika i jego sprawności** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: Stałe straty systemowe 3% (`STRATY_SYSTEMOWE_DOMYSLNE = 0.03`) nie oddają rzeczywistego zachowania falownika. Sprawność falownika zależy od obciążenia: przy 5% mocy nominalnej sprawność spada do 80-85%, przy 20-100% jest 95-98%.
   - Jak powinno być: Krzywa sprawności falownika η(P_load/P_nom) — typowo η = 0 poniżej progu samozapłonu (~50W), η rośnie szybko do 90% przy 10% obciążeniu, plateau 96-98% przy 20-100%.
   - Dlaczego to ważne: Rano i wieczorem (niska produkcja) falownik pracuje z niską sprawnością. Dla lokalizacji 54°N z długimi godzinami niskiej irradiancji to może dać 3-5% dodatkowej rocznej straty.

3. **Stałe 3% strat nie uwzględnia strat kablowych zależnych od odległości** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Straty na kablach DC rosną z długością trasy i prądem. Dla instalacji naziemnej trasa kablowa może być dłuższa niż dachowa.
   - Jak powinno być: Straty = I²R, gdzie R zależy od przekroju i długości kabla. Typowo 1-2% DC + 0.5-1% AC.
   - Dlaczego to ważne: Dla małej instalacji naziemnej (krótka trasa) wpływ jest niewielki (~0.5-1% różnicy). Stałe 3% jest akceptowalnym przybliżeniem.

4. **Bypass diody modelowane jako binarne (>50% = aktywacja)** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: W `_oblicz_zacienienie_panela` bypass aktywuje się gdy sekcja zacieniona >50%. Rzeczywisty próg aktywacji zależy od prądu w stringu i napięcia diody — bypass aktywuje się gdy napięcie na sekcji spada poniżej -0.7V (napięcie diody). To zależy od stopnia zacienienia nawet 10-15% sekcji może aktywować bypass przy pełnym nasłonecznieniu reszty.
   - Jak powinno być: Model prądowo-napięciowy: bypass aktywuje się gdy prąd ograniczający zacienionej celi < prąd stringa - margines. Próg ~10-20% zacienienia sekcji, nie 50%.
   - Dlaczego to ważne: Próg 50% jest zbyt wysoki — symulator niedoszacowuje straty od zacienienia w przypadku częściowego cienia (np. cień ramy budynku padający na 20-30% jednej sekcji).

5. **Brak uwzględnienia napięcia startu falownika i cut-off** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Falownik potrzebuje minimalnego napięcia DC (typowo 150-200V) i minimalnej mocy (~50-100W) aby się uruchomić. Rano/wieczorem string może nie osiągać tych progów.
   - Jak powinno być: Warunek: P_string > P_start_inverter AND V_string > V_min_mppt.
   - Dlaczego to ważne: Wpływ na wynik roczny niewielki (kilka kWh/rok), bo dotyczy godzin z minimalną produkcją.


---

### 2. Specjalista energetyk (bilansowanie energii, rynek energii, taryfy, rozliczenia prosumenckie)

#### Zastrzeżenia:

1. **Cena sprzedaży prosumenta ≠ cena RCE netto** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: Funkcja `pobierz_cene_rce_sprzedaz()` zwraca cenę RCE netto (PLN/MWh ÷ 1000). W rzeczywistości prosument w Polsce od 2024 sprzedaje po "cenie rynkowej" pomniejszonej o opłatę handlową sprzedawcy (tzw. spread). Energa w Ofercie Dynamicznej II stosuje cenę TGE RDN FIXING I minus marża (typowo 0-5 gr/kWh w zależności od umowy).
   - Jak powinno być: Cena sprzedaży = CTGE_netto - marża_sprzedawcy (np. 0.02-0.05 PLN/kWh). Przy ujemnych cenach RCE prosument PŁACI za oddanie energii (to jest uwzględnione, dobrze).
   - Dlaczego to ważne: Przy rocznej sprzedaży ~3000-5000 kWh nadwyżki, marża 3 gr/kWh to 90-150 PLN/rok niedoszacowanego kosztu. Przy 5 gr to 150-250 PLN/rok.

2. **Średnia miesięczno-godzinowa cena RCE nie odzwierciedla zmienności dziennej** — Wpływ: **średni** — Warto poprawić: **nie (akceptowalne)**
   - Co jest źle: `_pobierz_srednia_godzinowa_z_cache()` uśrednia cenę RCE dla danej godziny w danym miesiącu ze WSZYSTKICH dostępnych dni. Cena RCE w poniedziałek o 14:00 może wynosić 50 PLN/MWh, a w piątek 400 PLN/MWh. Średnia (225) nie oddaje ani jednej sytuacji.
   - Jak powinno być: Idealnie: symulacja Monte Carlo z rozkładem cen lub użycie konkretnych profili dziennych (365 różnych dni). Ale dla porównania scenariuszy średnia jest akceptowalna.
   - Dlaczego to ważne: Zmienność cen wpływa na opłacalność magazynu — high spread (duża różnica min/max w dniu) faworyzuje magazyn. Średnia zaniża korzyść z magazynu przy taryfie dynamicznej.

3. **Oplata mocowa jako ryczałt — dobrze, ale brak progu 2800 kWh/rok** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Taryfy mają zapisane `oplata_mocowa_ryczalt: 29.58`, co jest stawką dla odbiorców >2800 kWh/rok. Dla odbiorców <2800 kWh/rok stawka jest niższa. Z PV + magazynem pobór z sieci może spaść poniżej progu.
   - Jak powinno być: Dynamiczny dobór stawki na podstawie rocznego poboru z sieci (obliczonego w symulacji).
   - Dlaczego to ważne: Dla prosumenta z dużą instalacją PV + magazynem (który pobiera <2800 kWh/rok z sieci) oszczędność ~10 PLN/mc. Ale w praktyce przy 7000 kWh zuzycia + pompa ciepła raczej się nie zejdzie poniżej progu.

4. **Brak opłaty przejściowej i opłaty OZE jako ryczałtu** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: W polskim systemie taryfowym jest kilka dodatkowych mikro-opłat (opłata przejściowa — ryczałt ~5-7 PLN/mc), które nie są uwzględnione.
   - Jak powinno być: Dodanie ich do opłat stałych.
   - Dlaczego to ważne: Rzędu 60-80 PLN/rok — nieistotne przy porównaniu scenariuszy (bo jest stałe niezależnie od instalacji PV).

5. **Algorytm dwuprzebiegowy magazynu — dobra koncepcja, ale potencjalny double-counting autokonsumpcji** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: W `economics.py` przy priorytecie "autokonsumpcja" i rozładowaniu w godzinie szczytowej z dodatnim bilansem: `autokonsumpcja_kwh -= nadwyzka_uwolniona / 1000.0` — odejmowanie od autokonsumpcji i jednoczesne dodanie do sprzedaży. Ale wcześniej w tej samej godzinie dodano `autokonsumpcja = zuzycie` (bo bilans ≥ 0). Więc logika: "magazyn pokrywa zużycie, PV idzie na sprzedaż" jest poprawna co do zasady, ale netto wynik autokonsumpcji może spaść poniżej 0 w skrajnym przypadku.
   - Jak powinno być: Dodać warunek `nadwyzka_uwolniona = min(energia_dostarczona, zuzycie_godziny, autokonsumpcja_bieżąca)` aby nie zejść poniżej 0.
   - Dlaczego to ważne: Może dawać ujemne wartości autokonsumpcji w miesiącach letnich, co psuje metrykę autokonsumpcji%.

6. **Brak bilansowania net-billing i rozliczenia w depozycie** — Wpływ: **średni** — Warto poprawić: **tak (jeśli docelowo chcemy porównać z net-billing)**
   - Co jest źle: System rozliczeń prosumenckich w Polsce (net-billing) zakłada depozyt — nadwyżka nie jest sprzedawana "od razu" po cenie RCE, ale trafia na konto depozytowe i jest rozliczana z przyszłym poborem. Symulator traktuje sprzedaż jako natychmiastowy przychód.
   - Jak powinno być: Model depozytu: nadwyżka → konto (PLN), pobór → odejmowanie z konta, niewykorzystana kwota po 12 miesiącach — zwrot 20% wartości.
   - Dlaczego to ważne: Net-billing z depozytem jest aktualnym systemem rozliczeń. Bez tego modelu wynik ekonomiczny może być optymistyczny o 10-20% (bo zakładamy pełną monetyzację nadwyżki).


---

### 3. Specjalista OZE (projektowanie instalacji PV, dobór komponentów, yield analysis)

#### Zastrzeżenia:

1. **Model irradiancji oparty na stałych miesięcznych szczytach — fundamentalne uproszczenie** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: `NAPROMIENIOWANIE_SZCZYTOWE_POLSKA` to 12 stałych wartości (150-900 W/m²) używanych jako "szczytowa irradiancja" danego miesiąca. Realne GHI zmienia się codziennie (zachmurzenie), a nie tylko co miesiąc. W styczniu w Polsce GHI może być 0-200 W/m² (zachmurzone dni) albo 400 W/m² (słoneczny dzień) — średnia ~80 kWh/m²/mc.
   - Jak powinno być: Dane TMY (Typical Meteorological Year) z PVGIS lub Meteonorm — 8760 wartości GHI/DNI/DHI dla lokalizacji. Minimum to miesięczne sumy z podziałem na beam/diffuse. Aktualnie model daje `GHI = szczytowe * sin(elewacja)` co jest fizycznie niepoprawne (GHI nie jest proporcjonalne do sin(elewacja) w ten sposób).
   - Dlaczego to ważne: To jest GŁÓWNE źródło błędu symulacji. Yield analysis bez danych meteorologicznych TMY jest wróżeniem z fusów. Różnica między dobrym a złym rokiem nasłonecznienia w Polsce to ±15%, a model ze stałymi szczytami nie oddaje nawet średniej.

2. **Brak rozdzielenia irradiancji na beam i diffuse** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: Model oblicza POA jakby cała irradiancja była promieniowaniem bezpośrednim (beam). W rzeczywistości w Polsce 40-60% rocznej irradiancji to promieniowanie rozproszone (diffuse), szczególnie zimą (70-80% diffuse).
   - Jak powinno być: GHI = DNI * sin(elewacja) + DHI. POA = DNI * cos(AOI) + DHI * (1+cos(tilt))/2 + GHI * albedo * (1-cos(tilt))/2. Model Perez lub Hay-Davies do przeliczenia diffuse na nachyloną płaszczyznę.
   - Dlaczego to ważne: Promieniowanie rozproszone dociera do panela niezależnie od kąta padania — panel nachylony 30° "widzi" ~85% nieba. Pominięcie diffuse zaniża produkcję zimową o 30-50% i zawyża wrażliwość na kąt nachylenia.

3. **Brak uwzględnienia albedo (odbicia od gruntu)** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Dla paneli naziemnych nachylonych 30° odbicia od gruntu (albedo ~0.2 trawa, ~0.6 śnieg) dają dodatkowe 2-5% irradiancji, szczególnie zimą ze śniegiem.
   - Jak powinno być: Dodatkowy składnik irradiancji: GHI * albedo * (1-cos(tilt))/2.
   - Dlaczego to ważne: Wpływ 2-5% rocznie — mały w kontekście innych uproszczeń.

4. **Brak uwzględnienia soiling (zabrudzenie) i śniegu** — Wpływ: **średni** — Warto poprawić: **tak (przynajmniej śnieg)**
   - Co jest źle: Panele naziemne są bliżej gruntu — bardziej narażone na zabrudzenie (kurz, pollen, ptasie odchody). Zimą śnieg zalega na panelach (30° nachylenia to za mało żeby zsunął się sam przy mokrym śniegu).
   - Jak powinno być: Straty soiling: 2-5% rocznie (stałe). Straty śnieg: redukcja produkcji o 50-100% w dniach ze śniegiem (grudzień-luty: ~10-20 dni/mc w północnej Polsce). Alternatywnie: mnożnik 0.7-0.8 na zimowe miesiące.
   - Dlaczego to ważne: Przy 30° nachyleniu i lokalizacji 54°N, straty od śniegu mogą wynosić 5-10% rocznej produkcji. Dla instalacji naziemnej z niskim prześwitem czyścić trudniej.

5. **Produkcja roczna nie jest walidowana z benchmarkiem PVGIS** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: Brak porównania wyniku symulacji z narzędziem referencyjnym (PVGIS, PVsyst, SAM). Dla 54°N, 30° nachylenia, azymut południe, 1 kWp instalacja powinna dawać 900-1050 kWh/rok. Bez walidacji nie wiadomo czy model daje sensowne wyniki.
   - Jak powinno być: Test regresyjny: `assert 900 < roczna_produkcja_kwh_per_kwp < 1100` dla typowej konfiguracji.
   - Dlaczego to ważne: Jeśli model daje 1300 kWh/kWp (zawyżony) lub 600 kWh/kWp (zaniżony) — cała analiza ekonomiczna jest bezwartościowa.

6. **Stała temperatura otoczenia per miesiąc (12 wartości)** — Wpływ: **średni** — Warto poprawić: **nie (akceptowalne)**
   - Co jest źle: `TEMPERATURA_OTOCZENIA_POLSKA = [-3, -1, 3, 9, 14, 17, 20, 19, 14, 9, 4, -1]` — jedna wartość na miesiąc. Nie uwzględnia zmienności dziennej (dzień/noc: ΔT = 8-12°C) ani ekstremalnych dni (35°C latem).
   - Jak powinno być: Temperatura godzinowa z danych TMY. Minimum: profil dobowy (T_max w 14:00, T_min o 5:00) z amplitudą zależną od miesiąca.
   - Dlaczego to ważne: Temperatura panela wpływa na moc przez współczynnik temperaturowy (-0.34 do -0.35%/°C). Przy T_panel = 60°C (gorący dzień) vs 45°C (średni) różnica mocy to ~5%. Średnia miesięczna daje poprawny wynik energetyczny w skali miesiąca, ale nie w konkretnych godzinach.


---

### 4. Profesor meteorologii (nasłonecznienie, dane klimatyczne, modelowanie pogody, zachmurzenie)

#### Zastrzeżenia:

1. **Całkowity brak modelu zachmurzenia — sunshine hours ≠ clear sky** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: Model `oblicz_napromieniowanie()` zakłada clear-sky conditions w KAŻDEJ godzinie gdy słońce jest nad horyzontem. Jedyny modulator to `NAPROMIENIOWANIE_SZCZYTOWE_POLSKA` — 12 stałych. W Polsce średnie zachmurzenie to 65-70% (jedno z najwyższych w Europie). Oznacza to, że w większości godzin realna irradiancja jest 20-80% wartości clear-sky.
   - Jak powinno być: Minimum: clearness index (Kt) per miesiąc. Kt = GHI_actual / GHI_clear_sky. Dla Polski: Kt = 0.35-0.45 zimą, 0.50-0.60 latem. Lepiej: godzinowe dane TMY z prawdziwymi pomiarami stacji meteorologicznej.
   - Dlaczego to ważne: To najważniejszy czynnik wpływający na produkcję PV. Model bez zachmurzenia może zawyżać produkcję 2-3x w miesiącach zimowych (gdzie Kt < 0.4). Stałe szczytowe wartości częściowo to kompensują (np. 150 W/m² dla grudnia to już po zachmurzeniu), ale nie oddają zmienności godzinowej.

2. **Brak uwzględnienia air mass i extinkcji atmosferycznej** — Wpływ: **średni** — Warto poprawić: **nie (kompensowane)**
   - Co jest źle: Irradiancja na szczycie atmosfery to ~1361 W/m². Na poziomie morza przy elewacji 90° to ~1000 W/m² (STC). Przy elewacji 10° air mass wynosi ~5.7, co redukuje beam do ~600 W/m². Model częściowo to kompensuje przez `GHI = szczytowe * sin(elewacja)`, ale to nie jest fizycznie poprawna zależność.
   - Jak powinno być: Model Linke-Feussner lub Ineichen: DNI = G_ext * exp(-TL * AM / (0.9 + 9.4/AM)), gdzie TL = Linke turbidity, AM = air mass.
   - Dlaczego to ważne: Błąd jest częściowo kompensowany przez kalibrację stałych szczytowych. Ale rano/wieczorem (AM > 3) irradiancja jest zawyżona, a w południe (AM ≈ 1.5) potencjalnie zaniżona. Efekt netto jest umiarkowany.

3. **Brak składowej promieniowania rozproszonego (diffuse)** — Wpływ: **duży** — Warto poprawić: **tak**
   - Co jest źle: (powtórzenie z perspektywy meteorologa) W Polsce promieniowanie rozproszone stanowi 50-60% rocznej sumy GHI. W grudniu to nawet 80%. Model nie rozdziela GHI na beam/diffuse. Panel nachylony 30° przy pełnym zachmurzeniu (100% diffuse) wciąż otrzymuje ~90% GHI (izotropowy model diffuse). Model aktualny dałby 0 W/m² bo `cos_theta` ≈ 0 przy zachmurzeniu (brak kierunkowego promieniowania).
   - Jak powinno być: Dekompozycja GHI na beam i diffuse (model Erbs, Orgill-Hollands, lub BRL). Następnie transpozycja na POA (model Perez, Hay-Davies).
   - Dlaczego to ważne: W dniach zachmurzonych (których w Polsce jest >200/rok) panel wciąż produkuje 20-40% mocy z diffuse. Pominięcie tego zaniża roczną produkcję o 15-25%.

4. **Dane temperatury nie odpowiadają północnej Polsce (54°N)** — Wpływ: **mały** — Warto poprawić: **tak (drobna korekta)**
   - Co jest źle: `TEMPERATURA_OTOCZENIA_POLSKA = [-3, -1, 3, 9, 14, 17, 20, 19, 14, 9, 4, -1]` — to profil dla centralnej Polski (Warszawa/Łódź). Dla 54°N (Gdańsk/Trójmiasto) temperatury są niższe zimą (-4 do -5°C styczeń) i niższe latem (17-18°C lipiec) ze względu na klimat morski.
   - Jak powinno być: Dla 54°N: [-4, -3, 1, 7, 12, 15, 18, 17, 13, 8, 3, -2]. Różnica ΔT = 1-3°C.
   - Dlaczego to ważne: Niższa temperatura to wyższa sprawność paneli (mniej strat temperaturowych). Efekt jest niewielki: 2°C * 0.35%/°C = 0.7% więcej mocy. Łącznie ~0.5-1% rocznej produkcji.

5. **Brak modelowania wiatru i jego wpływu na temperaturę panela** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Model NOCT (ΔT = 28°C stałe) zakłada standardowe warunki: wiatr 1 m/s. Lokalizacja nadmorska (54°N) ma wyższe średnie prędkości wiatru (3-5 m/s), co chłodzi panele efektywniej.
   - Jak powinno być: Model Faiman lub SAPM: T_cell = T_amb + Irr / (U0 + U1 * v_wind), gdzie v_wind = prędkość wiatru.
   - Dlaczego to ważne: Silniejszy wiatr obniża T_panel o 5-10°C → więcej mocy o 1.5-3%. Ale bez danych wiatrowych nie da się tego modelować, a stałe ΔT=28°C jest konserwatywne (zawyża temperaturę → zaniża moc → jest bezpieczne).

6. **Refrakcja atmosferyczna — poprawnie zaimplementowana** — Wpływ: **żaden** — Warto poprawić: **nie**
   - Model refrakcji w `solar_position.py` jest poprawny (formuła Meeus dla elewacji > 5° i empiryczna dla niskich elewacji). To jedyny element meteorologiczny zaimplementowany właściwie.


---

### 5. Profesor fizyki (optyka, termodynamika paneli, efekt fotowoltaiczny, promieniowanie)

#### Zastrzeżenia:

1. **Brak modelu strat optycznych (IAM — Incident Angle Modifier)** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: Model POA w `oblicz_napromieniowanie()` oblicza `cos(theta)` jako korekcję geometryczną, ale nie uwzględnia strat odbicia (Fresnel reflection) na szkle przy dużych kątach padania. Przy AOI > 60° straty odbicia rosną nieliniowo: 3% przy 60°, 10% przy 70°, 30% przy 80°.
   - Jak powinno być: IAM = 1 - b₀ * (1/cos(AOI) - 1), gdzie b₀ ≈ 0.05 (model ASHRAE) lub model fizyczny Martina-Ruiza. Mnożyć irradiancję beam przez IAM.
   - Dlaczego to ważne: Rano i wieczorem (AOI > 60°) symulator zawyża irradiancję na panelu o 5-15%. Sumarycznie wpływ roczny: 2-4% zawyżenia produkcji.

2. **Model temperaturowy NOCT jest nadmiernie uproszczony** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: `oblicz_temperature_panela()` oblicza T_panel jako T_otoczenia + ΔT * wsp_dnia, gdzie wsp_dnia jest trójkątnym profilem (0-1-0 w ciągu dnia). W rzeczywistości ΔT jest proporcjonalny do irradiancji: T_cell = T_amb + (NOCT - 20) * G / 800. Profil trójkątny nie oddaje faktu, że w pochmurny dzień panel się nie nagrzewa.
   - Jak powinno być: T_cell = T_amb + (NOCT - 20) * G_POA / 800, gdzie NOCT typowo = 43-47°C. Więc ΔT = (45-20) * G/800 = 25 * G/800 ≈ 31°C przy G=1000. Aktualny model ma stałe ΔT=28°C co jest akceptowalne średnio, ale nie łączy temperatury z irradiancją.
   - Dlaczego to ważne: W pochmurny dzień (G=200 W/m²): rzeczywiste ΔT = 6°C, model daje ΔT = 28*wsp_dnia ≈ 14-28°C (zawyżone). Wynik: symulator ZANIŻA produkcję w pochmurne dni (bo zawyża temperaturę panela → zawyża straty temperaturowe). Efekt kompensuje częściowo brak modelu zachmurzenia.

3. **Formuła POA ma błąd fizyczny w przeliczeniu** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: W `oblicz_napromieniowanie()`:
     ```
     ghi = szczytowe * sin_elewacja
     irradiancja_poa = ghi * cos_theta / sin_elewacja
     ```
     To upraszcza się do: `POA = szczytowe * cos_theta`. Ale to jest poprawne TYLKO jeśli `szczytowe` reprezentuje beam irradiance (nie GHI). Komentarz w kodzie mówi "irradiancja na płaszczyznę poziomą (GHI)" ale potem traktuje to jako beam. GHI = DNI * sin(elev) + DHI. Jeśli szczytowe to GHI_peak, to `GHI / sin(elev)` to NIE jest beam (bo pomija DHI).
   - Jak powinno być: Rozdzielić na: DNI = (GHI - DHI) / sin(elev), POA_beam = DNI * cos(AOI), POA_diffuse = DHI * (1+cos(tilt))/2. Albo przynajmniej: traktować stałą `szczytowe` jawnie jako DNI (direct normal irradiance) i nie mnożyć/dzielić przez sin(elewacja).
   - Dlaczego to ważne: Przy niskich elewacjach (rano/wieczorem): sin(elev) ≈ 0.17 (10°), więc "beam" = GHI/sin(10°) = GHI * 5.76 — to daje niefizyczne wartości. Jedynie ograniczenie `min(1000, ...)` ratuje wynik. To oznacza, że rano/wieczorem symulator ZAWSZE daje 1000 W/m² (cap) co jest błędem.

4. **Współczynnik temperaturowy mocy — poprawnie zastosowany** — Wpływ: **żaden** — Warto poprawić: **nie**
   - Formuła `wsp_temp = 1.0 + (coeff/100) * (T_panel - 25)` jest standardowa i poprawna. Ograniczenie [0.5, 1.2] jest rozsądne (chroni przed ekstremalnym wychłodzeniem dającym > 20% wzrostu mocy, co fizycznie nie zachodzi).

5. **Zacienienie na płaszczyźnie gruntu vs. na płaszczyźnie panela** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: Cień budynku jest rzutowany na płaszczyznę poziomą (y = przeswit_nad_gruntem), a panel jest reprezentowany przez swój rzut na tę samą płaszczyznę. To jest poprawne geometrycznie DLA RZUTU, ale panel jest nachylony — piksel na dole panela (bliżej gruntu) i piksel na górze (wyżej) mają RÓŻNĄ wrażliwość na cień z danego kierunku.
   - Jak powinno być: Rzutowanie cienia na płaszczyznę panela (nachyloną), nie na grunt. Transformacja współrzędnych: punkt na panelu (u,v) → punkt w 3D → sprawdzenie czy promień do słońca przecina budynek.
   - Dlaczego to ważne: Przy niskich elewacjach słońca i dużym kącie nachylenia (30°) różnica między cieniem na gruncie a cieniem na panelu może być 10-20%. Przy wysokich elewacjach różnica jest minimalna. Efekt roczny: 2-5% błędu w szacunku strat od zacienienia.

6. **Brak uwzględnienia wielokrotnych odbić i promieniowania podczerwonego** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Panele emitują promieniowanie cieplne (~80-100 W/m² w temperaturze 50°C) i absorbują promieniowanie długofalowe z otoczenia. Również odbicia od ziemi i sąsiednich paneli (ale tu jest jeden rząd).
   - Jak powinno być: Bilans radiacyjny: Q_absorbed = α*G_POA, Q_emitted = ε*σ*T⁴*A. Ale to jest wbudowane w model NOCT empirycznie.
   - Dlaczego to ważne: Model NOCT już empirycznie uwzględnia te efekty (NOCT jest mierzony w warunkach obejmujących emisję IR). Jawne modelowanie dałoby zysk dokładności <1%.


---

### 6. Szef działu R&D firmy projektującej panele PV (rzeczywista wydajność paneli, testy laboratoryjne vs pole, gwarancje)

#### Zastrzeżenia:

1. **LID (Light Induced Degradation) nie jest uwzględnione — pierwszy rok to nie 0.55%** — Wpływ: **średni** — Warto poprawić: **tak**
   - Co jest źle: Model degradacji `(1 - 0.005)^(rok-1)` zakłada stałą degradację 0.5%/rok od roku 1. W rzeczywistości pierwszy rok to LID: ~1.5-3% straty mocy (stabilizacja ogniw PERC/mono po pierwszej ekspozycji na światło). Od roku 2 degradacja spada do 0.4-0.55%/rok.
   - Jak powinno być: Rok 1: strata 2% (LID). Rok 2+: 0.45-0.55%/rok (liniowa). Formuła: P(rok) = P_stc * 0.98 * (1 - 0.005)^(rok-2) dla rok ≥ 2.
   - Dlaczego to ważne: LID powoduje 2% mniej energii w PIERWSZYM roku — to rok w którym liczy się ROI. Niedoszacowanie LID zawyża produkcję pierwszoroczną o 1.5-2%.

2. **Baza paneli — brak parametrów niskoświetlnych (low-light performance)** — Wpływ: **średni** — Warto poprawić: **nie (dane trudno dostępne)**
   - Co jest źle: Panele w `panels_database.json` mają tylko parametry STC (1000 W/m², 25°C). Brak danych NMOT/NOCT (800 W/m², 20°C) ani krzywych low-light (200 W/m²). Przy niskiej irradiancji (<200 W/m²) sprawność panela spada o 2-5% (wyższy wpływ rezystancji szeregowej i rekombinacji).
   - Jak powinno być: Dodanie parametrów: moc_nmot (przy 800 W/m²), sprawność_200wm2. Użycie modelu liniowej interpolacji sprawności między punktami.
   - Dlaczego to ważne: W Polsce 30-40% godzin produkcyjnych to irradiancja <400 W/m². Przy tych warunkach panel 21% STC efficiency daje realnie 19-20%. Efekt: 2-4% mniej energii rocznie.

3. **Współczynnik temperaturowy Pmax — dobry, ale brak współczynnika Voc** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Model używa tylko γ_Pmax (-%/°C). Brak β_Voc (zmiana napięcia z temperaturą) i α_Isc (zmiana prądu z temperaturą). Dla modelowania stringa i MPPT potrzebny jest β_Voc.
   - Jak powinno być: Dodanie β_Voc = -0.28%/°C i α_Isc = +0.05%/°C do bazy paneli.
   - Dlaczego to ważne: Bez modelowania stringa (patrz elektryk p.1) te parametry nie są potrzebne. Ale gdyby dodać model stringa, stają się niezbędne.

4. **Wszystkie panele w bazie to technologia half-cut — brak diversyfikacji** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: Wszystkie 12 modeli to half-cut PERC mono. Brak paneli standard (do porównania), brak paneli bifacial (dla montażu naziemnego), brak paneli TOPCon/HJT (Tiger Neo ma -0.29%/°C ale nie jest oznaczony jako n-type).
   - Jak powinno być: Dodanie 2-3 modeli bifacial (zysk 5-15% z albedo dla instalacji naziemnej!), oznaczenie technologii ogniw (PERC/TOPCon/HJT).
   - Dlaczego to ważne: Instalacja naziemna z prześwitem 50cm to IDEALNY kandydat na panele bifacial. Brak tej opcji w symulatorze to przeoczenie istotnego scenariusza (5-15% więcej energii bez zmiany footprintu).

5. **Degradacja roczna — różnice między modelami są znaczące** — Wpływ: **mały** — Warto poprawić: **nie (dane już różne w bazie)**
   - Co jest źle: Baza ma degradację 0.40-0.55%/rok co odpowiada realnym karnetom gwarancyjnym. Jinko Tiger Neo (n-type) ma 0.40% — to zgodne z gwarancją. JA Solar 0.55% — to trochę pesymistyczne (gwarancja JA to 0.50%). Dobrze że jest zróżnicowanie.
   - Jak powinno być: Wartości są akceptowalne. Jedyna uwaga: to są wartości GWARANTOWANE (górna granica). Realne pole to 0.3-0.5%/rok dla dobrych paneli.
   - Dlaczego to ważne: Po 25 latach: różnica między 0.40% a 0.55% to: (1-0.004)^25 = 90.4% vs (1-0.0055)^25 = 87.1%. To 3.3% różnicy w mocy na końcu życia. Istotne dla LCOE.

6. **Brak modelowania PID (Potential Induced Degradation)** — Wpływ: **mały** — Warto poprawić: **nie**
   - Co jest źle: PID to degradacja spowodowana wysokim napięciem systemowym (szczególnie wilgoć + ciepło + napięcie > 800V). Dla instalacji naziemnej z prześwitem (wentylacja) i nowoczesnych paneli (PID-free) to minimalny problem.
   - Jak powinno być: Dla paneli certyfikowanych PID-free (wszystkie w bazie) — ignorowanie jest poprawne.
   - Dlaczego to ważne: Nowoczesne panele Tier 1 są PID-resistant. To nie jest problem do modelowania.

7. **Mismatch losses pomiędzy panelami** — Wpływ: **średni** — Warto poprawić: **nie (wymaga modelu stringa)**
   - Co jest źle: Nawet identyczne panele mają rozrzut mocy ±3-5% (z karty: +5Wp/-0Wp tolerancja). Najsłabszy panel w stringu limituje prąd. Dodatkowo nierównomierne zacienienie powoduje mismatch.
   - Jak powinno być: Model stringa z uwzględnieniem rozkładu mocy paneli (Gaussian σ=2%). Ale wymaga modelu prądowo-napięciowego.
   - Dlaczego to ważne: Typowe straty mismatch: 1-2% (nowe panele) do 3-5% (po 10 latach z różną degradacją). Bez modelu stringa nie da się tego poprawnie zamodelować.

---

## Podsumowanie wpływów uproszczeń

| Kategoria | Uproszczenie | Kierunek błędu | Wpływ roczny |
|-----------|-------------|----------------|--------------|
| Meteorologia | Brak zachmurzenia/TMY | Zawyżenie LUB zaniżenie (zależy od kalibracji stałych) | ±20-30% |
| Fizyka | Brak diffuse | Zaniżenie produkcji | -15-25% |
| Fizyka | Błąd POA (cap 1000) | Zawyżenie rano/wieczorem | +5-10% |
| Elektryka | Brak modelu stringa | Zaniżenie strat od cienia | -5-15% (przy zacienieniu) |
| OZE | Brak soiling/śniegu | Zawyżenie produkcji | +3-8% |
| Optyka | Brak IAM | Zawyżenie produkcji | +2-4% |
| R&D | Brak LID | Zawyżenie rok 1 | +1.5-2% |
| Ekonomia | Brak net-billing depozytu | Zawyżenie przychodu | +10-20% ekonomicznie |

**Główne ryzyko**: Uproszczenia częściowo się kompensują (brak diffuse zaniża, brak zachmurzenia zawyża), ale wynik netto jest nieprzewidywalny bez walidacji z PVGIS/rzeczywistymi danymi pomiarowymi. Rekomendacja: porównanie wyniku symulacji z PVGIS jako test sanity check.

