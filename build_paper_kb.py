import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW_TEXT_PATH = ROOT / "extracted_paper_raw.txt"
OUTPUT_PATH = ROOT / "paper_kb.json"
PAPER_TITLE = "Molecular quantum chemical data sets and databases for machine learning potentials"
# These replacements capture the recurring OCR / encoding artifacts seen in the
# extracted review text. The goal is not to become a general text-normalizer;
# it is to repair the specific mojibake patterns that repeatedly appeared in
# author names, titles, and reference strings for this paper.
TEXT_REPLACEMENTS = {
    "M�ller": "Müller",
    "Sch�tt": "Schütt",
    "Gonz�lez": "González",
    "Ram�rez": "Ramírez",
    "Mart�nez": "Martínez",
    "V�zquez": "Vázquez",
    "Cort�s": "Cortés",
    "Cortés-Guzm-n": "Cortés-Guzmán",
    "Guzm-n": "Guzmán",
    "C�lerse": "Célerse",
    "Jim�nez": "Jiménez",
    "H�ttig": "Hüttig",
    "Galv�n": "Galván",
    "J�nsson": "Jónsson",
    "Colom�s": "Colomés",
    "Sch�tz": "Schütz",
    "Rapp�": "Rappé",
    "Kovačević": "Kovačević",
    "Wesołowski": "Wesołowski",
    "Mickaël": "Mickaël",
    "Frédéric": "Frédéric",
    "João": "João",
    "Per Åke": "Per Åke",
    "Molpro: a general-purpose quantum chemistry program package": "Molpro: a general-purpose quantum chemistry program package",
    "OpenMolcas: from source code to insight": "OpenMolcas: From Source Code to Insight",
    "The OpenMolcas Web: from source code to insight": "OpenMolcas: From Source Code to Insight",
    "van der waals": "van der Waals",
    "mmff94": "MMFF94",
    "gdb-13": "GDB-13",
    "Figsharehttps://doi.org": "Figshare https://doi.org",
    "(Gaussian. Inc)": "(Gaussian Inc)",
    "GKhan D": "Khan D",
    "Vazquez-Mayagoitia": "Vázquez-Mayagoitia",
    "Juraskova": "Juraskova",
    "26 September 26 2024": "26 September 2024",
    "availabe": "available",
    " B97X/6-31G(d)": " ωB97X/6-31G(d)",
    " the B97X functional ": " the ωB97X functional ",
    " at the B97X level ": " at the ωB97X level ",
    "The 2DFT ": "The ∇2DFT ",
    " the 2DFT ": " the ∇2DFT ",
    " 2DFT ": " ∇2DFT ",
    "?2DFT": "∇2DFT",
}
OTHERS_MARKERS = [
    ("C7O2H10-17", "Among them, the C7O2H10-17 data set comprises"),
    ("ISO17", "The ISO17 data set extends"),
    ("VQM24", "The VQM24 data set is a comprehensive data set"),
    ("QCDGE", "The QCDGE database offers"),
    ("QM-22", "The QM-22 database is a compilation"),
    ("CheMFi", "The CheMFi data set is a multifidelity compilation"),
    ("QM9S", "The QM9S dataset, used for training and testing"),
    ("TensorMol ChemSpider", "The TensorMol ChemSpider data set contains"),
]
OTHERS_DATASET_REFERENCES = {
    "C7O2H10-17": "10",
    "ISO17": "17",
    "VQM24": "49",
    "QCDGE": "30",
    "QM-22": "40",
    "CheMFi": "11",
    "QM9S": "37",
    "TensorMol ChemSpider": "45",
}


def clean_text(text: str) -> str:
    # The raw text file still contains page breaks, running headers, author
    # lines, and standalone page numbers. Remove those first so section parsing
    # works on content rather than layout artifacts.
    text = text.replace("\x0c", "\n")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("Mach. Learn.: Sci. Technol."):
            continue
        if stripped == "A Ullah et al":
            continue
        if re.fullmatch(r"\d+", stripped):
            continue
        lines.append(line.rstrip())
    return normalize_text("\n".join(lines))


def normalize_text(text: str) -> str:
    # Apply targeted repairs for mojibake and formatting glitches before any
    # higher-level parsing. Some of these are simple string replacements, while
    # others are regex fixes for broken ranges such as page numbers and citation
    # spans.
    for old, new in TEXT_REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"([A-Za-z0-9])�([A-Za-z0-9])", r"\1-\2", text)
    text = re.sub(r"([A-Za-z])\?([A-Za-z])", r"\1-\2", text)
    text = re.sub(r"([A-Za-z])\s+\.\s+([0-9])", r"\1. \2", text)
    text = re.sub(r"\bSpice,\b", "SPICE,", text)
    text = re.sub(r"\bSchnet\b", "SchNet", text)
    text = text.replace("Müller K R", "Müller K-R")
    text = text.replace("Guzm-n", "Guzmán")
    text = re.sub(r"\bMol\. Phys\. 113 184-215\b", "Mol. Phys. 113 184-215", text)
    text = re.sub(r"\b1-86\b", "1-86", text)
    return text


def normalize_paragraph(text: str) -> str:
    # Collapse line-wrapped PDF text into paragraph-style text so dataset
    # summaries and references read like continuous prose.
    text = normalize_text(text.replace("\uFFFD", "?"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        block = re.sub(r"\s*\n\s*", " ", block.strip())
        block = re.sub(r"\s{2,}", " ", block)
        if block:
            paragraphs.append(block)
    return "\n\n".join(paragraphs)


def remove_embedded_table_one(text: str) -> str:
    # Section 3.1 contains a large table that bleeds into the extracted text
    # and hurts downstream sentence matching. Strip that specific span.
    return re.sub(
        r"Table 1\..*?(?=convergence criteria were employed to guarantee high-quality structures\.)",
        "",
        text,
        flags=re.S,
    )


def expand_reference_spans(text: str) -> list[int]:
    # Convert bracketed references such as [3], [3, 5], or [18-20] into a flat
    # sorted list of integer reference ids.
    refs = set()
    for raw in re.findall(r"\[([0-9,\-? ]+)\]", text):
        for part in raw.split(","):
            part = part.strip().replace("?", "-")
            if not part:
                continue
            if "-" in part:
                start_end = [p.strip() for p in part.split("-", 1)]
                if all(p.isdigit() for p in start_end):
                    start, end = map(int, start_end)
                    if start <= end:
                        refs.update(range(start, end + 1))
                continue
            if part.isdigit():
                refs.add(int(part))
    return sorted(refs)


def parse_references(text: str) -> dict[str, str]:
    # Build the master reference dictionary from the trailing "References"
    # section. Each entry is stitched back together across line breaks.
    if "References" not in text:
        return {}
    refs_text = text.split("References", 1)[1]
    refs = {}
    current_num = None
    current_lines = []
    for raw_line in refs_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\[(\d+)\]\s*(.*)", line)
        if match:
            if current_num is not None:
                refs[str(current_num)] = re.sub(r"\s{2,}", " ", " ".join(current_lines)).strip()
            current_num = int(match.group(1))
            current_lines = [match.group(2).strip()]
        elif current_num is not None:
            current_lines.append(line)
    if current_num is not None:
        refs[str(current_num)] = re.sub(r"\s{2,}", " ", " ".join(current_lines)).strip()
    return refs


def add_synthetic_reference(references: dict[str, str], entry: str) -> str:
    # Some access links in section 3.37 are given as plain URLs in the body
    # rather than numbered references. We synthesize stable reference ids so the
    # chat layer can cite those links in the same way it cites ordinary papers.
    for ref_num, ref_text in references.items():
        if ref_text == entry:
            return ref_num
    next_num = max((int(key) for key in references), default=0) + 1
    references[str(next_num)] = entry
    return str(next_num)


def build_dataset_entry(
    section_id: str,
    dataset_name: str,
    summary: str,
    methodology: str,
    accessibility: str,
    references: dict[str, str],
) -> dict:
    # Every dataset record is normalized into the same schema. This lets the
    # chat layer treat paper-native datasets and later manual additions in a
    # consistent way.
    full_text = summary
    if methodology:
        full_text = f"{full_text}\n\nComputational methodology: {methodology}"
    if accessibility:
        full_text = f"{full_text}\n\nData accessibility: {accessibility}"
    cited_refs = [str(num) for num in expand_reference_spans(full_text)]
    return {
        "section": section_id,
        "dataset_name": dataset_name,
        "summary": summary,
        "computational_methodology": methodology,
        "data_accessibility": accessibility,
        "full_text": full_text,
        "cited_references": cited_refs,
        "reference_entries": {ref: references[ref] for ref in cited_refs if ref in references},
    }


def split_others_section(section_id: str, body: str, references: dict[str, str]) -> list[dict]:
    # The paper's "3.37 Others" subsection packs several datasets into a single
    # section. Split it into standalone records so follow-up questions about
    # QCDGE, QM9S, CheMFi, etc. can resolve cleanly.
    accessibility_match = re.search(r"Data accessibility:\s*(.*)$", body, flags=re.S)
    main_text = body[: accessibility_match.start()].strip() if accessibility_match else body

    spans = []
    for dataset_name, marker in OTHERS_MARKERS:
        start = main_text.find(marker)
        if start == -1:
            continue
        spans.append((dataset_name, marker, start))
    spans.sort(key=lambda item: item[2])

    access_map = {
        "C7O2H10-17": (
            "Available at http://quantum-machine.org/datasets/.",
            "C7O2H10-17 and ISO17 data access page: http://quantum-machine.org/datasets/",
        ),
        "ISO17": (
            "Available at http://quantum-machine.org/datasets/.",
            "C7O2H10-17 and ISO17 data access page: http://quantum-machine.org/datasets/",
        ),
        "VQM24": (
            "Accessible on Zenodo at https://doi.org/10.5281/zenodo.11164951.",
            "VQM24 data access: Zenodo https://doi.org/10.5281/zenodo.11164951",
        ),
        "QCDGE": (
            "Hosted at http://langroup.site/QCDGE/.",
            "QCDGE data access: http://langroup.site/QCDGE/",
        ),
        "QM-22": (
            "Can be downloaded from https://github.com/jmbowma/QM-22.",
            "QM-22 data access: GitHub https://github.com/jmbowma/QM-22",
        ),
        "CheMFi": (
            "Available at https://github.com/SM4DA/CheMFi.",
            "CheMFi data access: GitHub https://github.com/SM4DA/CheMFi",
        ),
        "QM9S": (
            "Hosted on Figshare at https://doi.org/10.6084/m9.figshare.24235333.",
            "QM9S data access: Figshare https://doi.org/10.6084/m9.figshare.24235333",
        ),
        "TensorMol ChemSpider": (
            "Previously accessible via "
            "https://drive.google.com/drive/folders/1IfWPs7i5kfmErIRyuhGv95dSVtNFo0e_, "
            "but noted in the paper as no longer available.",
            "TensorMol ChemSpider former access location: "
            "https://drive.google.com/drive/folders/1IfWPs7i5kfmErIRyuhGv95dSVtNFo0e_ "
            "(noted in the paper as no longer available)",
        ),
    }

    entries = []
    for index, (dataset_name, marker, start) in enumerate(spans):
        end = spans[index + 1][2] if index + 1 < len(spans) else len(main_text)
        segment = main_text[start:end].strip()
        if dataset_name == "C7O2H10-17":
            segment = segment.replace("Among them, ", "", 1)
        # The introductory sentence in "Others" carries the dataset-defining
        # paper reference, so inject that citation back into each split record.
        dataset_ref = OTHERS_DATASET_REFERENCES.get(dataset_name)
        if dataset_ref:
            segment = f"{dataset_name} [{dataset_ref}]. {segment}"
        access_text, access_reference_entry = access_map.get(dataset_name, ("", ""))
        access_ref = add_synthetic_reference(references, access_reference_entry) if access_reference_entry else ""
        accessibility = f"{access_text} [{access_ref}]" if access_text and access_ref else access_text
        entries.append(
            build_dataset_entry(
                section_id,
                dataset_name,
                segment,
                "",
                accessibility,
                references,
            )
        )
    return entries


def parse_sections(text: str, references: dict[str, str]) -> list[dict]:
    # Sections 3.x correspond to dataset entries in the review. The regex stops
    # before the next section, section 4, ORCID block, or references.
    section_re = re.compile(
        r"(?ms)^3\.(\d+)\.\s+(.+?)\n(.*?)(?=^3\.\d+\.\s+.+?$|^4\.\s+.+?$|^ORCID iDs$|^References$|\Z)"
    )
    datasets = []
    for match in section_re.finditer(text):
        section_id = f"3.{match.group(1)}"
        name = match.group(2).strip()
        raw_body = match.group(3).strip()
        if section_id == "3.1":
            raw_body = remove_embedded_table_one(raw_body)
        body = normalize_paragraph(raw_body)

        if section_id == "3.37" and name == "Others":
            datasets.extend(split_others_section(section_id, body, references))
            continue

        methodology = ""
        accessibility = ""
        summary = body

        # When the extracted text explicitly contains "Computational
        # methodology:" and "Data accessibility:", split the body into the
        # fields that the chat app later surfaces directly.
        methodology_match = re.search(
            r"Computational methodology:\s*(.*?)(?=\n\nData accessibility:|\Z)",
            body,
            flags=re.S,
        )
        accessibility_match = re.search(r"Data accessibility:\s*(.*)$", body, flags=re.S)

        if methodology_match:
            methodology = methodology_match.group(1).strip()
            summary = body[: methodology_match.start()].strip()
        if accessibility_match:
            accessibility = accessibility_match.group(1).strip()
            if not methodology_match:
                summary = body[: accessibility_match.start()].strip()

        cited_refs = [str(num) for num in expand_reference_spans(body)]
        datasets.append(
            {
                "section": section_id,
                "dataset_name": name,
                "summary": summary,
                "computational_methodology": methodology,
                "data_accessibility": accessibility,
                "full_text": body,
                "cited_references": cited_refs,
                "reference_entries": {ref: references[ref] for ref in cited_refs if ref in references},
            }
        )
    return datasets


def main() -> None:
    # This builder assumes the PDF has already been converted to
    # extracted_paper_raw.txt by an external PDF-to-text step. From there it
    # cleans the text, parses the global references, extracts dataset sections,
    # and writes a structured JSON knowledge base.
    raw_text = RAW_TEXT_PATH.read_text(encoding="utf-8", errors="replace")
    cleaned = clean_text(raw_text)
    references = parse_references(cleaned)
    datasets = parse_sections(cleaned, references)
    payload = {
        "paper_title": PAPER_TITLE,
        "source_pdf": "Ullah et al_2024_Molecular quantum chemical data sets and databases for machine learning.pdf",
        "source_text": RAW_TEXT_PATH.name,
        "dataset_count": len(datasets),
        "datasets": datasets,
        "references": references,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.name} with {len(datasets)} dataset sections and {len(references)} references.")


if __name__ == "__main__":
    main()
