# Gradescope PDF merger

Turn a Gradescope bulk export into one organized PDF for convenient review without losing which pages belong to each submission.

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

Put materials such as the assignment and solution manual in the `references` folder beside `merge_gradescope_pdfs.py`. Every run automatically places those PDFs before the student submissions. Reference PDFs receive their own clearly marked dividers and are sorted naturally by filename (`Part 2` before `Part 10`). If the folder is empty, no reference pages are added.

Files inside `references` are intentionally ignored by Git so course materials and solution manuals are not committed. The empty folder is retained through `references/.gitkeep`; after cloning the project, simply copy your local PDFs into it.

PDFs are saved in the `results` folder beside `merge_gradescope_pdfs.py`. Each filename is based on the source folder name. Existing results are never overwritten; `_2`, `_3`, and so on are added when necessary.

## Use with command-line arguments

Point the script at the unzipped Gradescope folder shown in the screenshot:

```powershell
python merge_gradescope_pdfs.py "C:\path\to\unzipped-submissions" -o "merged-submissions.pdf"
```

It automatically reads `submission_metadata.yml` and every PDF directly inside the folder. Metadata keys can be either `422145561.pdf` (Gradescope's usual export format) or `422145561`. PDFs are ordered from earliest to latest using Gradescope's submission timestamp (`created_at` or `submission_time`). Missing or unreadable timestamps are placed last and ordered numerically by submission ID. Unless `-o` is supplied, the command writes a uniquely named PDF into `results`.

Submitter names are included automatically from the metadata file.

Use `--no-page-labels` if the small label at the top of each source page is undesirable. Divider pages and bookmarks are still retained.

## Notes

- The script never modifies the downloaded PDFs.
- A malformed, unreadable, or password-protected PDF stops the merge with the filename in the error.
- The YAML is optional, but it is required for submitter names and chronological ordering. Without it, PDF filenames provide submission identity and determine the order.
- Reference PDFs and generated files in `results` remain local because both locations are excluded from Git tracking.
- Large classes may produce a very large PDF. Split the class into several source folders and run the script once per folder if smaller review files are easier to manage.
