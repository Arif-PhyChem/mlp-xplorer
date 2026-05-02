from pathlib import Path

import build_paper_kb
import chat_paper


ROOT = Path(__file__).resolve().parent
# Only the raw extracted paper text and the manual extension file can make the
# generated knowledge base stale.
SOURCE_FILES = [
    ROOT / "extracted_paper_raw.txt",
    ROOT / "extra_datasets.json",
]
KB_PATH = ROOT / "paper_kb.json"


def kb_needs_rebuild() -> bool:
    # Rebuild whenever the generated KB is missing or older than one of the
    # source inputs.
    if not KB_PATH.exists():
        return True
    kb_mtime = KB_PATH.stat().st_mtime
    for path in SOURCE_FILES:
        if path.exists() and path.stat().st_mtime > kb_mtime:
            return True
    return False


def main() -> None:
    # This is the convenience entry point: rebuild when needed, then launch the
    # local HTTP chat server.
    if kb_needs_rebuild():
        print("Building paper knowledge base...")
        build_paper_kb.main()
    else:
        print("Knowledge base is up to date.")
    print(f"Starting chat server at {chat_paper.display_base_url()}")
    chat_paper.main()


if __name__ == "__main__":
    main()
