import json
import os
import random
import re
from html import escape as html_escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import sleep, time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parent
KB_PATH = ROOT / "paper_kb.json"
EXTRA_DATASETS_PATH = ROOT / "extra_datasets.json"
API_KEY_FILE = ROOT / "deepseek_api.txt"
FRONTEND_DIR = ROOT / "frontend"
INDEX_TEMPLATE_PATH = FRONTEND_DIR / "modern_index.html"
STYLE_PATH = FRONTEND_DIR / "modern_style.css"
APP_JS_PATH = FRONTEND_DIR / "modern_app.js"
DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEFAULT_DEEPSEEK_TIMEOUT = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "180"))
DEFAULT_DEEPSEEK_RETRIES = int(os.getenv("DEEPSEEK_RETRIES", "2"))
HOST = os.getenv("PAPER_CHAT_HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", os.getenv("PAPER_CHAT_PORT", "8000")))
def display_base_url() -> str:
    host_for_browser = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    return f"http://{host_for_browser}:{PORT}"


STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "data", "dataset", "datasets",
    "for", "from", "give", "has", "how", "i", "in", "is", "it", "me", "of", "on", "or",
    "paper", "please", "set", "sets", "that", "the", "this", "to", "us", "what", "which",
    "with", "you",
}
FOLLOW_UP_HINTS = {
    "availability", "available", "citation", "cite", "download", "link", "method", "methodology",
    "properties", "property", "reference", "references", "size", "source", "theory", "url", "where",
    "accuracy", "accurate", "better", "best", "difference", "different", "which", "worse",
}
GROUP_FOLLOW_UP_HINTS = {
    "accuracy", "accurate", "better", "best", "compare", "comparison", "difference", "different",
    "which", "worse", "stronger", "weaker",
}
GLOBAL_SCOPE_HINTS = {
    "all datasets",
    "all the datasets",
    "whole database",
    "entire database",
    "across all datasets",
    "in the database",
    "in this database",
    "among all datasets",
    "among all the datasets",
}
CORPUS_INVENTORY_PATTERNS = [
    r"\bhow many datasets?\b",
    r"\bhow many databases?\b",
    r"\bhow many dataset/database entries\b",
    r"\bhow many entries\b",
    r"\bhow many can you provide information about\b",
    r"\bhow many datasets and databases\b",
]
SMALL_TALK_PATTERNS = [
    r"^\s*hi\s*$",
    r"^\s*hello\s*$",
    r"^\s*hey\s*$",
    r"^\s*good morning\s*$",
    r"^\s*good afternoon\s*$",
    r"^\s*good evening\s*$",
    r"^\s*thanks?\s*$",
    r"^\s*thank you\s*$",
    r"^\s*how can you help(?: me)?\s*\??\s*$",
    r"^\s*how you can help(?: me)?\s*\??\s*$",
    r"^\s*what can you do\s*\??\s*$",
    r"^\s*help\s*\??\s*$",
]
TOPIC_KEYWORDS = {
    "accuracy": {"accuracy", "accurate", "better", "best", "worse", "stronger", "weaker"},
    "availability": {"availability", "available", "download", "link", "url", "hosted", "access"},
    "methods": {"method", "methodology", "theory", "functional", "basis", "computed"},
    "size": {"size", "million", "conformations", "molecules", "coverage", "contains"},
    "references": {"reference", "references", "citation", "cite"},
    "ground_state": {
        "ground", "ground-state", "groundstate", "total", "atomization", "potential",
        "electronic", "energies", "energy", "enthalpies", "thermochemical", "energetics",
    },
    "excited_states": {
        "excited", "excitation", "excitations", "spectra", "spectrum", "transition",
        "transitions", "oscillator", "singlet", "triplet", "electronic", "td-dft",
        "tddft", "s0", "s1", "s2",
    },
}
SESSION_STATES: dict[str, dict] = {}

TOPIC_SYNONYMS = {
    "ground_state": {
        "ground", "state", "states", "ground-state", "groundstate", "total", "total-energy",
        "total-energies", "atomization", "atomization-energy", "atomization-energies",
        "potential", "potential-energy", "potential-energies", "electronic", "electronic-energy",
        "electronic-energies", "enthalpy", "enthalpies", "thermochemical", "energetic", "energetics",
        "zpe", "zero-point",
    },
    "excited_states": {
        "excited", "state", "states", "excited-state", "excited-state(s)", "excitation",
        "excitations", "transition", "transitions", "transition-energy", "transition-energies",
        "energy", "energies", "spectra", "spectrum", "electronic", "oscillator", "singlet",
        "triplet", "td-dft", "tddft", "photo", "photodynamic",
    },
}


def read_api_key() -> str:
    # Prefer the environment variable for normal use, but keep the local text
    # file fallback so the project is easy to run without additional setup.
    env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key
    if API_KEY_FILE.exists():
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def load_kb() -> dict:
    # The paper-derived KB is the authoritative base. extra_datasets.json is a
    # lightweight extension layer for datasets added after the paper.
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    extra = []
    if EXTRA_DATASETS_PATH.exists():
        try:
            extra_payload = json.loads(EXTRA_DATASETS_PATH.read_text(encoding="utf-8"))
            extra = extra_payload.get("datasets", [])
        except json.JSONDecodeError:
            extra = []
    kb["datasets"] = kb.get("datasets", []) + extra
    return kb


def tokenize(text: str) -> set[str]:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z0-9\-/+]+", text)}
    return {token for token in tokens if len(token) > 1 and token not in STOPWORDS}


def default_session_state(previous_starter_prompts: list[tuple[str, str]] | None = None) -> dict:
    # Keep the conversation state small and explicit. This lets follow-up turns
    # reuse the last retrieval scope instead of drifting into a fresh search.
    return {
        "active_datasets": [],
        "active_aliases": [],
        "last_context_dataset_names": [],
        "last_context_references": {},
        "last_query_type": "",
        "last_topic": "",
        "last_user_query": "",
        "last_rewritten_query": "",
        "ui_messages": [],
        "ui_prompt_history": [],
        "ui_starter_prompts": pick_starter_prompts(exclude=previous_starter_prompts),
        "ui_status": "Ready.",
        "updated_at": time(),
    }


def get_session_state(session_id: str) -> dict:
    state = SESSION_STATES.get(session_id)
    if state is None:
        state = default_session_state()
        SESSION_STATES[session_id] = state
    return state


def dataset_aliases(name: str) -> set[str]:
    aliases = set()
    clean = (name or "").strip()
    if not clean:
        return aliases
    aliases.add(clean.lower())
    aliases.update(piece.strip() for piece in re.split(r"\band\b|,|/", clean.lower()) if piece.strip())
    stripped_symbol = re.sub(r"^[^A-Za-z0-9]+", "", clean).strip().lower()
    if stripped_symbol and stripped_symbol != clean.lower():
        aliases.add(stripped_symbol)
    if clean.startswith("∇"):
        stripped = clean[1:].strip().lower()
        if stripped:
            aliases.add(stripped)
        aliases.add(re.sub(r"^∇\d*", "nabla", clean, flags=re.IGNORECASE).strip().lower())
        aliases.add(clean.replace("∇", "nabla", 1).strip().lower())
    if "∇" in clean:
        aliases.add(clean.replace("∇", "nabla").lower())
    if clean.startswith("?"):
        aliases.add(clean[1:].strip().lower())
        aliases.add(clean.replace("?", "nabla", 1).strip().lower())
    if stripped_symbol.endswith("2dft"):
        aliases.add(stripped_symbol.replace("2dft", "nablasquaredft"))
        aliases.add(stripped_symbol.replace("2dft", "nabla square dft"))
    return {alias for alias in aliases if alias}


def get_dataset_by_name(kb: dict, name: str) -> dict | None:
    target_aliases = dataset_aliases(name)
    for dataset in kb.get("datasets", []):
        if target_aliases & dataset_aliases(dataset.get("dataset_name", "")):
            return dataset
    return None


def datasets_from_names(kb: dict, names: list[str]) -> list[dict]:
    datasets = []
    for name in names:
        dataset = get_dataset_by_name(kb, name)
        if dataset:
            datasets.append(dataset)
    return datasets


def find_explicit_dataset_matches(kb: dict, query: str) -> list[dict]:
    # Match dataset names and simple aliases directly in the user query before
    # falling back to token-overlap retrieval.
    query_lower = query.lower()
    matches = []
    for dataset in kb.get("datasets", []):
        aliases = dataset_aliases(dataset.get("dataset_name", ""))
        if any(alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query_lower) for alias in aliases):
            matches.append(dataset)
    matches.sort(key=lambda item: len(item.get("dataset_name", "")), reverse=True)
    return matches


def find_explicit_dataset_match_pairs(kb: dict, query: str) -> list[tuple[dict, str]]:
    query_lower = query.lower()
    matches = []
    seen = set()
    for dataset in kb.get("datasets", []):
        aliases = dataset_aliases(dataset.get("dataset_name", ""))
        matched_alias = None
        for alias in sorted(aliases, key=len, reverse=True):
            if alias and re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", query_lower):
                matched_alias = alias
                break
        key = dataset.get("dataset_name", "")
        if matched_alias and key not in seen:
            seen.add(key)
            matches.append((dataset, matched_alias))
    matches.sort(key=lambda item: len(item[1]), reverse=True)
    return matches


def is_comparison_query(query: str) -> bool:
    lowered = query.lower()
    return any(word in lowered for word in ["compare", "comparison", "versus", " vs ", " vs. "])


def is_follow_up_query(query: str) -> bool:
    tokens = tokenize(query)
    if len(tokens) <= 5:
        return True
    return bool(tokens & (FOLLOW_UP_HINTS | GROUP_FOLLOW_UP_HINTS))


def is_group_follow_up_query(query: str) -> bool:
    tokens = tokenize(query)
    return bool(tokens & GROUP_FOLLOW_UP_HINTS)


def requests_global_scope(query: str) -> bool:
    lowered = query.lower()
    return any(phrase in lowered for phrase in GLOBAL_SCOPE_HINTS)


def is_corpus_inventory_query(query: str) -> bool:
    lowered = query.lower()
    return any(re.search(pattern, lowered) for pattern in CORPUS_INVENTORY_PATTERNS)


def is_inventory_follow_up_query(query: str, state: dict) -> bool:
    if state.get("last_query_type") != "inventory":
        return False
    lowered = query.lower().strip()
    follow_up_phrases = [
        "list them all",
        "list all of them",
        "list all",
        "show them all",
        "show all of them",
        "give me all of them",
        "please list them all",
        "short description of each",
        "short descript of each",
        "describe each",
        "describe them",
        "brief description of each",
        "go ahead and list",
        "go ahead and give me a short description",
    ]
    return any(phrase in lowered for phrase in follow_up_phrases)


def is_small_talk_query(query: str) -> bool:
    lowered = query.lower().strip()
    return any(re.search(pattern, lowered) for pattern in SMALL_TALK_PATTERNS)


def classify_user_turn(query: str, state: dict, explicit_pairs: list[tuple[dict, str]] | None = None) -> dict:
    # Decide whether the user is asking about a named dataset, making a
    # comparison, asking a vague follow-up, or issuing a fresh global query
    # across the database.
    explicit_pairs = explicit_pairs or []
    tokens = tokenize(query)
    last_scope_type = state.get("last_query_type", "")
    has_active_scope = bool(state.get("active_datasets") or state.get("last_context_dataset_names"))
    is_short = len(tokens) <= 7
    has_follow_up_markers = bool(tokens & (FOLLOW_UP_HINTS | GROUP_FOLLOW_UP_HINTS))
    unique_explicit = {dataset.get("dataset_name", "") for dataset, _ in explicit_pairs}
    has_explicit_dataset = bool(unique_explicit)
    is_comparison = is_comparison_query(query) or len(unique_explicit) > 1
    broad_plural_query = bool(re.search(r"\b(which|what)\s+datasets?\b", query.lower()))
    has_global_scope_marker = requests_global_scope(query)
    is_inventory_query = is_corpus_inventory_query(query)
    is_small_talk = is_small_talk_query(query)

    if is_small_talk:
        return {"kind": "small_talk", "scope": "general"}

    if has_explicit_dataset:
        if is_comparison:
            return {"kind": "explicit_comparison", "scope": "comparison"}
        return {"kind": "explicit_dataset", "scope": "single"}

    if is_inventory_query:
        return {"kind": "corpus_inventory", "scope": "general"}

    if broad_plural_query or has_global_scope_marker:
        return {"kind": "fresh_general", "scope": "general"}

    if has_active_scope and (is_short or has_follow_up_markers):
        if last_scope_type == "comparison" or is_group_follow_up_query(query):
            return {"kind": "follow_up", "scope": "comparison"}
        return {"kind": "follow_up", "scope": "single"}

    return {"kind": "fresh_general", "scope": "general"}


def infer_query_topic(query: str, fallback: str = "") -> str:
    tokens = tokenize(query)
    for topic, keywords in TOPIC_KEYWORDS.items():
        if tokens & keywords:
            return topic
    return fallback


def combine_reference_entries(datasets: list[dict]) -> dict[str, str]:
    refs = {}
    for dataset in datasets:
        for ref_num, ref_text in dataset.get("reference_entries", {}).items():
            refs[ref_num] = ref_text
    return refs


def resolve_datasets_from_history(kb: dict, history: list[dict], query: str) -> list[dict]:
    if not history or not is_follow_up_query(query):
        return []

    for item in reversed(history):
        names = item.get("source_datasets") or []
        resolved = [get_dataset_by_name(kb, name) for name in names]
        resolved = [dataset for dataset in resolved if dataset]
        if resolved:
            if len(resolved) > 1:
                return resolved[:6]
            return resolved[:1]
    return []


def resolve_datasets_from_state(kb: dict, state: dict, query: str) -> list[dict]:
    names = state.get("active_datasets") or []
    if not names or not is_follow_up_query(query):
        return []
    resolved = datasets_from_names(kb, names)
    if not resolved:
        return []
    if len(resolved) > 1:
        return resolved[:6]
    return resolved[:1]


def resolve_context_from_state(kb: dict, state: dict, query: str) -> tuple[list[dict], dict[str, str]] | None:
    # Follow-up questions should prefer the exact last retrieved context instead
    # of performing a brand-new search immediately.
    if not is_follow_up_query(query):
        return None
    names = state.get("last_context_dataset_names") or state.get("active_datasets") or []
    if not names:
        return None
    datasets = datasets_from_names(kb, names)
    if not datasets:
        return None
    refs = dict(state.get("last_context_references") or {}) or combine_reference_entries(datasets)
    return datasets, refs


def get_last_user_message(history: list[dict]) -> str:
    for item in reversed(history):
        if item.get("role") == "user":
            content = item.get("content", "").strip()
            if content:
                return content
    return ""


def disambiguate_query(query: str, history: list[dict]) -> str:
    if not history or not is_follow_up_query(query):
        return query
    last_user_message = get_last_user_message(history)
    if not last_user_message:
        return query
    return f"{query}\n\nAbout this previously discussed item: {last_user_message}"


def heuristic_follow_up_rewrite(query: str, state: dict) -> str:
    # If the follow-up is vague ("which one is better?", "what about
    # availability?"), rewrite it into a self-contained prompt anchored to the
    # current dataset scope.
    aliases = state.get("active_aliases") or state.get("active_datasets") or []
    if not aliases:
        return query
    scope = ", ".join(aliases)
    topic = infer_query_topic(query)
    if not topic and state.get("last_query_type") == "follow_up":
        topic = state.get("last_topic", "")
    if len(aliases) > 1:
        extra = f"Treat this as a follow-up comparing only these datasets: {scope}."
    else:
        extra = f"Treat this as a follow-up about this dataset only: {scope}."
    if topic:
        extra += f" Focus specifically on {topic}."
    return f"{query}\n\n{extra}"


def score_dataset(query: str, query_tokens: set[str], dataset: dict) -> int:
    # Simple lexical scoring is enough here because the corpus is small and
    # structured: dataset name matches matter the most, followed by summary /
    # methodology / accessibility overlap.
    haystack = " ".join(
        [
            dataset.get("dataset_name", ""),
            dataset.get("summary", ""),
            dataset.get("computational_methodology", ""),
            dataset.get("data_accessibility", ""),
        ]
    )
    haystack_lower = haystack.lower()
    dataset_tokens = tokenize(haystack)
    overlap = len(query_tokens & dataset_tokens)
    score = overlap * 3
    aliases = dataset_aliases(dataset.get("dataset_name", ""))
    if any(alias and alias in query.lower() for alias in aliases):
        score += 12
    for piece in aliases:
        piece = piece.strip()
        if piece and len(piece) > 2 and piece in query.lower():
            score += 4
    if "reference" in query.lower() or "cite" in query.lower():
        score += min(len(dataset.get("cited_references", [])), 5)
    if any(token in haystack_lower for token in query_tokens):
        score += 1

    topic = infer_query_topic(query)
    if topic in TOPIC_SYNONYMS:
        topic_hits = sum(1 for token in TOPIC_SYNONYMS[topic] if token in haystack_lower)
        if topic_hits:
            score += topic_hits * 2

    if topic == "ground_state":
        if "ground state energ" in haystack_lower or "ground-state energ" in haystack_lower:
            score += 6
        if "atomization energ" in haystack_lower or "total energ" in haystack_lower:
            score += 5
        if "potential energ" in haystack_lower or "electronic energ" in haystack_lower:
            score += 4
        if "ground-state propert" in haystack_lower or "thermochemical energetics" in haystack_lower:
            score += 4

    if topic == "excited_states":
        if "excited state" in haystack_lower or "excited-state" in haystack_lower:
            score += 6
        if "transition energ" in haystack_lower or "excitation energ" in haystack_lower:
            score += 5
        if "first ten singlet and triplet transitions" in haystack_lower:
            score += 6

    return score


def deepseek_request(messages: list[dict], temperature: float = 0.1, timeout: int = 120) -> str:
    # All network calls flow through one place so API-key handling, proxy
    # bypassing, and error formatting stay consistent.
    api_key = read_api_key()
    if not api_key:
        return (
            "DeepSeek API key not found. Put it in the `DEEPSEEK_API_KEY` environment variable or in "
            "`deepseek_api.txt` in this folder, then retry."
        )

    payload = json.dumps({"model": DEFAULT_MODEL, "messages": messages, "temperature": temperature}).encode("utf-8")
    req = Request(
        url=f"{DEFAULT_BASE_URL.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    proxy_values = [
        os.getenv("HTTPS_PROXY", ""),
        os.getenv("HTTP_PROXY", ""),
        os.getenv("ALL_PROXY", ""),
    ]
    # Some Windows environments leak a dead local proxy into HTTP(S)_PROXY.
    # Bypass it for DeepSeek calls if we detect that exact broken target.
    use_direct = any("127.0.0.1:9" in value for value in proxy_values if value)
    opener = urlopen if not use_direct else build_opener(ProxyHandler({})).open
    attempts = max(1, DEFAULT_DEEPSEEK_RETRIES + 1)
    last_error = ""
    for attempt in range(attempts):
        try:
            with opener(req, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"DeepSeek API error {exc.code}: {body}"
            if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= attempts - 1:
                return last_error
        except URLError as exc:
            last_error = f"Network error while calling DeepSeek: {exc}"
            if attempt >= attempts - 1:
                return last_error
        except Exception as exc:
            last_error = f"Unexpected error while calling DeepSeek: {exc}"
            if attempt >= attempts - 1:
                return last_error

        sleep(min(1.5 * (attempt + 1), 4.0))

    return last_error or "Unexpected error while calling DeepSeek: request failed without a response."


def llm_rewrite_follow_up_query(query: str, state: dict) -> str:
    aliases = state.get("active_aliases") or state.get("active_datasets") or []
    if not aliases:
        return query
    fallback = heuristic_follow_up_rewrite(query, state)
    messages = [
        {
            "role": "system",
            "content": (
                "Rewrite ambiguous follow-up questions so they are self-contained. "
                "Preserve meaning, keep the exact dataset names provided in scope, and do not answer the question. "
                "Return only the rewritten question."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original follow-up question: {query}\n"
                f"Current dataset scope: {', '.join(aliases)}\n"
                f"Previous user question: {state.get('last_user_query', '')}\n"
                f"Current topic if known: {state.get('last_topic', '') or 'unknown'}"
            ),
        },
    ]
    rewritten = deepseek_request(messages, temperature=0.0, timeout=30)
    if is_error_response(rewritten) or not rewritten or len(rewritten) > 800:
        return fallback
    normalized = rewritten.strip()
    query_topic = infer_query_topic(query)
    rewritten_topic = infer_query_topic(normalized)
    lowered = normalized.lower()
    if not all(alias.lower() in lowered for alias in aliases):
        return fallback
    if query_topic and rewritten_topic and query_topic != rewritten_topic:
        return fallback
    if not query_topic and rewritten_topic:
        return fallback
    return normalized


def rewrite_query_with_state(query: str, state: dict) -> str:
    aliases = state.get("active_aliases") or state.get("active_datasets") or []
    if not aliases or not is_follow_up_query(query):
        return query
    heuristic = heuristic_follow_up_rewrite(query, state)
    if os.getenv("MLP_XPLORER_USE_LLM_REWRITE", "").strip() != "1":
        return heuristic
    rewritten = llm_rewrite_follow_up_query(query, state)
    return rewritten if rewritten else heuristic


def select_context(
    kb: dict,
    query: str,
    state: dict | None = None,
    history: list[dict] | None = None,
) -> tuple[list[dict], dict[str, str], dict]:
    # Retrieval strategy, in order:
    # 1. Reuse the exact prior context for follow-ups.
    # 2. Honor explicit dataset names / comparison requests.
    # 3. Fall back to lightweight lexical retrieval across the whole KB.
    state = state or default_session_state()
    history = history or []
    initial_topic = infer_query_topic(query)
    metadata = {
        "query_type": "general",
        "active_aliases": [],
        "active_scope_labels": [],
        "effective_query": query,
        "topic": initial_topic,
        "turn_kind": "fresh_general",
    }

    explicit_pairs = find_explicit_dataset_match_pairs(kb, query)
    turn = classify_user_turn(query, state, explicit_pairs)
    metadata["turn_kind"] = turn["kind"]

    if turn["kind"] == "follow_up":
        state_context = resolve_context_from_state(kb, state, query)
        if state_context:
            datasets, refs = state_context
            metadata["query_type"] = "follow_up"
            metadata["active_aliases"] = state.get("active_aliases", [])
            metadata["active_scope_labels"] = [
                {"label": alias, "dataset_name": dataset.get("dataset_name", "")}
                for alias, dataset in zip(state.get("active_aliases", []), datasets)
            ]
            metadata["effective_query"] = rewrite_query_with_state(query, state)
            if not metadata["topic"]:
                metadata["topic"] = state.get("last_topic", "")
            return datasets, refs, metadata

    if turn["kind"] in {"explicit_dataset", "explicit_comparison"} and explicit_pairs:
        selected_pairs = explicit_pairs[:6] if is_comparison_query(query) or len(explicit_pairs) > 1 else explicit_pairs[:1]
        selected = [dataset for dataset, _ in selected_pairs]
        metadata["query_type"] = "comparison" if len(selected) > 1 else "single_dataset"
        metadata["active_aliases"] = [alias for _, alias in selected_pairs]
        metadata["active_scope_labels"] = [
            {"label": alias, "dataset_name": dataset.get("dataset_name", "")}
            for dataset, alias in selected_pairs
        ]
        return selected, combine_reference_entries(selected), metadata

    if turn["kind"] == "follow_up":
        history_datasets = resolve_datasets_from_history(kb, history, query)
        if history_datasets:
            metadata["query_type"] = "follow_up"
            metadata["active_aliases"] = [dataset.get("dataset_name", "") for dataset in history_datasets]
            metadata["active_scope_labels"] = [
                {"label": dataset.get("dataset_name", ""), "dataset_name": dataset.get("dataset_name", "")}
                for dataset in history_datasets
            ]
            metadata["effective_query"] = disambiguate_query(query, history)
            if not metadata["topic"]:
                metadata["topic"] = state.get("last_topic", "")
            return history_datasets, combine_reference_entries(history_datasets), metadata

    query_tokens = tokenize(metadata["effective_query"])
    scored = []
    for dataset in kb.get("datasets", []):
        score = score_dataset(metadata["effective_query"], query_tokens, dataset)
        if score > 0:
            scored.append((score, dataset))
    if not scored:
        scored = [(0, dataset) for dataset in kb.get("datasets", [])[:5]]
    sorted_scored = sorted(scored, key=lambda item: item[0], reverse=True)
    broad_listing_query = bool(re.search(r"\bwhich\s+datasets?\b", metadata["effective_query"].lower())) or requests_global_scope(query)
    if broad_listing_query:
        max_items = 12
        min_score = max(1, sorted_scored[0][0] // 3) if sorted_scored else 1
        top_datasets = [dataset for score, dataset in sorted_scored if score >= min_score][:max_items]
        if not top_datasets:
            top_datasets = [dataset for _, dataset in sorted_scored[:max_items]]
    else:
        top_datasets = [dataset for _, dataset in sorted_scored[:6]]
    return top_datasets, combine_reference_entries(top_datasets), metadata


def build_prompt(query: str, datasets: list[dict], references: dict[str, str], metadata: dict | None = None) -> list[dict]:
    # Only the selected datasets and their reference entries are sent to the
    # model. This keeps the prompt compact and preserves grounding.
    metadata = metadata or {}
    context_blocks = []
    scope_labels = metadata.get("active_scope_labels") or []
    label_map = {
        item.get("dataset_name", ""): item.get("label", "")
        for item in scope_labels
        if item.get("dataset_name") and item.get("label")
    }
    for dataset in datasets:
        dataset_name = dataset.get("dataset_name", "")
        block = [
            f"Section: {dataset.get('section', '')}",
            f"Dataset: {dataset_name}",
            f"User-facing label: {label_map.get(dataset_name, dataset_name)}",
            f"Summary: {dataset.get('summary', '')}",
        ]
        if dataset.get("computational_methodology"):
            block.append(f"Computational methodology: {dataset['computational_methodology']}")
        if dataset.get("data_accessibility"):
            block.append(f"Data accessibility: {dataset['data_accessibility']}")
        block.append(f"Cited references: {', '.join(dataset.get('cited_references', [])) or 'None'}")
        context_blocks.append("\n".join(block))

    ref_block = "\n".join(f"[{num}] {text}" for num, text in sorted(references.items(), key=lambda item: int(item[0])))
    joined_context = "\n\n---\n\n".join(context_blocks)
    scope_block = "\n".join(
        f"- {item.get('label', '')} -> {item.get('dataset_name', '')}"
        for item in scope_labels
        if item.get("label") and item.get("dataset_name")
    )

    system = (
        "You are a careful research assistant for one review paper about molecular quantum-chemical datasets. "
        "Use the provided context as the primary grounded source. "
        "If the answer is not fully supported by the context, say that clearly. "
        "You may add concise general background knowledge from your own understanding when it helps the user, "
        "but you must clearly separate that from paper-grounded claims. "
        "Only use numbered citations in square brackets for claims supported by the provided context and references. "
        "Do not invent citations for your own background knowledge. "
        "Do not start your answer with phrases like 'Based solely on the provided context'. "
        "When you make a factual claim, cite the supporting reference numbers in square brackets, for example [1]. "
        "Preserve exact computational method strings from the provided context verbatim when possible, including symbols, prefixes, basis sets, and punctuation (for example ωB97X/6-31G(d)). "
        "Do not include your own References section at the end; the application will append the final normalized references block. "
        "Prefer precise, dataset-specific answers over generic summaries. "
        "If a dataset record covers a family but the user asked about a specific user-facing label, keep the answer anchored to the user-facing label. "
        "Do not replace a user-requested label with a sibling variant unless the user explicitly asks for that sibling. "
        "You may mention sibling variants only as supporting context inside the same family record."
    )
    user = (
        f"Question:\n{query}\n\n"
        f"User-requested scope labels:\n{scope_block or 'No explicit scope labels were provided.'}\n\n"
        f"Dataset context:\n\n{joined_context}\n\n"
        f"Reference entries:\n{ref_block or 'No references available.'}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_reference_numbers(text: str) -> list[str]:
    numbers = set()
    for raw in re.findall(r"\[([0-9,\- ]+)\]", text):
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                bounds = [p.strip() for p in part.split("-", 1)]
                if all(p.isdigit() for p in bounds):
                    start, end = map(int, bounds)
                    if start <= end:
                        numbers.update(str(i) for i in range(start, end + 1))
                continue
            if part.isdigit():
                numbers.add(part)
    return sorted(numbers, key=int)


SOURCE_MARKERS = [
    "Sci. Data",
    "Nat. Rev. Chem.",
    "Nat. Commun.",
    "Nat. Comput. Sci.",
    "J. Chem. Theory Comput.",
    "J. Chem. Inf. Model.",
    "J. Chem. Phys.",
    "J. Cheminf.",
    "Mach. Learn. Sci. Technol.",
    "Advances in Neural Information Processing Systems",
    "Phys. Chem. Chem. Phys.",
    "Digit. Discov.",
    "Front. Pharmacol.",
    "WIREs Comput. Mol. Sci.",
    "Wiley Interdiscip. Rev. Comput. Mol. Sci.",
    "Phys. Rev. Lett.",
    "New J. Phys.",
    "Chem. Sci.",
    "Struct. Sci.",
    "Angew. Chem., Int. Ed.",
    "Theor. Chem. Acc.",
    "ChemRxiv Preprint",
    "GitHub",
    "Zenodo",
    "Figshare",
    "Materials cloud",
    "(arXiv:",
]


def format_reference_entry(entry: str) -> str:
    # Reference strings come from line-joined PDF text, so a small formatter
    # makes them read more like normal bibliography entries in the UI.
    entry = re.sub(r"\s{2,}", " ", entry).strip()
    entry = re.sub(r"\((Zenodo|GitHub|Figshare|Materials cloud)\)\(", r" \1 (", entry)
    year_match = re.search(r"\b(19|20)\d{2}\b", entry)
    if not year_match:
        return entry

    authors = entry[: year_match.start()].strip().rstrip(",.")
    year = year_match.group(0)
    rest = entry[year_match.end() :].strip()

    source_index = -1
    for marker in SOURCE_MARKERS:
        index = rest.find(marker)
        if index != -1 and (source_index == -1 or index < source_index):
            source_index = index

    if source_index != -1:
        title = rest[:source_index].strip(" ,.;")
        source = rest[source_index:].strip()
        if title:
            return f"{authors} ({year}). {title}. {source}"
        return f"{authors} ({year}). {source}"

    return f"{authors} ({year}). {rest}"


def strip_existing_reference_block(answer: str) -> str:
    base = answer.rstrip()
    if not base:
        return base

    # Remove any model-generated trailing references section before we append
    # the normalized one. Models vary the heading style, so strip from the
    # last matching heading onward whenever such a heading appears.
    heading_matches = list(
        re.finditer(
            r"(?im)^(?:\*{0,2}\s*)?(?:#{1,6}\s*)?references(?:\s*\*{0,2})?\s*:?\s*$",
            base,
        )
    )
    if heading_matches:
        return base[: heading_matches[-1].start()].rstrip()

    # Some answers omit the heading but still end with a bibliography-like
    # block. If we find multiple reference-entry lines near the end, cut the
    # whole suffix and replace it with the normalized reference section.
    lines = base.splitlines()
    ref_line_indices = [idx for idx, line in enumerate(lines) if re.match(r"^\s*\[\d+\]\s+", line)]
    if len(ref_line_indices) >= 2 and ref_line_indices[0] >= max(0, len(lines) // 2):
        return "\n".join(lines[: ref_line_indices[0]]).rstrip()

    return base


def normalize_generated_answer_text(answer: str) -> str:
    text = answer or ""
    replacements = {
        "?2DFT": "∇2DFT",
        "nabla2DFT": "∇2DFT",
        "Nabla2DFT": "∇2DFT",
        "nabla-2DFT": "∇2DFT",
        "Nabla-2DFT": "∇2DFT",
        "nablasquareDFT": "∇2DFT",
        "NablasquareDFT": "∇2DFT",
        "nablaSquareDFT": "∇2DFT",
        "NablaSquareDFT": "∇2DFT",
        "nabla square DFT": "∇2DFT",
        "Nabla square DFT": "∇2DFT",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def ensure_reference_section(answer: str, references: dict[str, str]) -> str:
    # Whether the answer came from DeepSeek or the local fallback, normalize the
    # output to a single clean references block at the end.
    answer = normalize_generated_answer_text(answer)
    if not references:
        return answer

    cited_numbers = extract_reference_numbers(answer)
    if not cited_numbers:
        cited_numbers = sorted(references.keys(), key=int)[:3]

    entries = [f"[{num}] {format_reference_entry(references[num])}" for num in cited_numbers if num in references]
    if not entries:
        return answer

    base = strip_existing_reference_block(answer)
    return f"{base}\n\n**References**\n" + "\n".join(entries)


def is_error_response(text: str) -> bool:
    lowered = text.lower()
    return (
        lowered.startswith("network error while calling deepseek:")
        or lowered.startswith("deepseek api error ")
        or lowered.startswith("unexpected error while calling deepseek:")
        or lowered.startswith("deepseek api key not found.")
    )


def build_fallback_notice(error_text: str) -> str:
    reason = (error_text or "").strip()
    if not reason:
        reason = "DeepSeek was unavailable for this turn."
    return (
        "## DeepSeek Unavailable\n"
        f"**This response is using the local paper knowledge base only.**\n\n"
        f"Reason: {reason}"
    )


def build_fallback_response(query: str, datasets: list[dict], metadata: dict, refs: dict[str, str], error_text: str) -> str:
    local_answer = build_local_fallback_answer(query, datasets, metadata)
    answer = f"{build_fallback_notice(error_text)}\n\n{local_answer}"
    return ensure_reference_section(answer, refs)


def build_inventory_short_description(dataset: dict) -> str:
    summary = " ".join(str(dataset.get("summary", "")).split())
    name = dataset.get("dataset_name", "").strip()
    if not summary:
        return f"{name}: No short description is available in the current knowledge base." if name else "No short description is available in the current knowledge base."
    first_sentence = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)[0].strip()
    if not first_sentence:
        return f"{name}: No short description is available in the current knowledge base." if name else "No short description is available in the current knowledge base."
    if not name:
        return first_sentence
    return f"{name}: {first_sentence}"


def build_corpus_inventory_answer(kb: dict, query: str = "") -> str:
    datasets = [dataset for dataset in kb.get("datasets", []) if dataset.get("dataset_name", "").strip()]
    dataset_names = [dataset.get("dataset_name", "").strip() for dataset in datasets]
    total = len(dataset_names)
    lowered = query.lower()
    wants_all = any(
        phrase in lowered
        for phrase in ["list all", "list them all", "all of them", "all datasets", "all dataset", "full list", "show them all"]
    )
    wants_descriptions = any(
        phrase in lowered
        for phrase in [
            "short descript",
            "short description",
            "describe each",
            "brief description",
            "one line description",
            "one-line description",
            "what are they",
            "describe them",
        ]
    )

    if wants_descriptions:
        lines = [
            f"I can provide information about {total} dataset/database entries in the current knowledge base.\n",
            "**Dataset List With Short Descriptions**",
        ]
        for dataset in datasets:
            lines.append(f"- {build_inventory_short_description(dataset)}")
        return "\n".join(lines)

    if wants_all:
        lines = [
            f"I can provide information about {total} dataset/database entries in the current knowledge base.\n",
            "**All Dataset/Database Entries**",
        ]
        for dataset_name in dataset_names:
            lines.append(f"- {dataset_name}")
        return "\n".join(lines)

    preview = ", ".join(dataset_names[:12])
    extra = ""
    if total > 12:
        extra = f", and {total - 12} more"
    return (
        f"I can provide information about {total} dataset/database entries in the current knowledge base.\n\n"
        f"Examples include: {preview}{extra}.\n\n"
        "If you want, I can also list all of them or give a short description of each one."
    )


def build_inventory_prompt(kb: dict, query: str) -> tuple[list[dict], dict[str, str]]:
    datasets = [dataset for dataset in kb.get("datasets", []) if dataset.get("dataset_name", "").strip()]
    context_blocks = []
    references: dict[str, str] = {}

    for dataset in datasets:
        name = dataset.get("dataset_name", "").strip()
        summary = build_inventory_short_description(dataset)
        section = dataset.get("section", "").strip()
        refs = dataset.get("cited_references", [])[:3]
        ref_label = ", ".join(refs) if refs else "None"
        context_blocks.append(
            "\n".join(
                [
                    f"Section: {section or 'Unknown'}",
                    f"Dataset: {name}",
                    f"Short description: {summary}",
                    f"Representative references: {ref_label}",
                ]
            )
        )
        for ref_num, ref_text in dataset.get("reference_entries", {}).items():
            references[str(ref_num)] = ref_text

    system = (
        "You are a careful research assistant for one review paper about molecular quantum-chemical datasets. "
        "The user is asking a whole-knowledge-base inventory question across all available dataset entries. "
        "Use the provided inventory context to answer the user's request directly. "
        "If the user asks to list all datasets, list all of them. "
        "If the user asks for short descriptions, provide short one-line descriptions for each entry. "
        "If the user asks only for the count, give the count first and then a concise helpful summary. "
        "Only use numbered citations in square brackets for claims supported by the provided reference entries. "
        "Do not include your own References section at the end; the application will append the final normalized references block. "
        "Keep the answer organized and easy to scan."
    )
    user = (
        f"Question:\n{query}\n\n"
        f"Knowledge-base inventory context ({len(datasets)} entries):\n\n"
        + "\n\n---\n\n".join(context_blocks)
        + "\n\nAnswer the question using the full inventory context."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}], references


def build_small_talk_answer(query: str) -> str:
    lowered = query.lower().strip()
    if "thank" in lowered:
        return "You’re welcome. Ask me about a dataset, a comparison, methods, access links, or the full database whenever you’re ready."
    return "Hi, I am MLP Xplorer. I can provide you information about datasets and databases in this knowledge base, including comparisons, computational details, access links, references, and whole-database overviews. How can I help?"


def build_small_talk_answer(query: str) -> str:
    lowered = query.lower().strip()
    if "thank" in lowered:
        return "You are welcome. Ask me about a dataset, a comparison, methods, access links, or the full database whenever you are ready."
    if any(phrase in lowered for phrase in ["how can you help", "how you can help", "what can you do", "help"]):
        return (
            "Hi, I am MLP Xplorer. I can help you explore the datasets and databases in this knowledge base.\n\n"
            "I can:\n"
            "- summarize a specific dataset or database\n"
            "- compare two or more datasets\n"
            "- explain computational methods, levels of theory, basis sets, and software\n"
            "- tell you what properties, molecules, conformations, or excited-state data a dataset includes\n"
            "- provide access links and paper-grounded references\n"
            "- list all datasets in the knowledge base or give a short description of each one\n\n"
            "You can ask things like `What is QM9?`, `Compare SPICE and ANI-1x`, or `Which datasets include excited-state energies?`"
        )
    return "Hi, I am MLP Xplorer. I can provide you information about datasets and databases in this knowledge base, including comparisons, computational details, access links, references, and whole-database overviews. How can I help?"


def is_greeting_only_state(state: dict) -> bool:
    messages = state.get("ui_messages", [])
    if len(messages) != 2:
        return False
    first, second = messages
    if first.get("role") != "user" or second.get("role") != "assistant":
        return False
    if not is_small_talk_query(first.get("content", "")):
        return False
    return second.get("content", "").strip() == build_small_talk_answer(first.get("content", ""))


def extract_focus_text(text: str, query: str) -> str:
    if not text:
        return ""
    query_tokens = tokenize(query)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matched = [sentence.strip() for sentence in sentences if tokenize(sentence) & query_tokens]
    if matched:
        return " ".join(matched[:3]).strip()
    return text.strip()


def build_local_fallback_answer(query: str, datasets: list[dict], metadata: dict | None = None) -> str:
    # When DeepSeek is unavailable, answer directly from the retrieved KB
    # records instead of surfacing a raw API error to the user.
    metadata = metadata or {}
    if not datasets:
        return "I could not find matching dataset information in the local paper knowledge base."

    if len(datasets) > 1 or metadata.get("query_type") == "comparison":
        topic = metadata.get("topic", "")
        names = [dataset.get("dataset_name", "this dataset") for dataset in datasets[:6]]
        if topic == "accuracy":
            parts = [
                f"Based on the local paper knowledge base, there is no direct apples-to-apples accuracy ranking among {', '.join(names)}."
            ]
            for dataset in datasets[:6]:
                name = dataset.get("dataset_name", "This dataset")
                full_text = dataset.get("full_text", "")
                relevant = extract_focus_text(full_text, "accuracy accurate better CCSD(T) revised high level theory benchmark")
                if relevant:
                    parts.append(f"{name}: {relevant}")
            parts.append(
                "So the safest local-only answer is that the paper does not explicitly state which of these datasets is overall 'better' in accuracy; it only gives dataset-specific methodological clues."
            )
            return "\n\n".join(parts).strip()

        parts = ["Based on the local paper knowledge base, here is a comparison of the requested datasets:"]
        for dataset in datasets[:6]:
            name = dataset.get("dataset_name", "This dataset")
            summary = dataset.get("summary", "").strip()
            methodology = dataset.get("computational_methodology", "").strip()
            accessibility = dataset.get("data_accessibility", "").strip()

            block_parts = []
            focused_summary = extract_focus_text(summary, query)
            if focused_summary:
                block_parts.append(focused_summary)
            if methodology:
                first_method_sentence = re.split(r"(?<=[.!?])\s+", methodology, maxsplit=1)[0].strip()
                block_parts.append(f"Methodology: {first_method_sentence}")
            if accessibility:
                focused_accessibility = extract_focus_text(accessibility, query)
                if focused_accessibility:
                    block_parts.append(f"Data accessibility: {focused_accessibility}")
            parts.append(f"{name}: " + " ".join(block_parts).strip())
        return "\n\n".join(parts).strip()

    dataset = datasets[0]
    parts = []
    name = dataset.get("dataset_name", "This dataset")
    summary = dataset.get("summary", "").strip()
    methodology = dataset.get("computational_methodology", "").strip()
    accessibility = dataset.get("data_accessibility", "").strip()

    focused_summary = extract_focus_text(summary, query)
    focused_accessibility = extract_focus_text(accessibility, query)

    if focused_summary:
        parts.append(focused_summary)
    if methodology:
        first_method_sentence = re.split(r"(?<=[.!?])\s+", methodology, maxsplit=1)[0].strip()
        parts.append(f"Computational methodology: {first_method_sentence}")
    if focused_accessibility:
        parts.append(f"Data accessibility: {focused_accessibility}")

    answer = "\n\n".join(parts).strip()
    if not answer:
        answer = f"I found the section for {name}, but it does not contain enough text to answer confidently."
    return answer


def update_session_state(state: dict, query: str, datasets: list[dict], metadata: dict) -> None:
    # Persist the resolved scope from this turn so the next vague user message
    # can be interpreted as a follow-up instead of a brand-new search.
    dataset_names = [dataset.get("dataset_name", "") for dataset in datasets if dataset.get("dataset_name")]
    state["active_datasets"] = dataset_names
    state["active_aliases"] = metadata.get("active_aliases") or state["active_datasets"]
    state["last_context_dataset_names"] = dataset_names
    state["last_context_references"] = combine_reference_entries(datasets)
    state["last_query_type"] = metadata.get("query_type", "")
    state["last_topic"] = metadata.get("topic", "")
    state["last_user_query"] = query
    state["last_rewritten_query"] = metadata.get("effective_query", query)
    state["updated_at"] = time()


def call_deepseek(messages: list[dict]) -> str:
    return deepseek_request(messages, temperature=0.1, timeout=DEFAULT_DEEPSEEK_TIMEOUT)


BASE_CSS = """
:root {
  --bg: #f3ede2;
  --panel: rgba(255, 250, 242, 0.92);
  --ink: #211c17;
  --muted: #64594d;
  --accent: #0f6a5b;
  --accent-2: #b66a2f;
  --accent-3: #214f86;
  --border: #dccdb9;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at 0% 0%, rgba(182, 106, 47, 0.18), transparent 26%),
    radial-gradient(circle at 100% 0%, rgba(15, 106, 91, 0.18), transparent 28%),
    linear-gradient(180deg, #f7f2ea 0%, #eee1ce 100%);
  min-height: 100vh;
  font-size: 15px;
}
.shell { max-width: 1420px; margin: 0 auto; padding: 16px 18px 24px; }
.hero, .chat, .history-panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 20px;
  box-shadow: 0 14px 40px rgba(66, 46, 28, 0.08);
}
.hero { padding: 22px 24px; margin-bottom: 14px; }
.eyebrow {
  display: inline-block;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(15, 106, 91, 0.08);
  border: 1px solid rgba(15, 106, 91, 0.12);
  color: var(--accent);
  font-size: 0.9rem;
  margin-bottom: 14px;
}
h1 { margin: 0 0 10px; font-size: clamp(1.7rem, 3.4vw, 2.45rem); line-height: 1.04; }
p { margin: 0; color: var(--muted); line-height: 1.55; }
.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 14px; align-items: start; }
.chat { padding: 14px; }
.messages {
  height: 58vh;
  overflow-y: auto;
  padding: 4px 4px 12px;
  border-radius: 16px;
  background: rgba(255,255,255,0.3);
}
.msg {
  padding: 11px 13px;
  border-radius: 16px;
  margin: 8px 0;
  line-height: 1.54;
  box-shadow: 0 8px 24px rgba(60, 42, 22, 0.05);
}
.user { background: linear-gradient(135deg, #efdec8, #ead3b8); margin-left: 18%; }
.assistant { background: #fbf7f1; border: 1px solid var(--border); margin-right: 10%; }
.msg-body p { margin: 0 0 10px; }
.msg-body p:last-child { margin-bottom: 0; }
.msg-body strong { font-weight: 700; }
.msg-body em { font-style: italic; }
.msg-body code {
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 0.95em;
  background: rgba(15, 106, 91, 0.08);
  border: 1px solid rgba(15, 106, 91, 0.12);
  padding: 1px 6px;
  border-radius: 8px;
}
.msg-body pre {
  margin: 12px 0;
  padding: 12px 14px;
  overflow-x: auto;
  border-radius: 14px;
  background: #f5efe6;
  border: 1px solid var(--border);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 0.92rem;
}
.msg-body ul, .msg-body ol { margin: 10px 0 10px 22px; padding: 0; }
.msg-body blockquote {
  margin: 12px 0;
  padding: 8px 14px;
  border-left: 3px solid var(--accent-2);
  background: rgba(182, 106, 47, 0.08);
}
.msg-body h1, .msg-body h2, .msg-body h3, .msg-body h4 { margin: 14px 0 8px; font-size: 1.02rem; }
.msg-body .equation {
  margin: 12px 0;
  padding: 10px 14px;
  border-radius: 14px;
  background: rgba(33, 79, 134, 0.06);
  border: 1px solid rgba(33, 79, 134, 0.12);
  font-family: "Cambria Math", "Times New Roman", serif;
  overflow-x: auto;
}
.typing-indicator {
  color: var(--muted);
  font-style: italic;
}
.typing-indicator::after {
  content: " ...";
  animation: blinkDots 1.2s infinite;
}
@keyframes blinkDots {
  0% { opacity: 0.25; }
  50% { opacity: 1; }
  100% { opacity: 0.25; }
}
.msg-body h2 {
  display: inline-block;
  padding: 6px 10px;
  border-radius: 10px;
  background: rgba(182, 106, 47, 0.14);
  border: 1px solid rgba(182, 106, 47, 0.24);
}
.starter-row { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 8px; }
.starter-form, .history-form, .clear-form, .newchat-form { margin: 0; }
.composer { display: grid; grid-template-columns: 1fr auto; gap: 12px; margin-top: 8px; }
textarea {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  border-radius: 14px;
  border: 1px solid var(--border);
  padding: 12px 14px;
  font: inherit;
  font-size: 0.98rem;
  background: #fffdfa;
  color: var(--ink);
}
button {
  border: 0;
  border-radius: 14px;
  padding: 10px 18px;
  background: linear-gradient(135deg, var(--accent), var(--accent-3));
  color: white;
  font: inherit;
  cursor: pointer;
  min-width: 88px;
}
.secondary {
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.82);
  color: var(--ink);
}
.hint { margin-top: 10px; font-size: 0.86rem; color: var(--muted); }
.history-panel {
  padding: 14px;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
}
.history-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.history-title { margin: 0; font-size: 0.98rem; font-weight: 700; }
.history-subtitle { margin: 2px 0 0; font-size: 0.82rem; color: var(--muted); }
.history-list { display: flex; flex-direction: column; gap: 8px; overflow-y: auto; min-height: 0; }
.history-item {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(220, 205, 185, 0.9);
  background: rgba(255, 255, 255, 0.72);
  color: var(--ink);
}
.history-empty { color: var(--muted); font-size: 0.9rem; line-height: 1.5; padding: 8px 2px; }
.toolbar { display: flex; gap: 10px; margin-top: 10px; }
@media (max-width: 720px) {
  .shell { padding: 14px 12px 22px; }
  .hero, .chat, .history-panel { border-radius: 18px; }
  .workspace { grid-template-columns: 1fr; }
  .history-panel { position: static; max-height: none; }
  .composer { grid-template-columns: 1fr; }
  .user, .assistant { margin-left: 0; margin-right: 0; }
}
"""

STARTER_PROMPT_POOL = [
    ("What is QM9?", "What is QM9 and why is it widely used?"),
    ("Compare major sets", "Compare SPICE, ANI-1x, and MD17 with references."),
    ("Explore ANI-1x", "What is ANI-1x and what makes it important for machine learning potentials?"),
    ("Find drug-like data", "Which datasets are most relevant for drug-like molecules and peptide interactions?"),
    ("Show access links", "Compare the data accessibility of SPICE, QM9, and ANI-1x."),
    ("Benchmark dynamics", "What makes MD17 useful as a benchmark for molecular dynamics force fields?"),
    ("Look at methodology", "Compare the computational methodology used in ANI-1x, SPICE, and MD17."),
    ("Survey large sets", "Which datasets in this knowledge base are especially large in size or conformational coverage?"),
]


def pick_starter_prompts(count: int = 3, exclude: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    pool = list(STARTER_PROMPT_POOL)
    random.shuffle(pool)
    selected = pool[:count]

    if exclude and len(pool) > count:
        normalized_exclude = list(exclude)
        attempts = 0
        while selected == normalized_exclude and attempts < 8:
            random.shuffle(pool)
            selected = pool[:count]
            attempts += 1

    return selected


def refresh_session_starter_prompts(state: dict) -> None:
    previous = state.get("ui_starter_prompts", [])
    state["ui_starter_prompts"] = pick_starter_prompts(exclude=previous)


def render_starter_html(session_id: str, variant: str, prompts: list[tuple[str, str]] | None = None) -> str:
    prompts = prompts or STARTER_PROMPT_POOL[:3]
    return "".join(
        f"""
        <form class="starter-form" method="post" action="/chat">
          <input type="hidden" name="session_id" value="{html_escape(session_id)}">
          <input type="hidden" name="ui_variant" value="{html_escape(variant)}">
          <input type="hidden" name="message" value="{html_escape(prompt)}">
          <button class="secondary starter-card" type="submit">
            <span class="starter-card-title">{html_escape(label)}</span>
            <span class="starter-card-preview">{html_escape(prompt)}</span>
          </button>
        </form>
        """
        for label, prompt in prompts
    )


def get_or_create_session_id(header_cookie: str = "", explicit_session_id: str = "") -> str:
    if explicit_session_id:
        return explicit_session_id
    if header_cookie:
        for part in header_cookie.split(";"):
            piece = part.strip()
            if piece.startswith("mlpxplorer_session_id="):
                value = piece.split("=", 1)[1].strip()
                if value:
                    return value
    return str(uuid4())


def append_ui_turn(state: dict, user_message: str, assistant_message: str) -> None:
    state.setdefault("ui_messages", [])
    state.setdefault("ui_prompt_history", [])
    state["ui_messages"].append({"role": "user", "content": user_message})
    state["ui_messages"].append({"role": "assistant", "content": assistant_message})
    clean = user_message.strip()
    if clean:
        history = state["ui_prompt_history"]
        if clean in history:
            history.remove(clean)
        history.insert(0, clean)
        del history[24:]


def render_message_actions(role: str) -> str:
    if role == "user":
        return (
            '<div class="msg-actions">'
            '<button class="msg-action secondary" type="button" data-action="edit" aria-label="Edit prompt" title="Edit prompt">✎</button>'
            '<button class="msg-action secondary" type="button" data-action="copy" aria-label="Copy prompt" title="Copy prompt">⧉</button>'
            '</div>'
        )
    if role == "assistant":
        return (
            '<div class="msg-actions">'
            '<button class="msg-action secondary" type="button" data-action="copy" aria-label="Copy response" title="Copy response">⧉</button>'
            '</div>'
        )
    return ""


def render_message_block(role: str, content: str) -> str:
    role_name = html_escape(role)
    raw_content = html_escape(content)
    body_html = render_message_body_html(content)
    actions_html = render_message_actions(role)
    return (
        f'<div class="msg {role_name}" data-role="{role_name}" data-raw="{raw_content}">'
        f'<div class="msg-body">{body_html}</div>'
        f"{actions_html}"
        f"</div>"
    )


def render_message_body_html(text: str) -> str:
    return render_rich_text_server(text)


def render_rich_text_server(text: str) -> str:
    lines = str(text).replace("\r\n", "\n").split("\n")
    parts = []
    in_list = False
    in_ordered = False
    in_code = False
    code_lines: list[str] = []

    def close_lists() -> None:
        nonlocal in_list, in_ordered
        if in_list:
            parts.append("</ul>")
            in_list = False
        if in_ordered:
            parts.append("</ol>")
            in_ordered = False

    def flush_code() -> None:
        nonlocal in_code, code_lines
        if in_code:
            parts.append(f"<pre><code>{html_escape(chr(10).join(code_lines))}</code></pre>")
            in_code = False
            code_lines = []

    def format_inline(value: str) -> str:
        html = html_escape(value)
        html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
        html = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", html)
        return html

    def is_markdown_table_row(value: str) -> bool:
        return bool(re.match(r"^\|.*\|$", value))

    def is_markdown_table_separator(value: str) -> bool:
        compact = re.sub(r"\s+", "", value)
        return bool(re.match(r"^\|?[:\-|]+\|?$", compact)) and "-" in compact

    def split_markdown_table_row(value: str) -> list[str]:
        value = re.sub(r"^\|", "", value)
        value = re.sub(r"\|$", "", value)
        return [cell.strip() for cell in value.split("|")]

    index = 0
    while index < len(lines):
        raw_line = lines[index]
        trimmed = raw_line.strip()
        if trimmed.startswith("```"):
            close_lists()
            if in_code:
                flush_code()
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(raw_line)
            index += 1
            continue
        if not trimmed:
            close_lists()
            index += 1
            continue
        if (
            is_markdown_table_row(trimmed)
            and index + 1 < len(lines)
            and is_markdown_table_separator(lines[index + 1].strip())
        ):
            close_lists()
            header_cells = split_markdown_table_row(trimmed)
            body_rows: list[list[str]] = []
            index += 2
            while index < len(lines):
                next_trimmed = lines[index].strip()
                if not next_trimmed or not is_markdown_table_row(next_trimmed) or is_markdown_table_separator(next_trimmed):
                    break
                body_rows.append(split_markdown_table_row(next_trimmed))
                index += 1

            parts.append('<div class="table-wrap"><table><thead><tr>')
            for header_cell in header_cells:
                parts.append(f"<th>{format_inline(header_cell)}</th>")
            parts.append("</tr></thead><tbody>")
            for row in body_rows:
                parts.append("<tr>")
                for column_index in range(len(header_cells)):
                    parts.append(f"<td>{format_inline(row[column_index] if column_index < len(row) else '')}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table></div>")
            continue
        if re.match(r"^\$\$.*\$\$$", trimmed) or (trimmed.startswith("\\[") and trimmed.endswith("\\]")):
            close_lists()
            parts.append(f'<div class="equation">{html_escape(trimmed)}</div>')
            index += 1
            continue
        if re.match(r"^#{1,4}\s+", trimmed):
            close_lists()
            level = min(len(re.match(r"^#+", trimmed).group(0)), 4)
            heading_text = re.sub(r"^#{1,4}\s+", "", trimmed)
            parts.append(f"<h{level}>{format_inline(heading_text)}</h{level}>")
            index += 1
            continue
        if re.match(r"^>\s+", trimmed):
            close_lists()
            quote_text = re.sub(r"^>\s+", "", trimmed)
            parts.append(f"<blockquote>{format_inline(quote_text)}</blockquote>")
            index += 1
            continue
        if re.match(r"^[-*]\s+", trimmed):
            if in_ordered:
                parts.append("</ol>")
                in_ordered = False
            if not in_list:
                parts.append("<ul>")
                in_list = True
            bullet_text = re.sub(r"^[-*]\s+", "", trimmed)
            parts.append(f"<li>{format_inline(bullet_text)}</li>")
            index += 1
            continue
        if re.match(r"^\d+\.\s+", trimmed):
            if in_list:
                parts.append("</ul>")
                in_list = False
            if not in_ordered:
                parts.append("<ol>")
                in_ordered = True
            ordered_text = re.sub(r"^\d+\.\s+", "", trimmed)
            parts.append(f"<li>{format_inline(ordered_text)}</li>")
            index += 1
            continue
        close_lists()
        parts.append(f"<p>{format_inline(trimmed)}</p>")
        index += 1

    flush_code()
    close_lists()
    return "".join(parts)


def render_history_entries(messages: list[dict]) -> str:
    user_turns = []
    turn_index = 0
    index = 0
    while index < len(messages):
        item = messages[index]
        if item.get("role") == "user":
            turn_index += 1
            assistant_text = ""
            if index + 1 < len(messages) and messages[index + 1].get("role") == "assistant":
                assistant_text = messages[index + 1].get("content", "")
            user_turns.append(
                {
                    "turn_id": f"turn-{turn_index}",
                    "prompt": item.get("content", ""),
                    "response": assistant_text,
                }
            )
            index += 2
            continue
        index += 1

    if not user_turns:
        return '<div class="history-empty">Your recent questions will appear here.</div>'

    rows = []
    for entry in reversed(user_turns[-24:]):
        prompt = entry["prompt"].strip()
        rows.append(
            (
                f'<button class="history-item secondary" type="button" '
                f'data-action="jump-turn" data-target="{html_escape(entry["turn_id"])}">'
                f"{html_escape(prompt[:140])}</button>"
            )
        )
    return "".join(rows)


def render_user_message_html(text: str) -> str:
    return render_message_block("user", text)


def render_assistant_message_html(text: str) -> str:
    return render_message_block("assistant", text)


def load_text_asset(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_messages_html(messages: list[dict]) -> str:
    parts = []
    turn_index = 0
    index = 0
    while index < len(messages):
        item = messages[index]
        role = item.get("role", "assistant")
        content = item.get("content", "")
        if role == "user":
            turn_index += 1
            parts.append(f'<section class="turn" id="turn-{turn_index}" data-turn-id="turn-{turn_index}">')
            parts.append(render_message_block("user", content))
            if index + 1 < len(messages) and messages[index + 1].get("role") == "assistant":
                parts.append(render_message_block("assistant", messages[index + 1].get("content", "")))
                index += 1
            parts.append("</section>")
        else:
            parts.append(render_message_block(role, content))
        index += 1
    return "".join(parts)


def build_page_state_payload(session_id: str, state: dict, draft: str = "", variant: str = "modern") -> dict:
    return {
        "session_id": session_id,
        "status": state.get("ui_status", "Ready."),
        "messages_html": render_messages_html(state.get("ui_messages", [])),
        "prompt_history_html": render_history_entries(state.get("ui_messages", [])),
        "starter_html": render_starter_html(session_id, variant, state.get("ui_starter_prompts")),
        "draft": draft,
    }


def render_page(session_id: str, state: dict, draft: str = "", variant: str = "modern") -> str:
    messages = state.get("ui_messages", [])
    status = state.get("ui_status", "Ready.")
    message_html = render_messages_html(messages)
    starter_html = render_starter_html(session_id, variant, state.get("ui_starter_prompts"))
    history_html = render_history_entries(messages)
    template = load_text_asset(INDEX_TEMPLATE_PATH)
    replacements = {
        "__MESSAGES_HTML__": message_html,
        "__STARTER_HTML__": starter_html,
        "__SESSION_ID__": html_escape(session_id),
        "__DRAFT__": html_escape(draft),
        "__STATUS__": html_escape(status),
        "__HISTORY_HTML__": history_html,
        "__UI_VARIANT__": html_escape(variant),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template


class PaperChatHandler(BaseHTTPRequestHandler):
    kb = load_kb()

    def send_no_cache_headers(self) -> None:
        # Force a fresh fetch while we iterate quickly on the local frontend.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def send_session_cookie(self, session_id: str) -> None:
        self.send_header("Set-Cookie", f"mlpxplorer_session_id={session_id}; Path=/; SameSite=Lax")

    def safe_write(self, body: bytes) -> None:
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def send_html_page(self, session_id: str, state: dict, draft: str = "", variant: str = "modern") -> None:
        body = render_page(session_id, state, draft, variant).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_session_cookie(session_id)
        self.send_no_cache_headers()
        self.end_headers()
        self.safe_write(body)

    def send_json_payload(self, session_id: str, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_session_cookie(session_id)
        self.send_no_cache_headers()
        self.end_headers()
        self.safe_write(body)

    def send_json_error_payload(self, session_id: str, message: str, status: str = "The server hit an internal error.") -> None:
        payload = {
            "session_id": session_id,
            "status": status,
            "assistant_text": f"## Internal Error\n{message}",
            "assistant_html": render_message_body_html(f"## Internal Error\n{message}"),
            "prompt_history_html": render_history_entries(get_session_state(session_id).get("ui_messages", [])),
        }
        self.send_json_payload(session_id, payload)

    def send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_no_cache_headers()
        self.end_headers()
        self.safe_write(body)

    def parse_form_payload(self, raw: bytes) -> dict[str, str]:
        parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
        return {key: values[-1] if values else "" for key, values in parsed.items()}

    def do_GET(self) -> None:
        if self.path == "/static/style.css":
            self.send_bytes(STYLE_PATH.read_bytes(), "text/css; charset=utf-8")
            return
        if self.path == "/static/app.js":
            self.send_bytes(APP_JS_PATH.read_bytes(), "application/javascript; charset=utf-8")
            return
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.send_no_cache_headers()
            self.end_headers()
            return
        if self.path == "/modern":
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_no_cache_headers()
            self.end_headers()
            return
        if self.path in {"/", "/index.html"}:
            # Landing on the root page should open a fresh chat window rather
            # than reviving the previous conversation automatically.
            session_id = str(uuid4())
            SESSION_STATES[session_id] = default_session_state()
            state = SESSION_STATES[session_id]
            self.send_html_page(session_id, state, variant="modern")
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        is_ajax = self.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"
        session_id = ""
        try:
            if self.path == "/api/chat":
                payload = json.loads(raw.decode("utf-8"))
                message = payload.get("message", "")
                history = payload.get("history", [])
                session_id = get_or_create_session_id(self.headers.get("Cookie", ""), payload.get("session_id", "") or self.client_address[0])
                session_state = get_session_state(session_id)

                if is_small_talk_query(message):
                    metadata = {
                        "query_type": "small_talk",
                        "active_aliases": [],
                        "active_scope_labels": [],
                        "effective_query": message,
                        "topic": "",
                        "turn_kind": "small_talk",
                    }
                    answer = build_small_talk_answer(message)
                    session_state["ui_status"] = "Ready."
                    update_session_state(session_state, message, [], metadata)
                    append_ui_turn(session_state, message, answer)
                    response = {
                        "answer": answer,
                        "source_datasets": [],
                        "reference_numbers": [],
                        "session_id": session_id,
                    }
                    self.send_json_payload(session_id, response)
                    return

                if is_corpus_inventory_query(message) or is_inventory_follow_up_query(message, session_state):
                    metadata = {
                        "query_type": "inventory",
                        "active_aliases": [],
                        "active_scope_labels": [],
                        "effective_query": message,
                        "topic": "",
                        "turn_kind": "corpus_inventory",
                    }
                    prompt, refs = build_inventory_prompt(self.kb, message)
                    answer = call_deepseek(prompt)
                    if is_error_response(answer):
                        answer = build_corpus_inventory_answer(self.kb, message)
                        session_state["ui_status"] = "DeepSeek was unavailable for this turn. The page is showing a local-only inventory answer."
                    else:
                        answer = ensure_reference_section(answer, refs)
                        session_state["ui_status"] = "Ready."
                    update_session_state(session_state, message, [], metadata)
                    append_ui_turn(session_state, message, answer)
                    response = {
                        "answer": answer,
                        "source_datasets": [],
                        "reference_numbers": sorted(refs.keys(), key=int),
                        "session_id": session_id,
                    }
                    self.send_json_payload(session_id, response)
                    return

                datasets, refs, metadata = select_context(self.kb, message, session_state, history)
                effective_message = metadata.get("effective_query", message)
                prompt = build_prompt(effective_message, datasets, refs, metadata)
                answer = call_deepseek(prompt)
                if is_error_response(answer):
                    answer = build_fallback_response(effective_message, datasets, metadata, refs, answer)
                    session_state["ui_status"] = "DeepSeek was unavailable for this turn. The page is showing a local-only answer."
                else:
                    answer = ensure_reference_section(answer, refs)
                    session_state["ui_status"] = "Ready."
                update_session_state(session_state, message, datasets, metadata)
                append_ui_turn(session_state, message, answer)
                response = {
                    "answer": answer,
                    "source_datasets": [item.get("dataset_name", "") for item in datasets],
                    "reference_numbers": sorted(refs.keys(), key=int),
                    "session_id": session_id,
                }
                self.send_json_payload(session_id, response)
                return

            form = self.parse_form_payload(raw)
            session_id = get_or_create_session_id(self.headers.get("Cookie", ""), form.get("session_id", ""))
            session_state = get_session_state(session_id)
            ui_variant = "modern"

            if self.path == "/clear-history":
                session_state["ui_prompt_history"] = []
                session_state["ui_status"] = "Question history cleared."
                if is_ajax:
                    self.send_json_payload(session_id, build_page_state_payload(session_id, session_state, variant=ui_variant))
                    return
                self.send_html_page(session_id, session_state, variant=ui_variant)
                return

            if self.path == "/reset-chat":
                previous_prompts = session_state.get("ui_starter_prompts", [])
                SESSION_STATES[session_id] = default_session_state(previous_prompts)
                if is_ajax:
                    self.send_json_payload(session_id, build_page_state_payload(session_id, SESSION_STATES[session_id], variant=ui_variant))
                    return
                self.send_html_page(session_id, SESSION_STATES[session_id], variant=ui_variant)
                return

            if self.path != "/chat":
                self.send_error(404, "Not found")
                return

            message = form.get("message", "").strip()
            if not message:
                session_state["ui_status"] = "Please enter a prompt before sending."
                self.send_html_page(session_id, session_state, variant=ui_variant)
                return

            if is_small_talk_query(message):
                metadata = {
                    "query_type": "small_talk",
                    "active_aliases": [],
                    "active_scope_labels": [],
                    "effective_query": message,
                    "topic": "",
                    "turn_kind": "small_talk",
                }
                answer = build_small_talk_answer(message)
                session_state["ui_status"] = "Ready."
                update_session_state(session_state, message, [], metadata)
                append_ui_turn(session_state, message, answer)
                refresh_session_starter_prompts(session_state)
                if is_ajax:
                    self.send_json_payload(
                        session_id,
                        {
                            "session_id": session_id,
                            "status": session_state.get("ui_status", "Ready."),
                            "messages_html": render_messages_html(session_state.get("ui_messages", [])),
                            "user_html": render_user_message_html(message),
                            "assistant_text": answer,
                            "assistant_html": render_message_body_html(answer),
                            "prompt_history_html": render_history_entries(session_state.get("ui_messages", [])),
                            "starter_html": render_starter_html(session_id, ui_variant, session_state.get("ui_starter_prompts")),
                        },
                    )
                    return
                self.send_html_page(session_id, session_state, variant=ui_variant)
                return

            if is_corpus_inventory_query(message) or is_inventory_follow_up_query(message, session_state):
                metadata = {
                    "query_type": "inventory",
                    "active_aliases": [],
                    "active_scope_labels": [],
                    "effective_query": message,
                    "topic": "",
                    "turn_kind": "corpus_inventory",
                }
                prompt, refs = build_inventory_prompt(self.kb, message)
                answer = call_deepseek(prompt)
                if is_error_response(answer):
                    answer = build_corpus_inventory_answer(self.kb, message)
                    session_state["ui_status"] = "DeepSeek was unavailable for this turn. The page is showing a local-only inventory answer."
                else:
                    answer = ensure_reference_section(answer, refs)
                    session_state["ui_status"] = "Ready."
                update_session_state(session_state, message, [], metadata)
                append_ui_turn(session_state, message, answer)
                refresh_session_starter_prompts(session_state)
                if is_ajax:
                    self.send_json_payload(
                        session_id,
                        {
                            "session_id": session_id,
                            "status": session_state.get("ui_status", "Ready."),
                            "messages_html": render_messages_html(session_state.get("ui_messages", [])),
                            "user_html": render_user_message_html(message),
                            "assistant_text": answer,
                            "assistant_html": render_message_body_html(answer),
                            "prompt_history_html": render_history_entries(session_state.get("ui_messages", [])),
                            "starter_html": render_starter_html(session_id, ui_variant, session_state.get("ui_starter_prompts")),
                        },
                    )
                    return
                self.send_html_page(session_id, session_state, variant=ui_variant)
                return

            visible_history = []
            for item in session_state.get("ui_messages", []):
                if item.get("role") in {"user", "assistant"}:
                    record = {"role": item.get("role", ""), "content": item.get("content", "")}
                    if item.get("source_datasets"):
                        record["source_datasets"] = item.get("source_datasets", [])
                    visible_history.append(record)

            datasets, refs, metadata = select_context(self.kb, message, session_state, visible_history)
            effective_message = metadata.get("effective_query", message)
            prompt = build_prompt(effective_message, datasets, refs, metadata)
            answer = call_deepseek(prompt)
            if is_error_response(answer):
                answer = build_fallback_response(effective_message, datasets, metadata, refs, answer)
                session_state["ui_status"] = "DeepSeek was unavailable for this turn. The page is showing a local-only answer."
            else:
                answer = ensure_reference_section(answer, refs)
                session_state["ui_status"] = "Ready."

            update_session_state(session_state, message, datasets, metadata)
            append_ui_turn(session_state, message, answer)
            refresh_session_starter_prompts(session_state)
            if session_state.get("ui_messages"):
                session_state["ui_messages"][-1]["source_datasets"] = [item.get("dataset_name", "") for item in datasets]
            if is_ajax:
                self.send_json_payload(
                    session_id,
                    {
                        "session_id": session_id,
                        "status": session_state.get("ui_status", "Ready."),
                        "messages_html": render_messages_html(session_state.get("ui_messages", [])),
                        "user_html": render_user_message_html(message),
                        "assistant_text": answer,
                        "assistant_html": render_message_body_html(answer),
                        "prompt_history_html": render_history_entries(session_state.get("ui_messages", [])),
                        "starter_html": render_starter_html(session_id, ui_variant, session_state.get("ui_starter_prompts")),
                    },
                )
                return
            self.send_html_page(session_id, session_state, variant=ui_variant)
        except Exception as exc:
            if is_ajax:
                if not session_id:
                    session_id = get_or_create_session_id(self.headers.get("Cookie", ""), "")
                self.send_json_error_payload(session_id, f"The AJAX request failed on the server: {exc}")
                return
            raise


def main() -> None:
    # Run a tiny local HTTP server; the HTML/CSS/JS interface is embedded in
    # this file so the project has no frontend build step.
    server = ThreadingHTTPServer((HOST, PORT), PaperChatHandler)
    server.daemon_threads = True
    print(f"Paper chat running at {display_base_url()}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping chat server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
