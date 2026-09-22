# AGENTS.md

## Misja
Doprowadź projekt do działającego pipeline'u video-inpainting przeznaczonego do usuwania zawartości kart książki/albumu/księgi z filmu.

## Priorytety
1. Jakość wizualna.
2. Spójność czasowa bez migotania.
3. Zachowanie dłoni i obiektów foreground.
4. Automatyzacja.
5. Rozsądne wymagania sprzętowe.

## Zasady
- Możesz instalować zależności projektu.
- Preferuj `.venv`.
- Nie modyfikuj globalnego Pythona, jeśli nie trzeba.
- Nie usuwaj wejściowych plików.
- Wszystkie pliki generowane umieszczaj w `output/` lub `work/`.
- Pobierane modele umieszczaj w `models/` lub cache projektu.
- Jeśli zewnętrzne repo ma kod potrzebny do działania, vendoring/submodule/clone do `third_party/` jest dozwolony.
- Jeżeli projekt zewnętrzny ma konkretne wymagania wersji torch/CUDA, izoluj je w osobnym venv lub procesie.

## Definition of Done
Projekt jest gotowy, gdy:
- `run_windows.ps1` działa na Windowsie,
- `python -m src.main ...` działa,
- wynik zawiera audio,
- zawartość kart jest usunięta w większości klatek,
- problematyczne fragmenty są raportowane,
- README opisuje dokładne uruchomienie.
