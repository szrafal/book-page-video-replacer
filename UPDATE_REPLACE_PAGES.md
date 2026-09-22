# UPDATE: Wstawianie własnych ilustracji na oczyszczone strony księgi

## Cel aktualizacji

Rozszerz istniejący projekt czyszczenia stron księgi w filmie o możliwość wstawiania wskazanych przez użytkownika ilustracji w miejsce usuniętej zawartości.

Nie twórz nowego projektu. Zmodyfikuj istniejący pipeline i zachowaj wszystkie dotychczasowe funkcje czyszczenia.

Docelowo projekt ma obsługiwać dwa tryby:

1. `clean` – obecny tryb, w którym zawartość stron jest usuwana i pozostają naturalnie puste kartki.
2. `replace` – nowy tryb, w którym po oczyszczeniu strony na kartę nanoszona jest wskazana ilustracja.

## Wymagania funkcjonalne

### 1. Katalog z ilustracjami

Dodaj w projekcie katalog:

```text
replacement_pages/
```

oraz plik:

```text
replacement_pages/README.txt
```

W tym katalogu użytkownik będzie umieszczał ilustracje PNG lub JPG.

### 2. Konfiguracja przypisania ilustracji

Dodaj plik konfiguracyjny:

```text
replacement_pages/pages.yaml
```

Przykładowa struktura:

```yaml
mode: replace

spreads:
  - id: 1
    left: replacement_pages/spread_01_left.png
    right: replacement_pages/spread_01_right.png

  - id: 2
    left: replacement_pages/spread_02_left.png
    right: replacement_pages/spread_02_right.png
```

Jeżeli projekt identyfikuje pojedyncze strony zamiast rozkładówek, dopuszczalna jest równoważna struktura dopasowana do aktualnej architektury projektu.

### 3. Tryb automatyczny

Dodaj opcjonalny tryb automatyczny, w którym ilustracje są przypisywane kolejno według nazw plików.

Przykładowa kolejność:

```text
spread_01_left.png
spread_01_right.png
spread_02_left.png
spread_02_right.png
```

Jeżeli użytkownik nie dostarczy `pages.yaml`, projekt może spróbować użyć takiej kolejności automatycznie.

### 4. Renderowanie ilustracji

Ilustracja NIE może być zwykłym statycznym prostokątem nałożonym na film.

Dla każdej klatki należy:

- wyznaczyć geometrię aktualnej strony,
- dopasować ilustrację do perspektywy strony,
- wykorzystać homografię / transformację perspektywiczną lub lepszą metodę odpowiednią dla aktualnego pipeline'u,
- śledzić stronę pomiędzy klatkami,
- zachować stabilność temporalną,
- nie dopuszczać do "pływania" grafiki po kartce,
- uwzględnić obrót, skalę i zmianę perspektywy.

### 5. Zasłonięcia dłonią i innymi obiektami

Jeżeli dłoń, palec albo inny obiekt znajduje się przed stroną, ma pozostać przed ilustracją.

Wykorzystaj aktualne maski segmentacyjne, maski foreground lub dodaj odpowiednią obsługę occlusion.

Kolejność kompozycji powinna logicznie odpowiadać:

```text
tło filmu
-> oczyszczona strona
-> nowa ilustracja
-> cienie / faktura / światło strony
-> obiekty pierwszego planu, np. palce i dłonie
```

### 6. Naturalny wygląd ilustracji

Dodaj możliwość subtelnego dopasowania ilustracji do papieru:

- blend z fakturą papieru,
- zachowanie lokalnego oświetlenia,
- zachowanie cieni,
- delikatne dopasowanie jasności i kontrastu,
- opcjonalne lekkie zmiękczenie obrazu,
- możliwość ustawienia przez użytkownika `paper_blend_strength`.

Ilustracja powinna wyglądać jak wydrukowana lub wklejona do księgi, a nie jak cyfrowy overlay.

### 7. Stabilizacja temporalna

Priorytetem jest brak migotania.

Wykorzystaj aktualny tracking stron i w razie potrzeby dodaj:

- temporal smoothing,
- optical flow,
- stabilizację punktów narożnych,
- filtrowanie parametrów homografii.

### 8. Obsługa przewracania kartek

Jeżeli kartka jest przewracana:

- ilustracja powinna poruszać się razem z kartką tak długo, jak strona jest rozpoznawalna,
- nie może "wisieć" w przestrzeni po zniknięciu strony,
- po pojawieniu się nowej rozkładówki należy przełączyć się na ilustracje przypisane do kolejnego `spread`.

Jeżeli automatyczne wykrycie granicy rozkładówki jest niepewne, zapisz taki fragment do raportu do ręcznej kontroli.

### 9. CLI

Rozszerz obecny CLI, zachowując zgodność wsteczną.

Przykłady oczekiwanych poleceń:

```bash
python main.py --input input/film.mp4 --mode clean
```

oraz:

```bash
python main.py --input input/film.mp4 --mode replace --pages replacement_pages/pages.yaml
```

Jeżeli architektura projektu używa innej komendy wejściowej, dostosuj te opcje do istniejącego rozwiązania zamiast tworzyć równoległy system.

### 10. Wynik

Nowy plik wynikowy:

```text
output/replaced.mp4
```

Musi zachować oryginalny dźwięk.

Pozostaw również dotychczasowy:

```text
output/cleaned.mp4
```

dla trybu `clean`.

### 11. Podgląd i kontrola jakości

Dodaj możliwość wygenerowania klatek kontrolnych:

```text
output/replacement_preview/
```

Powinny zawierać reprezentatywne klatki dla każdej wykrytej rozkładówki.

Jeżeli to praktyczne, wygeneruj również:

```text
output/replaced_preview.mp4
```

krótszy podgląd ułatwiający ocenę efektu.

### 12. Walidacja

Przed renderowaniem sprawdź:

- czy wskazane pliki ilustracji istnieją,
- czy można je odczytać,
- czy mają poprawny format,
- czy konfiguracja nie odwołuje się do brakujących obrazów.

Wyświetl czytelny komunikat po polsku lub angielsku, ale bez tracebacku jako jedynej informacji dla użytkownika.

## README.md – obowiązkowa aktualizacja

Zaktualizuj istniejący `README.md`.

NIE usuwaj obecnych instrukcji. Dodaj nową, wyraźną sekcję po polsku zatytułowaną:

```text
## Wstawianie własnych ilustracji na strony księgi
```

Sekcja musi być napisana dla użytkownika nietechnicznego.

README ma dokładnie wyjaśnić:

### Jak przygotować zdjęcia / ilustracje

Napisz po polsku co najmniej:

- używaj PNG lub JPG,
- najlepiej przygotować osobny obraz dla lewej i prawej strony rozkładówki,
- zalecane minimum to około 1500-2000 px dłuższego boku,
- większa rozdzielczość jest lepsza, jeżeli film jest w Full HD lub 4K,
- nie trzeba samodzielnie deformować obrazu do perspektywy – zrobi to program,
- nie dodawać sztucznej perspektywy, trapezu ani cieni imitujących stronę,
- najlepiej dostarczać obraz "na wprost",
- zostawić kilka procent bezpiecznego marginesu przy krawędziach,
- ważne napisy i twarze nie powinny być bardzo blisko brzegu,
- profil kolorów najlepiej sRGB,
- ilustracje nie muszą mieć przezroczystego tła,
- użytkownik może używać zdjęć, grafik, skanów lub przygotowanych plansz.

### Nazewnictwo

Podaj rekomendowany sposób nazywania:

```text
spread_01_left.png
spread_01_right.png
spread_02_left.png
spread_02_right.png
```

Wyjaśnij, że:

- `01`, `02` oznaczają kolejne rozkładówki,
- `left` oznacza lewą stronę,
- `right` oznacza prawą stronę.

### Gdzie skopiować pliki

Podaj dokładnie:

```text
replacement_pages/
```

### Jak wydać polecenie Codexowi

Dodaj do README gotowy blok tekstu do skopiowania i wklejenia do Codexa.

Treść ma być w tym sensie:

```text
Przeczytaj README.md i uruchom projekt w trybie wstawiania ilustracji.

Film znajduje się w katalogu input/.
Moje ilustracje znajdują się w replacement_pages/.

Sprawdź pliki, dopasuj je do kolejnych stron księgi i wygeneruj wynikowy film.

Jeżeli pages.yaml istnieje, użyj przypisań z tego pliku.
Jeżeli go nie ma, spróbuj przypisać ilustracje automatycznie na podstawie nazw plików.

Zachowaj perspektywę, ruch stron, fakturę papieru, światło, cienie oraz prawidłowe zasłanianie ilustracji przez dłonie i palce.

Nie nakładaj ilustracji jako statycznych prostokątów.

Wygeneruj:
output/replaced.mp4

Zachowaj oryginalny dźwięk filmu.

Po zakończeniu sprawdź wizualnie reprezentatywne klatki każdej rozkładówki i popraw fragmenty, w których tracking, perspektywa lub zasłonięcia wyglądają nienaturalnie.
```

Możesz dostosować komendę do faktycznej architektury po aktualizacji projektu, ale README musi zawierać jednoznaczny, gotowy tekst dla użytkownika.

### Jak ręcznie sterować przypisaniem

W README wyjaśnij prostym językiem:

- do czego służy `pages.yaml`,
- jak zmienić ilustrację dla konkretnej rozkładówki,
- co zrobić, jeśli lewa i prawa strona zostały zamienione,
- jak wyłączyć ilustrację dla jednej strony, np. przez `null`, jeżeli implementacja to obsługuje.

### Przykładowy workflow

README powinien mieć uproszczony workflow:

```text
1. Skopiuj film do input/.
2. Skopiuj ilustracje do replacement_pages/.
3. Nazwij je zgodnie z instrukcją.
4. Opcjonalnie edytuj pages.yaml.
5. Wydaj gotowe polecenie Codexowi.
6. Odbierz output/replaced.mp4.
```

## Testy

Po wykonaniu aktualizacji:

1. uruchom testy istniejącego projektu,
2. dodaj testy dla parsowania konfiguracji replacement pages,
3. dodaj test sprawdzający brakujące pliki,
4. jeżeli jest możliwe, wykonaj krótki test renderowania na kilku klatkach,
5. nie usuwaj ani nie psuj trybu `clean`.

## Zasada implementacyjna

Najpierw przeczytaj istniejący kod i wykorzystaj aktualny pipeline detekcji, segmentacji, trackingu oraz czyszczenia stron.

Nie twórz drugiego niezależnego pipeline'u, jeżeli można rozszerzyć obecny.

Zachowaj dotychczasowe działanie projektu i jego strukturę tam, gdzie to możliwe.

## Kryterium zakończenia

Aktualizację uznaj za zakończoną dopiero, gdy:

- projekt nadal działa w trybie `clean`,
- działa tryb `replace`,
- istnieje katalog `replacement_pages/`,
- istnieje przykładowy `pages.yaml`,
- README.md zawiera pełne polskie instrukcje,
- testy przechodzą,
- Codex potrafi uruchomić test lub próbny render bez błędu konfiguracji.
