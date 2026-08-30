#!/usr/bin/env python3
"""Merge Gradescope PDF exports while preserving submission identity."""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


METADATA_NAMES = ("submission_metadata.yml", "submission_metadata.yaml")


@dataclass(frozen=True)
class Submission:
    submission_id: str
    pdf_path: Path
    metadata: Any


def natural_id_key(value: str) -> tuple[int, int | str]:
    """Sort all-numeric IDs numerically, then other IDs alphabetically."""
    return (0, int(value)) if value.isdigit() else (1, value.casefold())


def clean_pasted_path(value: str) -> Path:
    """Accept a path copied from Explorer, including optional surrounding quotes."""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return Path(cleaned).expanduser()


def load_metadata(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        loaded = yaml.safe_load(stream)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a top-level mapping")
    return {str(key): value for key, value in loaded.items()}


def find_metadata(source_dir: Path, explicit_path: Path | None) -> Path | None:
    if explicit_path is not None:
        path = explicit_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Metadata file not found: {path}")
        return path
    for name in METADATA_NAMES:
        candidate = source_dir / name
        if candidate.is_file():
            return candidate
    return None


def discover_submissions(
    source_dir: Path,
    metadata: dict[str, Any],
    excluded_paths: Iterable[Path] = (),
) -> list[Submission]:
    excluded = {path.resolve() for path in excluded_paths}
    pdfs = {
        path.stem: path
        for path in source_dir.iterdir()
        if path.is_file() and path.suffix.casefold() == ".pdf" and path.resolve() not in excluded
    }
    if not pdfs:
        raise ValueError(f"No PDF files found in {source_dir}")

    submissions = [
        Submission(submission_id, pdf_path, metadata.get(submission_id))
        for submission_id, pdf_path in pdfs.items()
    ]
    return sorted(submissions, key=lambda item: natural_id_key(item.submission_id))


def submitter_names(metadata: Any) -> list[str]:
    """Read Gradescope's :submitters field without assuming every export has it."""
    if not isinstance(metadata, dict):
        return []
    raw_submitters = metadata.get(":submitters", metadata.get("submitters", []))
    if not isinstance(raw_submitters, list):
        return []

    names: list[str] = []
    for submitter in raw_submitters:
        if not isinstance(submitter, dict):
            continue
        name = submitter.get(":name", submitter.get("name"))
        if name is not None and str(name).strip():
            names.append(str(name).strip())
    return names


def pdf_page(width: float, height: float, draw: Any) -> Any:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    draw(pdf, width, height)
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def make_separator(submission: Submission, position: int, total: int, include_names: bool) -> Any:
    names = submitter_names(submission.metadata) if include_names else []

    def draw(pdf: canvas.Canvas, width: float, height: float) -> None:
        navy = HexColor("#17324D")
        blue = HexColor("#2E75B6")
        muted = HexColor("#536273")
        pdf.setFillColor(navy)
        pdf.rect(0, height - 88, width, 88, stroke=0, fill=1)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(48, height - 54, "GRADESCOPE SUBMISSION")

        pdf.setFillColor(blue)
        pdf.setFont("Helvetica-Bold", 30)
        pdf.drawString(48, height - 170, submission.submission_id)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, height - 199, f"Submission {position} of {total}")
        pdf.drawString(48, height - 219, f"Source file: {submission.pdf_path.name}")

        if names:
            pdf.setFont("Helvetica-Bold", 11)
            pdf.drawString(48, height - 259, "Submitter(s)")
            pdf.setFont("Helvetica", 11)
            y = height - 280
            for name in names:
                pdf.drawString(62, y, name[:90])
                y -= 18

        pdf.setFillColor(navy)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(48, 72, f"BEGIN SUBMISSION {submission.submission_id}")
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(48, 52, "The pages following this divider belong to the submission above.")

    return pdf_page(letter[0], letter[1], draw)


def make_page_label(width: float, height: float, text: str) -> Any:
    def draw(pdf: canvas.Canvas, _width: float, _height: float) -> None:
        pdf.setFillColorRGB(1, 1, 1, alpha=0.90)
        pdf.roundRect(8, height - 19, min(width - 16, 300), 14, 3, stroke=0, fill=1)
        pdf.setFillColor(HexColor("#17324D"))
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawString(12, height - 15, text)

    return pdf_page(width, height, draw)


def page_dimensions(page: Any) -> tuple[float, float]:
    return float(page.mediabox.width), float(page.mediabox.height)


def merge_submissions(
    submissions: Iterable[Submission],
    output_path: Path,
    include_names: bool,
    label_pages: bool,
) -> list[dict[str, Any]]:
    items = list(submissions)
    writer = PdfWriter()
    manifest: list[dict[str, Any]] = []

    writer.add_metadata(
        {
            "/Title": "Gradescope submissions",
            "/Subject": "Merged submissions with ID divider pages and bookmarks",
            "/Creator": "merge_gradescope_pdfs.py",
        }
    )

    for index, submission in enumerate(items, start=1):
        try:
            reader = PdfReader(submission.pdf_path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("PDF is password protected")
            if not reader.pages:
                raise ValueError("PDF has no pages")
        except Exception as exc:
            raise ValueError(f"Could not read {submission.pdf_path.name}: {exc}") from exc

        separator_page = len(writer.pages) + 1
        writer.add_page(make_separator(submission, index, len(items), include_names))
        writer.add_outline_item(f"Submission {submission.submission_id}", separator_page - 1)

        content_start = len(writer.pages) + 1
        for source_page_number, page in enumerate(reader.pages, start=1):
            if label_pages:
                if page.rotation:
                    page.transfer_rotation_to_content()
                width, height = page_dimensions(page)
                label = (
                    f"SUBMISSION ID: {submission.submission_id}  |  "
                    f"source page {source_page_number} of {len(reader.pages)}"
                )
                page.merge_page(make_page_label(width, height, label), over=True)
            writer.add_page(page)
        content_end = len(writer.pages)

        entry: dict[str, Any] = {
            "submission_id": submission.submission_id,
            "source_file": submission.pdf_path.name,
            "divider_page": separator_page,
            "content_pages": {"start": content_start, "end": content_end},
            "source_page_count": len(reader.pages),
        }
        if include_names:
            entry["submitters"] = submitter_names(submission.metadata)
        manifest.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        writer.write(stream)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge Gradescope PDFs into one document with divider pages, bookmarks, "
            "visible submission IDs, and a JSON page-range manifest."
        )
    )
    parser.add_argument(
        "source",
        nargs="?",
        type=Path,
        help="Unzipped Gradescope export folder (you will be prompted if omitted)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output PDF (default: gradescope_submissions_merged.pdf beside this script)",
    )
    parser.add_argument("--metadata", type=Path, help="Metadata YAML path (auto-detected by default)")
    parser.add_argument(
        "--include-names",
        action="store_true",
        help="Include submitter names from YAML (off by default for privacy)",
    )
    parser.add_argument(
        "--no-page-labels",
        action="store_true",
        help="Do not add a small submission-ID label to each source page",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    prompted_for_source = args.source is None
    if prompted_for_source:
        print("Paste the path to the unzipped Gradescope submissions folder.")
        try:
            pasted = input("Folder path: ")
        except EOFError:
            print("error: no folder path was provided", file=sys.stderr)
            return 2
        if not pasted.strip():
            print("error: no folder path was provided", file=sys.stderr)
            return 2
        source_dir = clean_pasted_path(pasted).resolve()
    else:
        source_dir = args.source.resolve()

    if not source_dir.is_dir():
        print(f"error: source folder not found: {source_dir}", file=sys.stderr)
        return 2

    try:
        script_dir = Path(__file__).resolve().parent
        output_path = (
            args.output.resolve()
            if args.output is not None
            else script_dir / "gradescope_submissions_merged.pdf"
        )
        metadata_path = find_metadata(source_dir, args.metadata)
        metadata = load_metadata(metadata_path) if metadata_path else {}
        submissions = discover_submissions(source_dir, metadata, excluded_paths=(output_path,))

        missing_ids = [item.submission_id for item in submissions if item.submission_id not in metadata]
        if metadata_path is None:
            print("warning: no submission_metadata.yml found; using PDF filenames as IDs", file=sys.stderr)
        elif missing_ids:
            print(
                f"warning: {len(missing_ids)} PDF(s) had no matching YAML entry; "
                "their filenames will still be used as IDs",
                file=sys.stderr,
            )

        manifest = merge_submissions(
            submissions,
            output_path,
            include_names=args.include_names,
            label_pages=not args.no_page_labels,
        )
        manifest_path = output_path.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    source_pages = sum(item["source_page_count"] for item in manifest)
    print(f"Merged {len(manifest)} submissions ({source_pages} source pages).")
    print(f"PDF:      {output_path}")
    print(f"Manifest: {manifest_path}")
    if prompted_for_source and sys.stdin.isatty():
        input("Press Enter to close...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
