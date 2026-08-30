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
                        20: {":submitters": [{":name": "Student Twenty"}]},
                        3: {":submitters": [{":name": "Student Three"}]},
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
            self.assertIn("Student Three", merged.pages[0].extract_text())
            self.assertIn("Student Twenty", merged.pages[2].extract_text())
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
