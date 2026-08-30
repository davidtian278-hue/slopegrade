# Gradescope PDF merger

Turn a Gradescope bulk export into one chatbot-friendly PDF without losing which pages belong to which submission.

The merged PDF contains:

- a divider page before every submission;
- a visible submission-ID label on every source page;
- PDF bookmarks for quick navigation; and
- a JSON manifest mapping each submission ID to its merged page range.

Submitter names are excluded by default. The numeric Gradescope submission ID remains the link back to `submission_metadata.yml`.

## Setup

Python 3.10 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Use interactively

Run the script without a folder argument:

```powershell
python merge_gradescope_pdfs.py
```

When `Folder path:` appears, paste the path to the unzipped Gradescope folder and press Enter. Paths copied with surrounding quotes are accepted. The results are saved in the same directory as `merge_gradescope_pdfs.py`:

- `gradescope_submissions_merged.pdf`
- `gradescope_submissions_merged.manifest.json`

## Use with command-line arguments

Point the script at the unzipped Gradescope folder shown in the screenshot:

```powershell
python merge_gradescope_pdfs.py "C:\path\to\unzipped-submissions" -o "merged-submissions.pdf"
```

It automatically reads `submission_metadata.yml` and every PDF directly inside the folder. PDFs are ordered numerically by submission ID. The command creates:

- `merged-submissions.pdf`
- `merged-submissions.manifest.json`

If names are genuinely needed in the AI workflow, add `--include-names`. Be sure the chosen AI service is approved for student data first.

```powershell
python merge_gradescope_pdfs.py "C:\path\to\unzipped-submissions" -o "merged-submissions.pdf" --include-names
```

Use `--no-page-labels` if the small label at the top of each source page is undesirable. Divider pages and bookmarks are still retained.

## Suggested chatbot prompt

Upload the merged PDF and use a prompt such as:

> Treat each `GRADESCOPE SUBMISSION` divider as the start of a new, independent submission. The visible submission ID is the only identifier. Never carry an answer, comment, or grade across a divider. Return results keyed by submission ID.

## Notes

- The script never modifies the downloaded PDFs.
- A malformed, unreadable, or password-protected PDF stops the merge with the filename in the error.
- The YAML is optional unless names are requested; PDF filenames are sufficient for identity.
- A single large PDF solves file-count limits, but a chatbot may still have per-file size or page limits. Split the class into several source folders and run the script once per folder if necessary.
