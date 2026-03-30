"""
Shared pipeline module — used by CLI (test_pipeline.py), Slack bot (bot.py), and web UI (web/app.py).

4-stage pipeline: Understand → Design → Build → Guide

All run_* functions use module-level singletons for the Anthropic client, prompts, and registries
so they can be imported and called directly without any setup boilerplate.
"""

import json
import re
import os
from pathlib import Path

import anthropic

PROJECT_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Singletons — loaded once at import time
# ---------------------------------------------------------------------------

def _load_prompt(filename: str) -> str:
    path = PROJECT_ROOT / "prompts" / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text()


def _load_registry(filename: str, default: dict | None = None) -> dict:
    path = PROJECT_ROOT / "registry" / filename
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(
            f"Registry file not found: {path}\n"
            f"Copy registry/{filename.replace('.json', '.example.json')} to registry/{filename} and fill in your data."
        )
    return json.loads(path.read_text())


PROMPTS = {
    "understand":       _load_prompt("01_understand.md"),
    "design":           _load_prompt("02_design.md"),
    "builder":          _load_prompt("03_build.md"),
    "verify":           _load_prompt("03b_verify.md"),
    "guide":            _load_prompt("04_guide.md"),
    "capabilities":     _load_prompt("capabilities.md"),
}

def _get_team() -> list[str]:
    """Get team members from DB, falling back to registry/team.json for migration."""
    try:
        team = _get_backend().get_team()
        if team:
            return team
    except Exception:
        pass
    # Fallback to file for backward compat during migration
    data = _load_registry("team.json", default={"team": []})
    return data.get("team", [])

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
# Storage backend (lazy import to avoid circular deps)
# ---------------------------------------------------------------------------

def _get_backend():
    from storage import get_backend
    return get_backend()


# ---------------------------------------------------------------------------
# Core stage runner
# ---------------------------------------------------------------------------

def run_stage(system_prompt: str, user_content: str, max_tokens: int = 2000,
              strip_fences: bool = True) -> str:
    response = get_client().messages.create(
        model=os.environ.get("BUILDER_ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        extra_headers={"anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"}
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
# Pipeline stages (4-stage: Understand → Design → Build → Guide)
# ---------------------------------------------------------------------------

def run_understand(transcript: str) -> dict:
    """Stage 1: Classify + dependencies + knowledge resolution + solutions match."""
    team = _get_team()
    solutions = json.dumps(_get_backend().get_solutions(), indent=2)
    content = (
        f"Internal team members (anyone else is the customer):\n"
        f"{json.dumps(team, indent=2)}\n\n"
        f"Agency capabilities:\n{PROMPTS['capabilities']}\n\n"
        f"Solutions registry (existing demos):\n{solutions}\n\n"
        f"Analyze this transcript:\n\n{transcript}"
    )
    return _parse_json(run_stage(PROMPTS["understand"], content, max_tokens=4000), "Understand")


def get_available_skills() -> list[dict]:
    """Scan the skills directory and return a list of parsed manifest.json dictionaries."""
    skills = []
    skills_dir = PROJECT_ROOT / "skills"
    if not skills_dir.exists():
        return skills
    for entry in skills_dir.iterdir():
        if entry.is_dir():
            manifest_path = entry / "manifest.json"
            if manifest_path.exists():
                try:
                    skills.append(json.loads(manifest_path.read_text()))
                except json.JSONDecodeError:
                    pass
    return skills


def run_design(understand_output: dict, customer_inputs: str = "") -> dict:
    """Stage 2: Solutions match + SDR message + demo blueprint."""
    solutions = json.dumps(_get_backend().get_solutions(), indent=2)
    available_skills = json.dumps(get_available_skills(), indent=2)
    content = (
        f"Stage 1 (Understand) output:\n{json.dumps(understand_output, indent=2)}\n\n"
        f"Solutions registry:\n{solutions}\n\n"
        f"Available API Skills:\n{available_skills}\n\n"
        f"Customer-provided inputs:\n{customer_inputs or 'None'}"
    )
    return _parse_json(run_stage(PROMPTS["design"], content, max_tokens=6000), "Design")


def run_build(design_output: dict, customer_inputs: str = "") -> str:
    """Stage 3: Implement the spec from Design stage."""
    demo_spec = design_output.get("demo_spec", {})
    component_matches = design_output.get("component_matches", [])
    
    required_skills = demo_spec.get("required_skills", [])
    skill_adapters = ""
    if required_skills:
        for skill_name in required_skills:
            adapter_path = PROJECT_ROOT / "skills" / skill_name / "adapter.py"
            if adapter_path.exists():
                adapter_code = adapter_path.read_text()
                skill_adapters += f"\n--- {skill_name} adapter ---\n{adapter_code}\n"
    
    content = (
        f"Demo spec:\n{json.dumps(demo_spec, indent=2)}\n\n"
        f"Component matches:\n{json.dumps(component_matches, indent=2)}\n\n"
        f"Requested Skill Adapters (Do NOT redefine these, import from their skills.* package):\n{skill_adapters or 'None'}\n\n"
        f"Customer-provided inputs:\n{customer_inputs or 'None'}"
    )
    return run_stage(PROMPTS["builder"], content, max_tokens=16000, strip_fences=False)


def run_verify(demo_output: str, issues: list[str]) -> str:
    """Stage 3b: Fix code issues found by static analysis."""
    content = (
        f"Demo code:\n{demo_output}\n\n"
        f"Issues found by static analysis:\n"
        + "\n".join(f"- {issue}" for issue in issues)
    )
    return run_stage(PROMPTS["verify"], content, max_tokens=16000, strip_fences=False)


def run_guide(understand_output: dict, demo_output: str, live_url: str = "") -> str:
    """Stage 4: Demo guide for the founder."""
    file_list = re.findall(
        r'\*\*([^\n*`#]{1,80})\*\*|\n#{1,3}\s+([^\n*`#]{1,80})\n|```[^\n]*\n#\s*([a-zA-Z0-9_./-]{1,80})\n',
        demo_output,
    )
    filenames = [next(f for f in match if f) for match in file_list if any(f for f in match)]
    content = (
        f"Understanding:\n{json.dumps(understand_output, indent=2)}\n\n"
        f"Demo app files: {', '.join(filenames) if filenames else 'see demo output'}\n\n"
        f"Live URL: {live_url or 'not yet deployed'}"
    )
    return run_stage(PROMPTS["guide"], content, max_tokens=1000, strip_fences=False)


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------

def append_to_registry(design_output: dict, understand_output: dict,
                       deploy_url: str | None = None) -> str | None:
    """
    Append a newly built solution to the solutions registry.
    Returns the new solution ID, or None if skipped.
    """
    if not design_output.get("add_to_registry_after_build", False):
        return None

    suggested = design_output.get("suggested_registry_entry", {})
    if not suggested or not suggested.get("name"):
        return None

    backend = _get_backend()
    data = backend.get_solutions()
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

    customer = understand_output.get("customer", {})
    entry = {
        "id": new_id,
        "name": name,
        "description": suggested.get("description", ""),
        "built_for": customer.get("company", ""),
        "demo_type": suggested.get("demo_type") or understand_output.get("demo_type", "custom"),
        "stack": suggested.get("stack", ""),
        "source": "demo_tool",
        "status": "built",
        "demo_url": deploy_url or None,
    }

    backend.append_solution(entry, data)
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
