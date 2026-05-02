---
title: MLP-Xplorer
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# MLP-Xplorer

MLP-Xplorer is a lightweight local web app that turns a review paper into a searchable chat assistant for molecular quantum chemistry datasets and databases.

This repository is safe to share on GitHub as long as you do not commit your API key. The app is already designed to read the key from an environment variable first.

## What is in this repo

- `chat_paper.py`: chat server and retrieval logic.
- `run_paper_chat.py`: convenience launcher that rebuilds the knowledge base when needed, then starts the app.
- `build_paper_kb.py`: converts the extracted review text into `paper_kb.json`.
- `paper_kb.json`: generated knowledge base from the source review text.
- `extracted_paper_raw.txt`: extracted text used to build the current knowledge base.
- `extra_datasets.json`: manual extension file for adding new dataset records without rebuilding the whole paper parser.
- `extra_datasets.template.json`: template showing the expected schema for manual additions.
- `.env.example`: example environment-variable setup.
- `frontend/`: HTML, CSS, and JavaScript for the chat UI.
- `METHODOLOGY.md`: details about the review-to-knowledge-base pipeline.

## Keep your API key private

Recommended local setup:

```powershell
$env:DEEPSEEK_API_KEY="your_api_key_here"
```

Alternative local-only fallback:

- Put the key by itself into `deepseek_api.txt`.

Important:

- Do not commit `deepseek_api.txt`.
- Do not paste a real API key into `.env.example`, `README.md`, or any tracked file.
- The app checks `DEEPSEEK_API_KEY` first and only falls back to `deepseek_api.txt`.

## How to run locally

### Option 1: one command

```powershell
py -3 run_paper_chat.py
```

This will:

- rebuild `paper_kb.json` if `extracted_paper_raw.txt` or `extra_datasets.json` changed
- start the local server, usually at `http://127.0.0.1:8000`

### Option 2: run the steps separately

```powershell
py -3 build_paper_kb.py
py -3 chat_paper.py
```

## Python requirements

No third-party Python packages are required for the current app.

Tested target:

- Python 3.11+

## Environment variables

- `DEEPSEEK_API_KEY`: your private API key
- `DEEPSEEK_MODEL`: defaults to `deepseek-chat`
- `DEEPSEEK_BASE_URL`: optional compatible endpoint override
- `DEEPSEEK_TIMEOUT_SECONDS`: request timeout, default `180`
- `DEEPSEEK_RETRIES`: retry count, default `2`
- `PAPER_CHAT_PORT`: optional local port override
- `PORT`: hosting-friendly port variable, also supported

## How to add new data

You have two supported paths depending on what kind of new material you want to add.

### Path A: add a few new dataset/review entries manually

Use this when you want to append a few new items without reprocessing the full source review.

1. Open `extra_datasets.template.json`.
2. Copy the example object structure into `extra_datasets.json`.
3. Add one object per new dataset or review-derived entry under `"datasets"`.
4. Save the file.
5. Run:

```powershell
py -3 run_paper_chat.py
```

Manual-entry schema:

- `section`: your label, for example `extra.1`
- `dataset_name`: display name used in chat matching
- `summary`: short main description
- `computational_methodology`: method details if available
- `data_accessibility`: link or access details
- `full_text`: full searchable text for retrieval
- `cited_references`: list of reference IDs you define
- `reference_entries`: dictionary of those reference IDs to citation text or URLs

Tip:

- `full_text` should contain the most complete wording because the retrieval layer searches it directly.

### Path B: replace or extend the review source and rebuild the paper knowledge base

Use this when you want the repo to reflect a new or updated review paper as the main source.

1. Replace or edit `extracted_paper_raw.txt` with the extracted text from the new review.
2. If needed, update parsing logic in `build_paper_kb.py` so section splitting matches the new review structure.
3. Run:

```powershell
py -3 build_paper_kb.py
py -3 chat_paper.py
```

Notes:

- `build_paper_kb.py` is tuned to the current review paper structure, especially section numbering and reference parsing.
- If your new review uses a different layout, headings, or citation style, you may need to adjust the parser.

## GitHub sharing checklist

Before pushing:

- make sure `deepseek_api.txt` is not included
- make sure no real API key appears in any tracked file
- keep `.env.example` as example-only values
- keep `extra_datasets.json` only if you are comfortable sharing its contents
- avoid committing generated zip packages unless you want release artifacts in the repo

## Source attribution and license

This project includes a structured knowledge base derived from:

Ullah A, Chen Y, Dral P O. *Molecular quantum chemical data sets and databases for machine learning potentials*. *Machine Learning: Science and Technology* 5(4), 041001 (2024). https://doi.org/10.1088/2632-2153/ad8f13

Original article license:

- CC BY 4.0
- https://creativecommons.org/licenses/by/4.0/

This repository transforms the article into a searchable structured database and chat application. Changes were made from the original publication format during text extraction, parsing, normalization, and database construction.

## Docker and Hugging Face

This repo includes a `Dockerfile` and can also be used in a Hugging Face Docker Space.

For Hugging Face Spaces:

1. Create a new Space with `Docker` SDK.
2. Upload or push this project.
3. Add a secret named `DEEPSEEK_API_KEY` in the Space settings.
4. Launch the Space.

For hosted environments, the app reads `PORT` automatically.
