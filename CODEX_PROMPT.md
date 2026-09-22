Jesteś agentem programistycznym odpowiedzialnym za doprowadzenie tego projektu do działającego końca. Nie zatrzymuj się na samym szkielecie ani instrukcjach. Masz samodzielnie instalować brakujące zależności, poprawiać kod, uruchamiać testy i iterować aż pipeline będzie działał na filmie użytkownika.

CEL
====
Weź film umieszczony w katalogu `input/` i wygeneruj `output/cleaned.mp4`, w którym zawartość wszystkich widocznych kart księgi została usunięta. Kartki mają wyglądać naturalnie i na puste. Zachowaj możliwie wiernie:
- geometrię i perspektywę kart,
- fakturę papieru,
- cienie i zmiany oświetlenia,
- zagięcia i krzywizny,
- dłonie, palce i inne obiekty znajdujące się przed stroną,
- ruch kamery i księgi,
- oryginalny dźwięk filmu.

Treść do usunięcia obejmuje tekst, zdjęcia, podpisy, grafiki, naklejki, wydruki i ręczne wpisy. Nie usuwaj samej księgi ani krawędzi kartek.

TRYB PRACY
==========
1. Najpierw sprawdź system: Windows/Linux, Python, ffmpeg, GPU NVIDIA, CUDA, ilość VRAM.
2. Jeżeli czegoś brakuje, zainstaluj to automatycznie w sposób możliwie bezpieczny i lokalny dla projektu. Preferuj virtualenv `.venv`.
3. Nie wymagaj od użytkownika ręcznego instalowania bibliotek Pythona.
4. Pobierz potrzebne modele/wagi, jeżeli licencja i źródło na to pozwalają. Zapisuj je w `models/` lub cache projektu.
5. Jeżeli ciężki model nie działa, zastosuj automatyczny fallback.
6. Po każdej istotnej zmianie uruchom test lub krótki fragment filmu i oceniaj wynik technicznie.
7. Nie pytaj użytkownika o zgodę na normalne instalacje zależności projektu. Pytaj tylko, jeśli system wymaga uprawnień administratora lub działania destrukcyjnego.

PREFEROWANA ARCHITEKTURA
========================
A. Media
- ffprobe: parametry wejściowe,
- ffmpeg: dekodowanie/enkodowanie,
- zachowaj audio poprzez remux lub ponowne muxowanie z oryginału.

B. Detekcja i śledzenie stron
- preferuj SAM 2 / nowoczesną segmentację temporalną, jeśli dostępna,
- alternatywnie użyj OpenCV + detekcja konturów/prostokątów + optical flow / homografia,
- obsłuż cięcia scen i ponowną inicjalizację trackera,
- rozpoznaj jedną lub dwie otwarte strony książki.

C. Maska treści
- maskuj wnętrze kartki z marginesem bezpieczeństwa, ale zachowuj krawędzie,
- jeśli można, wykrywaj nadruk/zdjęcia i usuń je zamiast zamalowywać cały papier,
- w razie trudności można odtworzyć środek strony, pozostawiając zewnętrzny pas oryginalnej kartki.

D. Ochrona obiektów pierwszego planu
- dłonie, palce, zakładki i inne obiekty przed kartką nie mogą zostać usunięte,
- preferuj segmentację foreground/occlusion albo wykorzystaj różnice temporalne,
- przy compositingu foreground ma być na wierzchu.

E. Inpainting
Preferencja:
1. ProPainter,
2. E2FGVI,
3. inny dobry video inpainting,
4. fallback: rekonstrukcja papieru przy użyciu tekstury pobranej z czystych fragmentów strony + perspektywiczne mapowanie + zachowanie cieni/luminancji z oryginału.

F. Spójność czasowa
- unikaj migotania,
- wygładzaj maski temporalnie,
- stabilizuj parametry koloru i tekstury,
- stosuj interpolację/tracking zamiast niezależnego przetwarzania każdej klatki.

G. Kontrola jakości
Wygeneruj:
- `output/cleaned.mp4`,
- `output/preview.mp4` – opcjonalnie krótki podgląd porównawczy,
- `output/report.txt` – użyte backendy, GPU/CPU, czas filmu, rozdzielczość, FPS, liczba wykrytych segmentów stron,
- `output/review_frames.txt` – tylko gdy są fragmenty o niskiej pewności.

INTERFEJS
========
Główne uruchomienie ma działać tak:

    python -m src.main --input input/film.mp4 --output output/cleaned.mp4

Obsłuż też automatyczne znalezienie pierwszego filmu w `input/`, gdy `--input` nie podano.

Dodaj sensowne opcje CLI:
- `--device auto|cuda|cpu`
- `--quality fast|balanced|best`
- `--preview-seconds N`
- `--keep-work`
- `--debug-overlay`

TRYB DEBUG
==========
`--debug-overlay` powinien tworzyć film pokazujący maskę stron i ewentualnie maski dłoni/foreground, żeby dało się szybko ocenić błędy trackingu.

AUTOMATYCZNY DOBÓR JAKOŚCI
===========================
- CUDA + >= 12 GB VRAM: `best`, pełny video inpainting.
- CUDA + 6-12 GB VRAM: `balanced`, ewentualnie skalowanie robocze.
- CPU / mało VRAM: fallback geometry+texture, ewentualnie przetwarzanie w niższej rozdzielczości i finalny compositing w pełnej.

ZASADY IMPLEMENTACYJNE
======================
- Kod ma być czytelny, logowany i odporny na wznowienie.
- Cache'uj kosztowne wyniki w `work/`.
- Nie usuwaj pliku wejściowego.
- Nie zmieniaj FPS bez potrzeby.
- Zachowaj czas trwania filmu i audio-sync.
- Przy błędzie nie zostawiaj tylko stack trace; zapisz czytelny komunikat i możliwy fallback.
- Aktualizuj `README.md`, jeśli finalna procedura uruchomienia różni się od obecnej.

BARDZO WAŻNE
============
Nie kończ zadania stwierdzeniem „użytkownik musi ręcznie zaznaczyć strony”. Automatyzuj maksymalnie. Jeśli potrzebna jest inicjalizacja pierwszej sceny, spróbuj samodzielnej detekcji. Dopiero jeśli analiza filmu wykaże, że automatyczna detekcja jest niewiarygodna, dodaj opcjonalny mechanizm jednorazowego wskazania 4 narożników strony, ale pozostaw go jako tryb awaryjny.

Po zakończeniu uruchom pipeline na filmie użytkownika, sprawdź czy `output/cleaned.mp4` istnieje i czy ffprobe potwierdza poprawny strumień video oraz audio.
