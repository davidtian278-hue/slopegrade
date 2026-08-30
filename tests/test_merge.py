import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from pypdf import PdfReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "merge_gradescope_pdfs.py"


def make_pdf(path: Path, pages: int) -> None:
    pdf = canvas.Canvas(str(path))
    for page_number in range(1, pages + 1):
        pdf.drawString(72, 720, f"Original page {page_number}")
        pdf.showPage()
    pdf.save()


class MergeTests(unittest.TestCase):
    def test_merge_keeps_ids_and_page_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_pdf(folder / "20.pdf", 2)
            make_pdf(folder / "3.pdf", 1)
            (folder / "submission_metadata.yml").write_text(
                yaml.safe_dump(
                    {
                        "20.pdf": {
                            ":created_at": "2026-08-30T08:00:00-04:00",
                            ":submitters": [{":name": "Student Twenty"}],
                        },
                        "3.pdf": {
                            ":submission_time": "2026-08-30 14:00:00+00:00",
                            ":submitters": [{":name": "Student Three"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            output = folder / "merged.pdf"

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(folder), "-o", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(len(PdfReader(output).pages), 5)
            merged = PdfReader(output)
            # 08:00 EDT is 12:00 UTC, so submission 20 precedes submission 3.
            self.assertIn("Student Twenty", merged.pages[0].extract_text())
            self.assertIn("Student Three", merged.pages[3].extract_text())
            self.assertFalse(output.with_suffix(".manifest.json").exists())

            # A second run must not ingest the previous output as a submission.
            repeated = subprocess.run(
                [sys.executable, str(SCRIPT), str(folder), "-o", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(len(PdfReader(output).pages), 5)

    def test_missing_submission_times_sort_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for submission_id in ("10", "20", "30"):
                make_pdf(folder / f"{submission_id}.pdf", 1)
            (folder / "submission_metadata.yml").write_text(
                yaml.safe_dump(
                    {
                        "10.pdf": {":created_at": "not a timestamp"},
                        "20.pdf": {":created_at": "2026-08-30T15:00:00Z"},
                        "30.pdf": {":created_at": "2026-08-30T14:00:00Z"},
                    }
                ),
                encoding="utf-8",
            )
            output = folder / "ordered.pdf"

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), str(folder), "-o", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            merged = PdfReader(output)
            divider_ids = [merged.pages[index].extract_text() for index in (0, 2, 4)]
            self.assertIn("30", divider_ids[0])
            self.assertIn("20", divider_ids[1])
            self.assertIn("10", divider_ids[2])
            self.assertIn("placed after timestamped submissions", completed.stderr)

    def test_reference_pdfs_are_naturally_sorted_before_submissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            copied_script = folder / SCRIPT.name
            shutil.copy2(SCRIPT, copied_script)
            submissions = folder / "submissions"
            references = folder / "references"
            submissions.mkdir()
            references.mkdir()
            make_pdf(submissions / "123.pdf", 1)
            make_pdf(references / "Part 10 Solution.pdf", 1)
            make_pdf(references / "Part 2 Assignment.pdf", 1)
            output = folder / "with-references.pdf"

            completed = subprocess.run(
                [
                    sys.executable,
                    str(copied_script),
                    str(submissions),
                    "-o",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            merged = PdfReader(output)
            self.assertEqual(len(merged.pages), 6)
            self.assertIn("Part 2 Assignment", merged.pages[0].extract_text())
            self.assertIn("Part 10 Solution", merged.pages[2].extract_text())
            self.assertIn("123", merged.pages[4].extract_text())
            self.assertIn("Added 2 reference PDF(s)", completed.stdout)

    def test_interactive_mode_repeats_and_uses_results_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            copied_script = folder / SCRIPT.name
            shutil.copy2(SCRIPT, copied_script)
            first_source = folder / "grade set one"
            second_source = folder / "grade set two"
            first_source.mkdir()
            second_source.mkdir()
            make_pdf(first_source / "12345.pdf", 1)
            make_pdf(second_source / "67890.pdf", 1)

            completed = subprocess.run(
                [sys.executable, str(copied_script)],
                input=f'"{first_source}"\n{second_source}\n\n',
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.count("Merged 1 submissions"), 2)
            results = folder / "results"
            self.assertTrue((results / "grade_set_one_merged.pdf").is_file())
            self.assertTrue((results / "grade_set_two_merged.pdf").is_file())
            self.assertEqual(list(results.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
