# Book Page Cleaner

Cel: automatycznie usunąć treść (tekst, zdjęcia, wpisy, grafiki) ze wszystkich widocznych kart księgi w filmie, zachowując możliwie naturalny papier, cienie, ruch, perspektywę, dłonie i przewracanie stron.

## Uruchomienie na Windows

1. Skopiuj film do `input/` (obsługiwane: MP4, MOV, MKV, AVI, M4V).
2. W PowerShell uruchom:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\run_windows.ps1
   ```

Skrypt tworzy lokalne `.venv`, jeśli go brakuje, instaluje zależności i zapisuje wynik
w `output/cleaned.mp4`. Oryginalny dźwięk jest kopiowany bez ponownego kodowania.

Bezpośrednie uruchomienie:

```powershell
.\.venv\Scripts\python.exe -m src.main --input input\film.mp4 --output output\cleaned.mp4 --device auto --quality best
```

Gdy `--input` jest pominięte, program wybiera pierwszy film z `input/`.

## Selektywne usuwanie ilustracji z wzorców

Tryb selektywny usuwa wyłącznie ilustracje dostarczone jako pliki PNG. Każdy wzorzec
jest traktowany jako cały prostokątny obszar do wyczyszczenia; tekst, inicjały i
ornamenty znajdujące się poza tym prostokątem pozostają bez zmian. Dopasowanie
uwzględnia perspektywę i ruch strony, a maska jest stabilizowana pomiędzy klatkami.

```powershell
.\.venv\Scripts\python.exe -m src.selective `
  --input input\film.mp4 `
  --output output\illustrations_removed.mp4 `
  --references work\illustration_references `
  --quality best
```

Opcja `--debug-overlay` zapisuje dodatkowy film diagnostyczny z zaznaczonymi
prostokątami. Oryginalny strumień audio jest kopiowany bez ponownego kodowania.

## Wstawianie własnych ilustracji na strony księgi

Tryb `replace` jest przygotowany do użycia wtedy, gdy masz już własne zdjęcia lub
ilustracje. Nie czyści całej kartki. Korzysta z prostokątnych wzorców zapisanych w
`work/illustration_references/` i usuwa wyłącznie rozpoznaną starą ilustrację.
Napisy, inicjały i ozdobniki poza tym polem pozostają z oryginalnego filmu.
Następnie program dopasowuje nowy obraz do oczyszczonego pola po lewej lub prawej
stronie. Obraz porusza się razem z kartką, jest przekształcany zgodnie z jej
perspektywą i otrzymuje światło oraz fakturę papieru. Wykryte dłonie i palce są
ponownie umieszczane przed ilustracją.

Prostokąty wzorców nie muszą być idealne. Po rozpoznaniu program ogranicza każdy
z nich do rzeczywistej powierzchni odpowiedniej kartki i cofa krawędzie o niewielki
margines. Ta skorygowana maska służy jednocześnie do czyszczenia i wstawiania,
dzięki czemu luźniejszy wzorzec nie powinien usuwać tekstu ani wychodzić poza papier.
Podczas przekładania strony maska i narożniki są prowadzone przepływem optycznym.

### Jak przygotować zdjęcia lub ilustracje

- Używaj plików PNG, JPG albo JPEG.
- Najlepiej przygotuj osobny obraz dla lewej i prawej strony każdej rozkładówki.
- Zalecane minimum to około 1500-2000 pikseli na dłuższym boku. Przy filmie Full HD
  lub 4K warto użyć większej rozdzielczości.
- Obraz przygotuj „na wprost”. Nie deformuj go samodzielnie do trapezu i nie dodawaj
  sztucznej perspektywy — zrobi to program.
- Nie dodawaj cieni imitujących kartkę. Program korzysta ze światła i cieni filmu.
- Zostaw kilka procent bezpiecznego marginesu przy krawędziach. Ważne napisy i
  twarze nie powinny znajdować się bardzo blisko brzegu.
- Najbezpieczniejszy profil kolorów to sRGB.
- Przezroczyste tło nie jest wymagane.
- Możesz używać zdjęć, grafik, skanów albo gotowych plansz z tekstem i obrazami.

Program zachowuje proporcje dostarczonego obrazu i umieszcza go z marginesem na
kartce. Nie trzeba przygotowywać ilustracji o dokładnym kształcie strony.

### Nazwy plików i miejsce ich skopiowania

Skopiuj obrazy do katalogu:

```text
replacement_pages/
```

Zalecane nazwy:

```text
spread_01_left.png
spread_01_right.png
spread_02_left.png
spread_02_right.png
```

`01`, `02` i następne numery oznaczają kolejne rozkładówki. `left` oznacza lewą
stronę, a `right` prawą. Jeśli usuniesz lub zmienisz nazwę `pages.yaml`, program
może przypisać tak nazwane pliki automatycznie w kolejności numerów.

### Ręczne przypisanie przez pages.yaml

Plik [replacement_pages/pages.yaml](replacement_pages/pages.yaml) pozwala wskazać,
który obraz ma trafić na konkretną rozkładówkę. Przykład:

```yaml
mode: replace
paper_blend_strength: 0.35

spreads:
  - id: 1
    left: replacement_pages/spread_01_left.png
    right: replacement_pages/spread_01_right.png

  - id: 2
    left: replacement_pages/spread_02_left.png
    right: replacement_pages/spread_02_right.png
```

Aby zmienić ilustrację, podmień ścieżkę po `left:` albo `right:`. Jeżeli strony
zostały zamienione, zamień miejscami te dwie ścieżki. Wpisz `null`, aby konkretna
strona pozostała pusta, na przykład:

```yaml
  - id: 3
    left: null
    right: replacement_pages/spread_03_right.jpg
```

`paper_blend_strength` przyjmuje wartość od `0` do `1`. Typowa wartość `0.35`
subtelnie przenosi fakturę i oświetlenie papieru. Większa wartość mocniej wtapia
obraz w kartkę. Przed renderem program sprawdza wszystkie ścieżki, formaty i
możliwość odczytania plików; błąd jest wyświetlany czytelnym komunikatem.

### Uruchomienie

Po przygotowaniu obrazów uruchom w PowerShell:

```powershell
.\.venv\Scripts\python.exe -m src.main `
  --input input\input.mp4 `
  --mode replace `
  --pages replacement_pages\pages.yaml `
  --mask-references work\illustration_references `
  --output output\replaced.mp4 `
  --quality best
```

Albo użyj skryptu Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_windows.ps1 -Mode replace -Pages replacement_pages\pages.yaml
```

Wynikiem jest `output/replaced.mp4` z oryginalnym strumieniem audio. Program tworzy
również klatki kontrolne w `output/replacement_preview/`, krótki
`output/replaced_preview.mp4`, raport tekstowy oraz — po dodaniu opcji
`--debug-overlay` — film z obrysami śledzonych stron. Opcja
`--paper-blend-strength 0.5` może tymczasowo zastąpić wartość z YAML.

### Gotowe polecenie dla Codexa

Skopiuj cały poniższy tekst i wklej go do Codexa dopiero po umieszczeniu własnych
obrazów w `replacement_pages/`:

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

### Prosty workflow

1. Skopiuj film do `input/`.
2. Skopiuj ilustracje do `replacement_pages/`.
3. Nazwij je zgodnie z instrukcją.
4. Opcjonalnie edytuj `pages.yaml`.
5. Wydaj Codexowi gotowe polecenie z poprzedniej sekcji.
6. Odbierz `output/replaced.mp4`.

Tryb `clean` nadal działa niezależnie i zapisuje `output/cleaned.mp4`. Samo
przygotowanie katalogu `replacement_pages/` nie zmienia istniejącego filmu ani
nie uruchamia podmiany.

## Opcje

- `--device auto|cuda|cpu` — automatyczny wybór urządzenia lub wymuszenie trybu;
- `--quality fast|balanced|best` — rozdzielczość analizy i dokładność rekonstrukcji;
- `--preview-seconds N` — przetworzenie pierwszych N sekund;
- `--keep-work` — zachowanie pośredniego strumienia wideo;
- `--debug-overlay` — utworzenie `output/debug_overlay.mp4` z wizualizacją maski.

Pipeline zapisuje także `output/report.txt`. `output/review_frames.txt` powstaje tylko,
gdy wykryte zostaną klatki o niskiej pewności.

## Zaimplementowany pipeline

- FFprobe odczytuje parametry i strumienie źródła.
- OpenCV wykrywa ciepłą powierzchnię papieru, domyka obszary zajęte przez duże grafiki,
  chroni zewnętrzne obrzeża oraz grzbiet i stabilizuje maskę w czasie.
- Kolor papieru jest rekonstruowany metodą ważonej normalizacji z czystych próbek w
  przestrzeni Lab; usuwa to tusz i ilustracje, zachowując gradienty oświetlenia.
- Deterministyczna, subtelna tekstura zapobiega sztucznie płaskiemu wyglądowi.
- FFmpeg koduje H.264 i dołącza oryginalny strumień audio.
- Sceny bez rozpoznanej otwartej księgi są przepuszczane bez zmian.

Backend nie wymaga CUDA i automatycznie działa na CPU. Jest przeznaczony zwłaszcza do
ujęć, w których papier jest jaśniejszy i cieplejszy od tła; trudne przewroty stron są
widoczne w opcjonalnym filmie diagnostycznym.

## Ograniczenia

Pełna automatyzacja nie zawsze będzie idealna. Trudne przypadki:

- bardzo szybkie przewracanie stron,
- silny motion blur,
- dłonie zakrywające większość strony,
- bardzo mała księga w kadrze,
- refleksy i błyszczący papier,
- częste cięcia montażowe,
- kilka podobnych książek jednocześnie.

W takich przypadkach projekt powinien wygenerować plik `output/review_frames.txt` z numerami klatek lub przedziałami czasowymi wymagającymi kontroli.

## Struktura

- `CODEX_PROMPT.md` – główne zadanie dla Codexa
- `AGENTS.md` – stałe instrukcje projektowe
- `requirements.txt` – lekkie zależności bazowe
- `install_windows.ps1` – instalacja bazowych narzędzi
- `run_windows.ps1` – uruchomienie pipeline'u
- `src/main.py` – punkt wejścia
- `src/pipeline.py` – bazowy szkielet pipeline'u
- `src/replacement.py` – konfiguracja, tracking i kompozycja trybu `replace`
- `input/` – film wejściowy
- `replacement_pages/` – przyszłe ilustracje użytkownika i `pages.yaml`
- `output/` – wynik
- `work/` – pliki tymczasowe

## Wymagania sprzętowe

Najlepiej:
- Windows 10/11,
- Python 3.11,
- NVIDIA GPU z CUDA i co najmniej 8 GB VRAM dla cięższych modeli.

CPU-only jest możliwe, ale może być bardzo wolne. Codex powinien automatycznie dobrać lżejszy wariant, jeśli GPU/CUDA nie są dostępne.
