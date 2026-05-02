# MLP-Xplorer Methodology

This document explains the full workflow behind the project, from the review PDF to the local chat assistant.

## 1. Overall Architecture

The project is intentionally split into three layers:

1. `extracted_paper_raw.txt`
   This is the raw text version of the review paper after PDF-to-text conversion.
2. `build_paper_kb.py`
   This script cleans that raw text, repairs common extraction artifacts, parses dataset sections and references, and writes `paper_kb.json`.
3. `chat_paper.py`
   This script loads the structured JSON knowledge base, retrieves relevant dataset entries for a query, and either:
   - sends the selected context to DeepSeek, or
   - falls back to a local answer if DeepSeek is unavailable.

`run_paper_chat.py` is just the convenience launcher that rebuilds the knowledge base if needed and then starts the chat server.

## 2. PDF to Raw Text

The repository does not currently contain a PDF extraction script. Instead, it assumes that the paper was already converted into:

- `Ullah et al_2024_Molecular quantum chemical data sets and databases for machine learning.pdf`
- `extracted_paper_raw.txt`

So the current pipeline begins at the text stage, not at the PDF parsing stage.

That means:

- the PDF is the original source,
- `extracted_paper_raw.txt` is the machine-readable intermediate,
- and all later cleaning/parsing is done from that text file.

This design keeps the downstream logic reproducible even if the actual PDF extraction tool changes.

### Tool used in this project workflow

For the extraction work carried out in this project workflow, the PDF text was extracted with the local `pdftotext` binary found in the Git installation:

- `C:\Program Files\Git\mingw64\bin\pdftotext.exe`

So if you want to reproduce the same extraction approach used here, `pdftotext` is the tool to use.

### What can be said honestly about this project's current extraction step

The exact original extraction command was not preserved as a dedicated script in the repository.

So the current codebase does **not** prove that the text was extracted with one specific method such as:

- `pdftotext`,
- `PyMuPDF`,
- `pdfplumber`,
- `Apache Tika`,
- or OCR.

What we can infer from the text artifacts is that:

- the PDF likely had an embedded text layer,
- line wrapping came from page layout rather than image OCR alone,
- page headers/footers were copied into the text,
- and some characters were damaged by encoding or extraction mismatches.

So the practical assumption is:

- the raw text came from a text-layer extraction of the PDF,
- and `build_paper_kb.py` was then written to repair the resulting artifacts.

For this project documentation, the important practical fact is:

- the working extraction method used here is `pdftotext`,
- and the downstream pipeline is built around the kind of raw text that `pdftotext` produces for a born-digital scientific PDF.

### Recommended way to extract a scientific review PDF properly

If you want to reproduce this project from scratch, the safest workflow is:

1. First try **text-layer extraction** from the PDF.
2. Only fall back to OCR if the PDF is scanned or the extracted text is unusable.
3. Save the first-pass output as `extracted_paper_raw.txt`.
4. Inspect the references and section headings before running the builder.

For a born-digital journal PDF like this one, text-layer extraction is usually much better than OCR because it preserves:

- real characters instead of image guesses,
- citation numbers,
- punctuation,
- chemical formulas,
- and most author names.

### Recommended extraction tools

For this kind of paper, good options are:

- `pdftotext` from Poppler
- `PyMuPDF` (`fitz`)
- `pdfplumber`

#### Option A: `pdftotext` with layout preservation

This is often the best first attempt for scientific papers:

```powershell
pdftotext -layout "Ullah et al_2024_Molecular quantum chemical data sets and databases for machine learning.pdf" extracted_paper_raw.txt
```

Why `-layout` helps:

- it tends to preserve section structure,
- it often keeps references readable,
- and it reduces some sentence scrambling across columns.

Possible downside:

- it may preserve too much page-layout spacing and line wrapping, which then needs cleanup.

That tradeoff is acceptable here because `build_paper_kb.py` already collapses wrapped paragraphs later.

#### Option B: PyMuPDF extraction

This is a good Python-native option when you want more control:

```python
import fitz
from pathlib import Path

pdf_path = Path("Ullah et al_2024_Molecular quantum chemical data sets and databases for machine learning.pdf")
out_path = Path("extracted_paper_raw.txt")

doc = fitz.open(pdf_path)
parts = []
for page in doc:
    parts.append(page.get_text("text"))

out_path.write_text("\n\n".join(parts), encoding="utf-8")
```

This usually preserves:

- plain text well,
- Unicode better than some older extractors,
- and page order reliably.

But it can still include:

- headers,
- footers,
- page numbers,
- and line-broken references.

#### Option C: `pdfplumber`

Useful if you want to inspect page-level text carefully:

```python
import pdfplumber
from pathlib import Path

pdf_path = Path("Ullah et al_2024_Molecular quantum chemical data sets and databases for machine learning.pdf")
out_path = Path("extracted_paper_raw.txt")

parts = []
with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        parts.append(page.extract_text() or "")

out_path.write_text("\n\n".join(parts), encoding="utf-8")
```

### When OCR should be used

OCR should only be the fallback if:

- the PDF is image-only,
- text-layer extraction returns nearly empty output,
- or characters are catastrophically broken.

For OCR, a workflow such as:

- `ocrmypdf`
- or Tesseract-based extraction

can work, but OCR usually introduces new problems in scientific documents:

- citation brackets can be misread,
- superscripts and subscripts can be damaged,
- author names with accents can degrade,
- and formulas like `B97X-D/6-31G` can be corrupted.

So for papers like this, OCR is usually worse than direct text extraction unless the source PDF is scanned.

### How to extract in a way that keeps "everything intact" as much as possible

No PDF-to-text method keeps *everything* perfectly intact, because PDF is a page-description format, not a semantic document format. The practical goal is to preserve the parts that matter most for downstream parsing:

- section headings,
- paragraph order,
- reference numbering,
- author names,
- URLs/DOIs,
- and computational-method strings.

The best practice is:

1. Use a text-layer extractor first.
2. Prefer UTF-8 output.
3. Keep line breaks from the extractor instead of aggressively reflowing text immediately.
4. Save the untouched extraction as `extracted_paper_raw.txt`.
5. Create a cleaned derivative such as `extracted_paper.txt` only after inspection.
6. Manually spot-check:
   - section headers like `3.1`, `3.37`, `References`
   - dataset names like `QM9`, `SPICE`, `ANI-1x`, `QCDGE`
   - accented names like `Müller`, `Schütt`, `González`
   - reference ranges like `1-7`, `347-58`
   - URLs and DOIs

### Why this project keeps both raw and cleaned text

The repository keeps:

- `extracted_paper_raw.txt`
- `extracted_paper.txt`

for a reason.

`extracted_paper_raw.txt` is the archival extraction result.

`extracted_paper.txt` is the human-cleaned / normalized text used to inspect what the parser is seeing after repairs.

This separation is helpful because:

- the raw file preserves provenance,
- the cleaned file is easier to debug,
- and the builder logic can evolve without losing the original extracted source.

In practice, PDF-to-text conversion often introduces:

- page breaks and form-feed characters,
- running headers and author lines,
- broken line wrapping,
- encoding errors in names and accents,
- malformed punctuation,
- broken numeric ranges like `1�7`,
- and references split across several lines.

That is exactly what the builder script is designed to repair.

## 3. Cleaning the Raw Text

The first stage in `build_paper_kb.py` is `clean_text(...)`.

Its job is to remove layout artifacts that are useful on a PDF page but harmful for structured parsing. It removes:

- form-feed characters (`\x0c`),
- running journal headers such as `Mach. Learn.: Sci. Technol.`,
- repeated author lines such as `A Ullah et al`,
- and standalone page numbers.

After that, the script calls `normalize_text(...)`.

## 4. Correcting Broken Names, Numbers, and Reference Text

`normalize_text(...)` does targeted cleanup of extraction errors. The most important mechanism is the `TEXT_REPLACEMENTS` dictionary.

This dictionary contains specific fixes for repeated mojibake and OCR-like errors seen in the extracted review, for example:

- `M锟絣ler` -> `Müller`
- `Sch锟絫t` -> `Schütt`
- `Ram锟絩ez` -> `Ramírez`
- `Mart锟絥ez` -> `Martínez`
- `Cort茅s-Guzm-n` -> `Cortés-Guzmán`
- `Figsharehttps://doi.org` -> `Figshare https://doi.org`

This project uses targeted corrections rather than a generic encoding guesser because:

- the corpus is small,
- the errors are repeated and recognizable,
- and targeted substitutions are easier to audit than broad automatic repairs.

The script also applies regex-based cleanup for common structural problems, for example:

- broken ranges such as `347�58` or `1�7` are normalized,
- capitalization fixes like `Spice` -> `SPICE`,
- model/dataset spelling fixes like `Schnet` -> `SchNet`,
- and some punctuation/spacing issues are repaired.

`normalize_paragraph(...)` then rebuilds readable paragraphs by:

- collapsing line-broken PDF text into single paragraph blocks,
- removing excess blank lines,
- and preserving paragraph boundaries.

## 5. Reference Parsing

The paper's trailing bibliography is parsed by `parse_references(...)`.

The function:

1. finds the `References` section,
2. detects lines beginning with `[number]`,
3. groups continuation lines with the active reference,
4. rejoins them into single reference strings.

The result is a dictionary like:

```json
{
  "1": "Ramakrishnan R, Dral P O, Rupp M and Von Lilienfeld O A 2014 ...",
  "2": "von Lilienfeld O A, Müller K-R and Tkatchenko A 2020 ..."
}
```

This reference dictionary becomes the citation backbone for the chat system.

## 6. Extracting Dataset Sections

The review organizes datasets mainly in section `3.x`, so `parse_sections(...)` uses a regex that scans section blocks of the form:

- `3.1 ...`
- `3.2 ...`
- ...
- `3.37 Others`

Each section is converted into a structured dataset record with fields:

- `section`
- `dataset_name`
- `summary`
- `computational_methodology`
- `data_accessibility`
- `full_text`
- `cited_references`
- `reference_entries`

If a section explicitly contains labels like:

- `Computational methodology:`
- `Data accessibility:`

those parts are split into their own fields. Otherwise, the section is kept as a summary-style block.

## 7. Special Handling for Section 3.37 "Others"

Section `3.37. Others` is not one dataset. It is a bundle of multiple datasets in one shared subsection.

That is why `split_others_section(...)` exists.

It splits the single subsection into separate entries for:

- `C7O2H10-17`
- `ISO17`
- `VQM24`
- `QCDGE`
- `QM-22`
- `CheMFi`
- `QM9S`
- `TensorMol ChemSpider`

This is crucial for the chat system because otherwise a question like:

`What is QCDGE?`

would retrieve one giant mixed record instead of a QCDGE-specific one.

### Why citations had to be injected for these split entries

The paper lists the key citations for those datasets in the introductory sentence of the `Others` subsection, for example:

- `QCDGE [30]`
- `QM9S [37]`
- `CheMFi [11]`

But the later descriptive paragraphs often do not repeat the reference number.

So after splitting the block, the builder reinserts the appropriate dataset citation into each split record. That way, each dataset can still be cited properly by the chat assistant.

## 8. Synthetic References for Access Links

In several places, especially in `3.37 Others`, the paper gives a data link directly in the text rather than as a numbered bibliography item.

For example:

- a GitHub URL,
- a Zenodo DOI,
- a project website,
- or a now-dead Google Drive link.

To make the chat system able to cite those access points consistently, `add_synthetic_reference(...)` creates synthetic reference ids and stores them in the global references dictionary.

These synthetic references are not original paper bibliography items. They are added by this project so that:

- access links can be shown in the references block,
- and answers can cite both the dataset paper and the data location.

## 9. Building `paper_kb.json`

After cleaning, reference parsing, and section extraction, `build_paper_kb.py` writes the final knowledge base to `paper_kb.json`.

This file contains:

- paper metadata,
- the dataset count,
- the structured dataset entries,
- and the full reference dictionary.

This JSON file is the main retrieval source for the chat assistant.

## 10. Manual Dataset Extension

The paper is only the starting corpus. To support future datasets, the system also loads `extra_datasets.json`.

This file is meant for datasets that:

- appeared after the review,
- were not covered in the paper,
- or need manual enrichment.

At runtime, `chat_paper.py` merges:

- `paper_kb.json`
- `extra_datasets.json`

into one working knowledge base.

## 11. Retrieval and Query Handling

The chat server does not send the whole paper to the model. It retrieves only the most relevant dataset records for each question.

The core retrieval logic is `select_context(...)`.

It works in stages:

1. If the question is a follow-up, try to reuse the last retrieved context.
2. If the user explicitly names a dataset, honor that direct match.
3. If the user asks for a comparison, gather multiple explicit datasets.
4. Otherwise, score all dataset records using a lightweight lexical overlap method.

This is a deliberately simple RAG-style design:

- small corpus,
- structured entries,
- transparent retrieval,
- easy debugging.

## 12. Follow-Up Question Handling

One of the hardest problems in the project was follow-up drift.

Example:

1. `Compare SPICE, ANI-1x, and MD17`
2. `Which one is better in accuracy?`

If the second message is treated as a fresh search, the assistant can drift to unrelated datasets.

To reduce that, `chat_paper.py` keeps a backend session state with fields like:

- `active_datasets`
- `active_aliases`
- `last_context_dataset_names`
- `last_context_references`
- `last_query_type`
- `last_topic`

Then vague follow-ups are rewritten internally into self-contained forms tied to the previous scope.

So instead of searching the whole KB for:

`which one is better?`

the system can reinterpret it more like:

`Among SPICE, ANI-1x, and MD17, which one is better in accuracy?`

## 13. Prompt Construction for DeepSeek

`build_prompt(...)` creates the model input from:

- the user question,
- the selected dataset blocks,
- and only the relevant reference entries.

The prompt tells DeepSeek to:

- use the provided context as the primary grounded source,
- cite paper-grounded claims with reference numbers,
- avoid inventing citations,
- and include a `References` section.

The prompt also allows the model to add limited general background from its own knowledge, but only if it distinguishes that from paper-grounded claims.

## 14. Fallback Mode When DeepSeek Fails

If the API call fails, the app does not stop. Instead it uses `build_local_fallback_answer(...)`.

That function assembles an answer directly from the retrieved JSON fields:

- summary,
- methodology,
- accessibility,
- and relevant reference entries.

This is why the app can still answer even when DeepSeek is unavailable.

## 15. Reference Formatting in Chat Answers

The chat layer normalizes output references with:

- `format_reference_entry(...)`
- `ensure_reference_section(...)`

This serves two purposes:

1. references are reformatted into a cleaner human-readable style,
2. duplicate model-generated reference blocks are replaced by one standardized final block.

So even if the model already outputs its own reference section, the application post-processes the answer and appends one canonical `References` block.

## 16. The Web Interface

`chat_paper.py` also embeds the HTML, CSS, and JavaScript UI directly in the same file.

The interface:

- serves a local chat page,
- sends requests to `/api/chat`,
- stores a browser session id,
- stores recent user prompts for the right-side history panel,
- and renders rich text for answers.

This all runs on Python's built-in `HTTPServer`, so there is no separate frontend build step.

## 17. What `run_paper_chat.py` Does

`run_paper_chat.py` is just the operator script.

It checks whether `paper_kb.json` is older than:

- `extracted_paper_raw.txt`
- or `extra_datasets.json`

If so, it rebuilds the KB. Then it starts the chat server.

That is why the normal workflow is:

```powershell
py -3 run_paper_chat.py
```

## 18. Important Practical Limitation

The biggest limitation in the current pipeline is that PDF extraction itself is external to the codebase.

That means if the initial PDF-to-text conversion is poor, the later cleaning has to compensate for it. The current scripts do a lot of repair work, but they still depend on:

- the quality of `extracted_paper_raw.txt`,
- the consistency of section headings,
- and the stability of reference numbering in the source paper.

## 19. Source of Truth

It helps to think of the project like this:

- PDF = original human source
- `extracted_paper_raw.txt` = extracted machine source
- `build_paper_kb.py` = parser and normalizer
- `paper_kb.json` = structured source used by the chat assistant
- `extra_datasets.json` = manual extension layer
- `chat_paper.py` = retrieval + prompting + UI

## 20. Suggested Future Improvement

If you want to make the pipeline more reproducible end-to-end, the next best improvement would be adding an explicit PDF extraction script, for example:

- `extract_pdf_text.py`

Then the full pipeline would become:

1. PDF -> raw text
2. raw text -> cleaned structured JSON
3. JSON -> chat interface

Right now, step 1 is manual or external, and steps 2 and 3 are fully implemented in this repository.
