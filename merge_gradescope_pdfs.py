#!/usr/bin/env python3
"""Merge Gradescope PDF exports while preserving submission identity."""

from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


METADATA_NAMES = ("submission_metadata.yml", "submission_metadata.yaml")
SUBMISSION_TIME_KEYS = (
    ":created_at",
    "created_at",
    ":submission_time",
    "submission_time",
    ":submitted_at",
    "submitted_at",
    ":timestamp",
    "timestamp",
)


@dataclass(frozen=True)
class Submission:
    submission_id: str
    pdf_path: Path
    metadata: Any


def natural_id_key(value: str) -> tuple[int, int | str]:
    """Sort all-numeric IDs numerically, then other IDs alphabetically."""
    return (0, int(value)) if value.isdigit() else (1, value.casefold())


def natural_filename_key(path: Path) -> tuple[Any, ...]:
    """Sort names so `Part 2.pdf` appears before `Part 10.pdf`."""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", path.name)
    )


def submission_time_value(metadata: Any) -> Any | None:
    if not isinstance(metadata, dict):
        return None
    for key in SUBMISSION_TIME_KEYS:
        if key in metadata and metadata[key] not in (None, ""):
            return metadata[key]
    return None


def parse_submission_time(value: Any) -> float | None:
    """Convert common Gradescope/YAML timestamp representations to Unix time."""
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        # Accommodate epoch milliseconds or microseconds if encountered.
        while abs(timestamp) > 32_503_680_000:
            timestamp /= 1000
        return timestamp
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            numeric = float(candidate)
        except ValueError:
            numeric = None
        if numeric is not None:
            while abs(numeric) > 32_503_680_000:
                numeric /= 1000
            return numeric
        if candidate.endswith(("Z", "z")):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            for date_format in (
                "%Y-%m-%d %H:%M:%S %z",
                "%Y/%m/%d %H:%M:%S %z",
                "%m/%d/%Y %I:%M:%S %p %z",
                "%m/%d/%Y %I:%M %p %z",
            ):
                try:
                    parsed = datetime.strptime(candidate, date_format)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def submission_sort_key(submission: Submission) -> tuple[Any, ...]:
    timestamp = parse_submission_time(submission_time_value(submission.metadata))
    if timestamp is None:
        return (1, 0.0, natural_id_key(submission.submission_id))
    return (0, timestamp, natural_id_key(submission.submission_id))


def clean_pasted_path(value: str) -> Path:
    """Accept a path copied from Explorer, including optional surrounding quotes."""
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        cleaned = cleaned[1:-1].strip()
    return Path(cleaned).expanduser()


def next_output_path(script_dir: Path, source_dir: Path) -> Path:
    """Return a non-conflicting PDF path inside the script's results folder."""
    safe_name = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in source_dir.name
    ).strip("._")
    safe_name = safe_name or "gradescope_submissions"
    results_dir = script_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    candidate = results_dir / f"{safe_name}_merged.pdf"
    sequence = 2
    while candidate.exists():
        candidate = results_dir / f"{safe_name}_merged_{sequence}.pdf"
        sequence += 1
    return candidate


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


def metadata_for_pdf(metadata: dict[str, Any], pdf_path: Path) -> Any | None:
    """Match Gradescope exports keyed by either `123.pdf` or `123`."""
    for candidate in (pdf_path.name, pdf_path.stem):
        if candidate in metadata:
            return metadata[candidate]

    # Be tolerant of an uppercase .PDF suffix or other casing differences.
    casefolded = {key.casefold(): value for key, value in metadata.items()}
    for candidate in (pdf_path.name, pdf_path.stem):
        if candidate.casefold() in casefolded:
            return casefolded[candidate.casefold()]
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
        Submission(submission_id, pdf_path, metadata_for_pdf(metadata, pdf_path))
        for submission_id, pdf_path in pdfs.items()
    ]
    return sorted(submissions, key=submission_sort_key)


def discover_reference_pdfs(reference_dir: Path) -> list[Path]:
    if not reference_dir.is_dir():
        return []
    pdfs = [
        path
        for path in reference_dir.iterdir()
        if path.is_file() and path.suffix.casefold() == ".pdf"
    ]
    return sorted(pdfs, key=natural_filename_key)


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


def make_separator(submission: Submission, position: int, total: int) -> Any:
    names = submitter_names(submission.metadata)

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

        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(48, height - 259, "Submitter(s)")
        pdf.setFont("Helvetica", 11)
        y = height - 280
        displayed_names = names or ["Name unavailable in submission_metadata.yml"]
        for name in displayed_names:
            pdf.drawString(62, y, name[:90])
            y -= 18

        pdf.setFillColor(navy)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(48, 72, f"BEGIN SUBMISSION {submission.submission_id}")
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(48, 52, "The pages following this divider belong to the submission above.")

    return pdf_page(letter[0], letter[1], draw)


def make_reference_separator(pdf_path: Path, position: int, total: int) -> Any:
    def draw(pdf: canvas.Canvas, width: float, height: float) -> None:
        navy = HexColor("#17324D")
        teal = HexColor("#168B87")
        muted = HexColor("#536273")
        pdf.setFillColor(teal)
        pdf.rect(0, height - 88, width, 88, stroke=0, fill=1)
        pdf.setFillColor(white)
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(48, height - 54, "REFERENCE DOCUMENT")

        pdf.setFillColor(navy)
        pdf.setFont("Helvetica-Bold", 24)
        title = pdf_path.stem
        if len(title) > 43:
            title = title[:40] + "..."
        pdf.drawString(48, height - 170, title)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(48, height - 201, f"Reference {position} of {total}")
        pdf.drawString(48, height - 221, f"Source file: {pdf_path.name}")

        pdf.setFillColor(teal)
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(48, 72, "BEGIN REFERENCE DOCUMENT")
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(48, 52, "This material applies to the submissions that follow.")

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
    label_pages: bool,
    reference_pdfs: Iterable[Path] = (),
) -> list[dict[str, Any]]:
    items = list(submissions)
    references = list(reference_pdfs)
    writer = PdfWriter()
    manifest: list[dict[str, Any]] = []

    writer.add_metadata(
        {
            "/Title": "Gradescope submissions and reference materials",
            "/Subject": "Reference documents followed by identified Gradescope submissions",
            "/Creator": "merge_gradescope_pdfs.py",
        }
    )

    for index, reference_path in enumerate(references, start=1):
        try:
            reader = PdfReader(reference_path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("PDF is password protected")
            if not reader.pages:
                raise ValueError("PDF has no pages")
        except Exception as exc:
            raise ValueError(f"Could not read reference PDF {reference_path.name}: {exc}") from exc

        separator_page = len(writer.pages) + 1
        writer.add_page(make_reference_separator(reference_path, index, len(references)))
        writer.add_outline_item(f"Reference: {reference_path.stem}", separator_page - 1)
        for source_page_number, page in enumerate(reader.pages, start=1):
            if label_pages:
                if page.rotation:
                    page.transfer_rotation_to_content()
                width, height = page_dimensions(page)
                label = (
                    f"REFERENCE: {reference_path.name}  |  "
                    f"source page {source_page_number} of {len(reader.pages)}"
                )
                page.merge_page(make_page_label(width, height, label), over=True)
            writer.add_page(page)

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
        writer.add_page(make_separator(submission, index, len(items)))
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
        manifest.append(entry)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as stream:
        writer.write(stream)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Merge optional reference PDFs and Gradescope submissions into one document "
            "with divider pages, bookmarks, and visible page labels."
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
        help="Output PDF (default: a unique name in the script's results folder)",
    )
    parser.add_argument("--metadata", type=Path, help="Metadata YAML path (auto-detected by default)")
    parser.add_argument(
        "--no-page-labels",
        action="store_true",
        help="Do not add a small submission-ID label to each source page",
    )
    return parser


def process_source(source_dir: Path, args: argparse.Namespace) -> int:
    if not source_dir.is_dir():
        print(f"error: source folder not found: {source_dir}", file=sys.stderr)
        return 2

    try:
        script_dir = Path(__file__).resolve().parent
        output_path = (
            args.output.resolve()
            if args.output is not None
            else next_output_path(script_dir, source_dir)
        )
        metadata_path = find_metadata(source_dir, args.metadata)
        metadata = load_metadata(metadata_path) if metadata_path else {}
        submissions = discover_submissions(source_dir, metadata, excluded_paths=(output_path,))
        references_dir = script_dir / "references"
        references_dir.mkdir(parents=True, exist_ok=True)
        reference_pdfs = discover_reference_pdfs(references_dir)

        missing_ids = [item.submission_id for item in submissions if item.metadata is None]
        missing_times = [
            item.submission_id
            for item in submissions
            if parse_submission_time(submission_time_value(item.metadata)) is None
        ]
        if metadata_path is None:
            print(
                "warning: no submission_metadata.yml found; using numeric submission-ID order",
                file=sys.stderr,
            )
        elif missing_ids:
            print(
                f"warning: {len(missing_ids)} PDF(s) had no matching YAML entry; "
                "their filenames will still be used as IDs",
                file=sys.stderr,
            )
        if metadata_path is not None and missing_times:
            print(
                f"warning: {len(missing_times)} submission(s) had no readable submission time; "
                "they were placed after timestamped submissions",
                file=sys.stderr,
            )

        manifest = merge_submissions(
            submissions,
            output_path,
            label_pages=not args.no_page_labels,
            reference_pdfs=reference_pdfs,
        )
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    source_pages = sum(item["source_page_count"] for item in manifest)
    if reference_pdfs:
        print(f"Added {len(reference_pdfs)} reference PDF(s) before the submissions.")
    print(f"Merged {len(manifest)} submissions ({source_pages} source pages).")
    print(f"PDF: {output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.source is not None:
        return process_source(args.source.resolve(), args)

    print("Paste the path to an unzipped Gradescope submissions folder.")
    print("After each merge you can paste another path. Leave it blank to finish.")
    final_status = 0
    while True:
        try:
            pasted = input("Folder path (blank to finish): ")
        except EOFError:
            print()
            return final_status
        if not pasted.strip():
            print("Finished.")
            return final_status
        status = process_source(clean_pasted_path(pasted).resolve(), args)
        if status != 0:
            final_status = status
        print()


if __name__ == "__main__":
    raise SystemExit(main())
