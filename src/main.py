from __future__ import annotations

import argparse
from pathlib import Path
from rich.console import Console

from .pipeline import BookCleanerPipeline

console = Console()

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v"}


def find_input() -> Path:
    p = Path("input")
    files = [x for x in p.iterdir() if x.is_file() and x.suffix.lower() in VIDEO_EXTS]
    if not files:
        raise FileNotFoundError("No video found in input/")
    return sorted(files)[0]


def parse_args():
    ap = argparse.ArgumentParser(description="Clean book pages or place custom illustrations on them.")
    ap.add_argument("--input", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--mode", choices=["clean", "replace"], default="clean")
    ap.add_argument("--pages", type=Path, default=None,
                    help="YAML mapping for replacement mode; automatic filename order is used when omitted.")
    ap.add_argument("--replacement-dir", type=Path, default=Path("replacement_pages"))
    ap.add_argument("--mask-references", type=Path, default=Path("work/illustration_references"),
                    help="Reference rectangles identifying only the original illustrations to replace.")
    ap.add_argument("--paper-blend-strength", type=float, default=None)
    ap.add_argument("--no-replacement-preview", action="store_true")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    ap.add_argument("--quality", choices=["fast", "balanced", "best"], default="balanced")
    ap.add_argument("--preview-seconds", type=int, default=0)
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--debug-overlay", action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()
    src = args.input or find_input()
    output = args.output or Path("output/replaced.mp4" if args.mode == "replace" else "output/cleaned.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold]Input:[/bold] {src}")
    console.print(f"[bold]Mode:[/bold] {args.mode}")
    console.print(f"[bold]Output:[/bold] {output}")

    if args.mode == "replace":
        from .replacement import ReplacementPipeline

        pipeline = ReplacementPipeline(
            input_path=src,
            output_path=output,
            device=args.device,
            quality=args.quality,
            preview_seconds=args.preview_seconds,
            keep_work=args.keep_work,
            debug_overlay=args.debug_overlay,
            pages_path=args.pages,
            replacement_dir=args.replacement_dir,
            reference_dir=args.mask_references,
            paper_blend_strength=args.paper_blend_strength,
            create_preview=not args.no_replacement_preview,
        )
        try:
            pipeline.run()
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            console.print(f"[bold red]Błąd:[/bold red] {exc}")
            raise SystemExit(2) from None
        return

    pipeline = BookCleanerPipeline(
        input_path=src,
        output_path=output,
        device=args.device,
        quality=args.quality,
        preview_seconds=args.preview_seconds,
        keep_work=args.keep_work,
        debug_overlay=args.debug_overlay,
    )
    try:
        pipeline.run()
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        console.print(f"[bold red]Błąd:[/bold red] {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
