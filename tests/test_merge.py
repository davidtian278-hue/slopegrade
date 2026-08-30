import json
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
            manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([entry["submission_id"] for entry in manifest], ["3", "20"])
            self.assertEqual(manifest[0]["content_pages"], {"start": 2, "end": 2})
            self.assertEqual(manifest[1]["content_pages"], {"start": 4, "end": 5})
            self.assertNotIn("submitters", manifest[0])

            # A second run must not ingest the previous output as a submission.
            repeated = subprocess.run(
                [sys.executable, str(SCRIPT), str(folder), "-o", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertEqual(len(PdfReader(output).pages), 5)

    def test_prompts_for_quoted_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            make_pdf(folder / "12345.pdf", 1)
            output = folder / "interactive-result.pdf"

            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "-o", str(output)],
                input=f'"{folder}"\n',
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("Folder path:", completed.stdout)
            self.assertTrue(output.is_file())
            self.assertTrue(output.with_suffix(".manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
