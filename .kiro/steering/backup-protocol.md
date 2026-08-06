# Protokol backupow sesji

> **OBOWIAZKOWE** - Kazda sesja Kiro pracujaca nad tym projektem MUSI przestrzegac tego protokolu.

---

## Zasada nadrzedna

Uzytkownik stracil wielogodzinna sesje pracy przez crash. Ten protokol istnieje po to, zeby to sie NIGDY wiecej nie powtorzylo. Kazda sesja musi zostawic po sobie pelny zapis stanu, aby nastepna sesja mogla kontynuowac bez zadnych strat.

---

## Obowiazki kazdej sesji

### Na poczatku sesji:
1. **Przeczytaj** `.kiro/backups/SESSION-LOG.md` - zrozum stan projektu
2. **Przeczytaj** `.kiro/steering/project-plan.md` - zrozum plan i decyzje
3. **Sprawdz testy** - `python3 -m unittest discover -s backend/tests -p 'test_*.py'`
4. **Sprawdz branch i PR** - `git log --oneline -5` i `git status`

### W trakcie sesji:
- Po kazdym znaczacym kroku (nowa funkcja, wazna decyzja, naprawiony bug) - zaktualizuj SESSION-LOG.md
- Nie czekaj do konca sesji z aktualizacja - sesja moze crashnac w dowolnym momencie!

### Na koniec sesji (lub przed przejsciem do innego zadania):
1. **Zaktualizuj** `.kiro/backups/SESSION-LOG.md`:
   - Dodaj nowe funkcjonalnosci do sekcji 3 (stan realizacji)
   - Zaktualizuj sekcje 7 (TODO) - co zostalo do zrobienia
   - Dodaj nowe decyzje do sekcji 2 (jesli podjeto)
   - Zaktualizuj status testow
   - Dodaj wpis do sekcji 11 (historia zmian)
2. **Commituj** backup: `git add .kiro/backups/SESSION-LOG.md && git commit -m "chore: aktualizacja backupu sesji"`
3. **Pushuj** na branch

---

## Co musi zawierac SESSION-LOG.md

| Sekcja | Zawartosc | Dlaczego |
|--------|-----------|----------|
| Cel projektu | Opis co budujemy i dla kogo | Nowa sesja musi rozumiec kontekst |
| Decyzje | Wszystkie podjete decyzje z uzasadnieniem | Aby nie podejmowac ich ponownie |
| Stan realizacji | Kazda funkcja: status, pliki, co robi, testy | Aby wiedziec co jest gotowe |
| Architektura | Struktura plikow i technologie | Aby wiedziec gdzie co jest |
| API | Endpointy i ich format | Aby wiedziec jak dzialaja interfejsy |
| TODO | Co zostalo do zrobienia, priorytety | Aby wiedziec co robic dalej |
| Znane problemy | Bugi, ograniczenia, workaroundy | Aby nie wchodzic w te same pulapki |
| Preferencje | Jezyk, styl, oczekiwania uzytkownika | Aby zachowac spojnosc komunikacji |
| Historia zmian | Kiedy co zmieniono w backupie | Aby sledzic postep |

---

## Format aktualizacji

Kiedy dodajesz nowa funkcjonalnosc do sekcji 3, uzyj tego formatu:

```markdown
#### FEAT-XXX: Nazwa funkcjonalnosci
- **Status:** DONE / IN_PROGRESS / BLOCKED
- **Pliki:** lista plikow
- **Co robi:** opis (szczegolowy, nie ogolnikowy)
- **Testy:** ktore pliki testow
- **Uwagi:** problemy napotkane, workaroundy
```

---

## Kiedy aktualizowac (KONKRETNIE)

Aktualizuj SESSION-LOG.md natychmiast po:
- Dodaniu nowego pliku
- Zaimplementowaniu nowej funkcji
- Naprawieniu buga
- Podjciu waznej decyzji projektowej
- Zmianie architektury lub struktury
- Dodaniu nowych testow
- Odkryciu nowego problemu lub ograniczenia

**NIE CZEKAJ do konca sesji.** Sesja moze crashnac. Commituj czesto.

---

## Jak odtworzyc sesje (instrukcja dla nowej sesji)

Jesli jestes nowa sesja Kiro i uzytkownik napisal cos w stylu "sprawdz backup i kontynuuj":

1. `git clone` / otwieranie repozytorium
2. Przeczytaj `.kiro/backups/SESSION-LOG.md` - to twoje zrodlo prawdy
3. Przeczytaj `.kiro/steering/project-plan.md` - pelny plan techniczny
4. Przeczytaj `.kiro/steering/backup-protocol.md` - ten plik (protokol)
5. Sprawdz stan testow: `python3 -m unittest discover -s backend/tests -p 'test_*.py'`
6. Sprawdz git: `git log --oneline -10`, `git status`, `git branch -a`
7. Zapytaj uzytkownika co chce robic dalej
8. Pracuj, commituj, AKTUALIZUJ BACKUP

---

## Reguly

1. **NIGDY nie usuwaj starych wpisow** z SESSION-LOG.md - tylko dodawaj nowe
2. **NIGDY nie skracaj opisu** - szczegoly sa wazniejsze niz zwiezlosc
3. **ZAWSZE commituj backup** przed zakonczeniem sesji
4. **ZAWSZE pushuj** na remote (jesli masz dostep)
5. **Jezyk:** polski (zgodnie z preferencjami uzytkownika)
6. **Format:** Markdown, z tabelami i naglowkami dla czytelnosci

---

## Struktura folderow backupow

```
.kiro/
├── steering/
│   ├── project-plan.md          # Plan techniczny projektu
│   └── backup-protocol.md      # TEN PLIK - zasady backupow
└── backups/
    └── SESSION-LOG.md           # Glowny backup stanu projektu
```

W przyszlosci, jesli projekt sie rozrosnie, mozna dodac:
- `.kiro/backups/DECISIONS-LOG.md` - osobny log decyzji
- `.kiro/backups/BUGS-LOG.md` - osobny log bugow i napraw

Ale na razie SESSION-LOG.md wystarcza jako pojedyncze zrodlo prawdy.

---

## Dlaczego to jest wazne

Uzytkownik placi za subskrypcje i oczekuje ciaglosci pracy. Utrata sesji = utrata godzin pracy = frustracja. Ten backup to ubezpieczenie. Koszt jego utrzymania (kilka minut per sesje) jest NICZYM w porownaniu z kosztem utraty calej sesji.

**Jesli nie jestes pewien czy cos dodac do backupu - DODAJ. Lepiej za duzo niz za malo.**
