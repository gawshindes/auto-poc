"""
Shared pipeline module — used by CLI (test_pipeline.py), Slack bot (bot.py), and web UI (web/app.py).

All run_* functions use module-level singletons for the Anthropic client, prompts, and registries
so they can be imported and called directly without any setup boilerplate.
"""

import json
import re
import os
from datetime import datetime
from pathlib import Path

import anthropic

PROJECT_ROOT = Path(__file__).resolve().parent

# DATA_DIR: persistent storage root.
# - Locally: defaults to PROJECT_ROOT (solutions.json lives at registry/solutions.json)
# - Railway: set DATA_DIR=/data (Railway Volume mount point)
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT)))
SOLUTIONS_PATH = DATA_DIR / "registry" / "solutions.json"


# ---------------------------------------------------------------------------
# Singletons — loaded once at import time
# ---------------------------------------------------------------------------

def _load_prompt(filename: str) -> str:
    path = PROJECT_ROOT / "prompts" / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text()


def _load_registry(filename: str, default: dict | None = None) -> dict:
    path = DATA_DIR / "registry" / filename
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(
            f"Registry file not found: {path}\n"
            f"Copy registry/{filename.replace('.json', '.example.json')} to registry/{filename} and fill in your data."
        )
    return json.loads(path.read_text())


def _load_solutions() -> dict:
    """Load solutions from DATA_DIR/solutions.json, creating it if missing."""
    if not SOLUTIONS_PATH.exists():
        SOLUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        empty = {
            "version": "1.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "note": "Solutions registry — populated automatically as demos are built.",
            "solutions": [],
            "matching_rules": {
                "full_match": "3+ keywords match AND demo_type matches → reuse and customize",
                "partial_match": "1-2 keywords match OR components are reusable → use as starting point",
                "no_match": "Build new → add to registry when done",
                "status_filter": "Only use solutions with status: built or in_progress (not planned)",
            },
        }
        SOLUTIONS_PATH.write_text(json.dumps(empty, indent=2))
    return json.loads(SOLUTIONS_PATH.read_text())


PROMPTS = {
    "classifier": _load_prompt("01_classifier.md"),
    "dependency":  _load_prompt("02_dependency_checker.md"),
    "matcher":     _load_prompt("03_solutions_matcher.md"),
    "messenger":   _load_prompt("04_sdr_messenger.md"),
    "builder":     _load_prompt("05_demo_builder.md"),
    "guide":       _load_prompt("06_demo_guide.md"),
}

REGISTRIES = {
    "capabilities": _load_registry("capabilities.json"),
    "solutions":    _load_solutions(),
    "team":         _load_registry("team.json", default={"team": []}),
}

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _client = anthropic.Anthropic(api_key=key)
    return _client


# ---------------------------------------------------------------------------
# Core stage runner
# ---------------------------------------------------------------------------

def run_stage(system_prompt: str, user_content: str, max_tokens: int = 2000,
              strip_fences: bool = True) -> str:
    response = get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text.strip()
    if strip_fences and "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if start != end:
            inner = text[start:end + 3]
            text = inner.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return text


def _parse_json(raw: str, stage_name: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"{stage_name} returned non-JSON:\n{raw[:500]}")


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

def run_classifier(transcript: str) -> dict:
    content = (
        f"Internal team members (anyone else is the customer):\n"
        f"{json.dumps(REGISTRIES['team']['team'], indent=2)}\n\n"
        f"Analyze this transcript:\n\n{transcript}"
    )
    return _parse_json(run_stage(PROMPTS["classifier"], content), "Classifier")


def run_dependency_checker(classifier_output: dict) -> dict:
    content = (
        f"Demo spec:\n{json.dumps(classifier_output, indent=2)}\n\n"
        f"Capabilities registry:\n{json.dumps(REGISTRIES['capabilities'], indent=2)}"
    )
    return _parse_json(run_stage(PROMPTS["dependency"], content), "Dependency Checker")


def run_solutions_matcher(classifier_output: dict, dependency_output: dict) -> dict:
    content = (
        f"Classifier output:\n{json.dumps(classifier_output, indent=2)}\n\n"
        f"Dependency output:\n{json.dumps(dependency_output, indent=2)}\n\n"
        f"Solutions registry:\n{json.dumps(REGISTRIES['solutions'], indent=2)}"
    )
    return _parse_json(run_stage(PROMPTS["matcher"], content), "Solutions Matcher")


def run_sdr_messenger(classifier_output: dict, dependency_output: dict,
                      matcher_output: dict) -> str:
    content = (
        f"Classifier:\n{json.dumps(classifier_output, indent=2)}\n"
        f"Dependency:\n{json.dumps(dependency_output, indent=2)}\n"
        f"Matcher:\n{json.dumps(matcher_output, indent=2)}"
    )
    return run_stage(PROMPTS["messenger"], content, max_tokens=1500)


def run_demo_builder(classifier_output: dict, dependency_output: dict,
                     matcher_output: dict, customer_inputs: str = "") -> str:
    content = (
        f"Classifier spec:\n{json.dumps(classifier_output, indent=2)}\n"
        f"Dependency spec:\n{json.dumps(dependency_output, indent=2)}\n"
        f"Solutions matcher:\n{json.dumps(matcher_output, indent=2)}\n"
        f"Customer-provided inputs:\n{customer_inputs or 'None — build with mocks only'}"
    )
    return run_stage(PROMPTS["builder"], content, max_tokens=16000, strip_fences=False)


def run_demo_guide(classifier_output: dict, demo_output: str, live_url: str = "") -> str:
    file_list = re.findall(
        r'\*\*([^\n*`#]{1,80})\*\*|\n#{1,3}\s+([^\n*`#]{1,80})\n|```[^\n]*\n#\s*([a-zA-Z0-9_./-]{1,80})\n',
        demo_output,
    )
    filenames = [next(f for f in match if f) for match in file_list if any(f for f in match)]
    content = (
        f"Classifier:\n{json.dumps(classifier_output, indent=2)}\n\n"
        f"Demo app files: {', '.join(filenames) if filenames else 'see demo output'}\n\n"
        f"Live URL: {live_url or 'not yet deployed'}"
    )
    return run_stage(PROMPTS["guide"], content, max_tokens=1000, strip_fences=False)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def reload_solutions() -> dict:
    """Re-read solutions.json from disk (used after appending a new entry)."""
    return _load_solutions()


def append_to_registry(matcher_output: dict, classifier_output: dict,
                       deploy_url: str | None = None) -> str | None:
    """
    Append a newly built solution to registry/solutions.json.
    Returns the new solution ID, or None if skipped.
    """
    if not matcher_output.get("add_to_registry_after_build", False):
        return None

    suggested = matcher_output.get("suggested_registry_entry", {})
    if not suggested or not suggested.get("name"):
        return None

    data = json.loads(SOLUTIONS_PATH.read_text())
    solutions = data.get("solutions", [])

    name = suggested.get("name", "")
    if any(s.get("name", "").lower() == name.lower() for s in solutions):
        return None  # duplicate

    existing_ids = [s.get("id", "") for s in solutions if s.get("id", "").startswith("sol_")]
    max_num = max(
        (int(i.split("_")[1]) for i in existing_ids
         if len(i.split("_")) > 1 and i.split("_")[1].isdigit()),
        default=0,
    )
    new_id = f"sol_{max_num + 1:03d}"

    customer = classifier_output.get("customer", {})
    entry = {
        "id": new_id,
        "name": name,
        "description": suggested.get("description", ""),
        "built_for": customer.get("company", ""),
        "demo_type": suggested.get("demo_type") or classifier_output.get("demo_type", "custom"),
        "keywords": suggested.get("keywords", []),
        "stack": suggested.get("stack", ""),
        "source": "demo_tool",
        "status": "built",
        "demo_url": deploy_url or None,
    }

    solutions.append(entry)
    data["solutions"] = solutions
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    SOLUTIONS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # Keep in-memory registry in sync
    REGISTRIES["solutions"] = data
    return new_id


# ---------------------------------------------------------------------------
# Transcript reader
# ---------------------------------------------------------------------------

def read_transcript(path: Path) -> str:
    """Read a transcript file (.txt or .pdf) and return plain text."""
    suffix = path.suffix.lower()

    if suffix in (".txt", ".md", ""):
        return path.read_text(encoding="utf-8").strip()

    if suffix == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")
        text_parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        text = "\n".join(text_parts).strip()
        if not text:
            raise ValueError(
                f"PDF appears to be empty or unreadable (no text extracted): {path.name}\n"
                "Try exporting the transcript as a .txt file instead."
            )
        return text

    raise ValueError(f"Unsupported file type '{suffix}'. Use .txt or .pdf.")
