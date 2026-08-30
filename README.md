# Gradescope PDF merger

Turn a Gradescope bulk export into one easily readble PDF without losing which pages belong to which submission.

The merged PDF contains:

- a divider page before every submission;
- a visible submission-ID label on every source page;
- PDF bookmarks for quick navigation; and
- the submitter name from `submission_metadata.yml` on each divider.

The numeric Gradescope submission ID remains the stable link back to the original export.

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

When the folder prompt appears, paste the path to the unzipped Gradescope folder and press Enter. Paths copied with surrounding quotes are accepted. After the PDF is created, the prompt returns so you can process another folder. Submit a blank line when you are finished.

PDFs are saved in the `results` folder beside `merge_gradescope_pdfs.py`. Each filename is based on the source folder name. Existing results are never overwritten; `_2`, `_3`, and so on are added when necessary.

## Use with command-line arguments

Point the script at the unzipped Gradescope folder shown in the screenshot:

```powershell
python merge_gradescope_pdfs.py "C:\path\to\unzipped-submissions" -o "merged-submissions.pdf"
```

It automatically reads `submission_metadata.yml` and every PDF directly inside the folder. Metadata keys can be either `422145561.pdf` (Gradescope's usual export format) or `422145561`. PDFs are ordered from earliest to latest using Gradescope's submission timestamp (`created_at` or `submission_time`). Missing or unreadable timestamps are placed last and ordered numerically by submission ID. Unless `-o` is supplied, the command writes a uniquely named PDF into `results`.

Submitter names are included automatically. Be sure the chosen AI service is approved for student data.

Use `--no-page-labels` if the small label at the top of each source page is undesirable. Divider pages and bookmarks are still retained.

## Suggested chatbot prompt

Upload the merged PDF and use a prompt such as:

> Treat each `GRADESCOPE SUBMISSION` divider as the start of a new, independent submission. The visible submission ID is the only identifier. Never carry an answer, comment, or grade across a divider. Return results keyed by submission ID.

## Notes

- The script never modifies the downloaded PDFs.
- A malformed, unreadable, or password-protected PDF stops the merge with the filename in the error.
- The YAML is optional unless names are requested; PDF filenames are sufficient for identity.
- A single large PDF solves file-count limits, but a chatbot may still have per-file size or page limits. Split the class into several source folders and run the script once per folder if necessary.
