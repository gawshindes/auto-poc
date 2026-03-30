import os
import re
import json
import time
import ast
from dataclasses import dataclass, field
from pathlib import Path

import requests

GITHUB_API = "https://api.github.com"
RAILWAY_API = "https://backboard.railway.app/graphql/v2"


class ValidationError(Exception):
    pass


# Packages that will break Railway builds or are explicitly forbidden
_BANNED_PACKAGES = ["playwright", "greenlet", "openai"]  # openai: no OPENAI_API_KEY on Railway
_BANNED_PYDANTIC = re.compile(r"pydantic\s*[=<>!]=?\s*2\.[0-6]\b|pydantic\s*[=<>!]=?\s*1\.")


def _fix_truncated_json(broken_json: str) -> str:
    """Attempts to intelligently close truncated JSON strings and objects."""
    s = broken_json.strip()
    
    # 1. Close unescaped strings
    unmasked = s.replace('\\"', '')
    if unmasked.count('"') % 2 != 0:
        s += '"'
        
    s = s.strip()
    
    # 2. Cleanup trailing commas/colons
    if s.endswith(','):
        s = s[:-1].strip()
    elif s.endswith(':'):
        s += ' null'
        
    # 3. Handle uncompleted dictionary properties (e.g., `"recent_`)
    try:
        json.loads(s + '}')
    except json.JSONDecodeError as e:
        if "Expecting ':' delimiter" in str(e):
            s += ': null'

    # 4. Use LIFO stack to find necessary closing braces/brackets
    stack = []
    in_string = False
    escape = False
    for char in s:
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
            
        if not in_string:
            if char in '{[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
                    
    closing_suffix = ""
    for char in reversed(stack):
        if char == '{':
            closing_suffix += '}'
        elif char == '[':
            closing_suffix += ']'
            
    return s + closing_suffix


def validate_demo_files(files: dict) -> list:
    """
    Pre-deploy sanity checks on parsed demo files.

    Hard failures (raises ValidationError): missing required files, banned packages, syntax errors.
    Soft warnings (returned as list): missing $PORT usage.

    Args:
        files: dict of {filepath: content} from parse_demo_files()

    Returns:
        List of warning strings (empty = clean).
    """
    errors = []
    warnings = []

    # 1. Required files
    for required in ("main.py", "requirements.txt", "Procfile"):
        if required not in files:
            errors.append(f"Missing required file: {required}")
    if errors:
        raise ValidationError("Pre-deploy check failed:\n" + "\n".join(f"  • {e}" for e in errors))

    # 2. Banned packages
    req_content = files["requirements.txt"]
    bad_pkgs = []
    for line in req_content.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        for banned in _BANNED_PACKAGES:
            if banned in line:
                bad_pkgs.append(line)
        if _BANNED_PYDANTIC.search(line):
            bad_pkgs.append(line)
    if bad_pkgs:
        raise ValidationError(
            "Banned packages in requirements.txt (will fail Railway build):\n"
            + "\n".join(f"  • {p}" for p in bad_pkgs)
        )

    # 3. python-multipart required if form/file upload is used
    main_content = files["main.py"]
    form_indicators = ("UploadFile", "Form(", "File(")
    if any(ind in main_content for ind in form_indicators):
        req_lower = req_content.lower()
        if "python-multipart" not in req_lower:
            errors.append(
                "main.py uses form data (UploadFile/Form/File) but requirements.txt "
                "is missing python-multipart — Railway deploy will crash"
            )
    if errors:
        raise ValidationError("Pre-deploy check failed:\n" + "\n".join(f"  • {e}" for e in errors))

    # 4. $PORT usage (soft warning)
    if "PORT" not in main_content:
        warnings.append("main.py does not reference $PORT — app may not bind correctly on Railway")

    # 5. Python syntax check and AST validation (in-memory, works anywhere)
    try:
        tree = ast.parse(main_content, filename="main.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                is_template_call = False
                if isinstance(node.func, ast.Attribute) and node.func.attr == "TemplateResponse":
                    is_template_call = True
                elif isinstance(node.func, ast.Name) and node.func.id == "TemplateResponse":
                    is_template_call = True
                
                if is_template_call and node.args:
                    first_arg = node.args[0]
                    # If first arg is a string literal (e.g. "index.html"), it's using the old deprecated syntax
                    is_str_literal = (isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)) or type(first_arg).__name__ == "Str"
                    if is_str_literal:
                        raise ValidationError("TemplateResponse called with template name as first positional argument. Starlette 0.28+ requires `request` as the first argument. LLM must use `TemplateResponse(request=request, name='...', context={...})`")
    except SyntaxError as e:
        raise ValidationError(f"Syntax error in main.py: {e}")

    # 6. JSON syntax check for data files (malformed JSON crashes app at startup)
    for fname, fcontent in files.items():
        if fname.endswith(".json") and fcontent.strip():
            try:
                json.loads(fcontent)
            except json.JSONDecodeError as base_e:
                # LLM output truncated? Attempt simple fix
                try:
                    fixed = _fix_truncated_json(fcontent)
                    json.loads(fixed)
                    files[fname] = fixed  # Save the fixed version
                    warnings.append(f"Auto-fixed malformed JSON in {fname}")
                except Exception as final_e:
                    raise ValidationError(f"Malformed JSON in {fname}: {base_e} (auto-fix failed: {final_e})")

    return warnings


# ---------------------------------------------------------------------------
# Enhanced validation (returns report instead of raising)
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """Result of static analysis on demo files."""
    files: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    fixable: bool = False  # True if errors can be auto-fixed by verification agent


def analyze_demo_files(files: dict) -> ValidationReport:
    """
    Static analysis on parsed demo files. Returns a structured report
    instead of raising — lets the verification agent fix issues.
    """
    report = ValidationReport(files=files)

    # 1. Required files (NOT fixable — can't invent missing files)
    for required in ("main.py", "requirements.txt", "Procfile"):
        if required not in files:
            report.errors.append(f"Missing required file: {required}")
    if report.errors:
        return report  # Can't analyze further without required files

    main_content = files["main.py"]
    req_content = files["requirements.txt"]

    # 2. Banned packages (NOT fixable)
    for line in req_content.splitlines():
        line_stripped = line.strip().lower()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        for banned in _BANNED_PACKAGES:
            if banned in line_stripped:
                report.errors.append(f"Banned package: {line.strip()}")
        if _BANNED_PYDANTIC.search(line_stripped):
            report.errors.append(f"Banned pydantic version: {line.strip()}")

    # 3. python-multipart check (FIXABLE)
    form_indicators = ("UploadFile", "Form(", "File(")
    if any(ind in main_content for ind in form_indicators):
        if "python-multipart" not in req_content.lower():
            report.errors.append(
                "main.py uses form data (UploadFile/Form/File) but requirements.txt "
                "is missing python-multipart>=0.0.9"
            )
            report.fixable = True

    # 4. $PORT binding (FIXABLE)
    if "PORT" not in main_content:
        report.errors.append(
            "main.py does not reference $PORT — app will not bind correctly on Railway"
        )
        report.fixable = True

    # 5. AST-based checks (FIXABLE)
    try:
        tree = ast.parse(main_content, filename="main.py")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # TemplateResponse deprecated syntax
            is_template_call = (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "TemplateResponse")
                or (isinstance(node.func, ast.Name) and node.func.id == "TemplateResponse")
            )
            if is_template_call and node.args:
                first_arg = node.args[0]
                is_str_literal = (
                    isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str)
                ) or type(first_arg).__name__ == "Str"
                if is_str_literal:
                    report.errors.append(
                        f"Line {node.lineno}: TemplateResponse uses deprecated syntax. "
                        "Must use TemplateResponse(request=request, name='...', context={{...}})"
                    )
                    report.fixable = True

    except SyntaxError as e:
        report.errors.append(f"Syntax error in main.py: {e}")
        report.fixable = True

    # 6. Hardcoded model names (FIXABLE)
    hardcoded_models = ["claude-sonnet-4-20250514", "claude-3-5-sonnet", "claude-3-opus"]
    for model in hardcoded_models:
        if f'"{model}"' in main_content or f"'{model}'" in main_content:
            report.errors.append(
                f"Hardcoded model name '{model}' in main.py — "
                "must use os.environ.get('ANTHROPIC_MODEL', 'claude-3-haiku-20240307')"
            )
            report.fixable = True

    # 7. JSON file checks
    for fname, fcontent in files.items():
        if fname.endswith(".json") and fcontent.strip():
            try:
                json.loads(fcontent)
            except json.JSONDecodeError:
                try:
                    fixed = _fix_truncated_json(fcontent)
                    json.loads(fixed)
                    files[fname] = fixed
                    report.warnings.append(f"Auto-fixed truncated JSON in {fname}")
                except Exception:
                    report.errors.append(f"Malformed JSON in {fname}")
                    report.fixable = True

    return report


# ---------------------------------------------------------------------------
# Post-deploy health check
# ---------------------------------------------------------------------------

def health_check(url: str, retries: int = 3, delay: int = 5) -> bool:
    """
    GET the deploy URL and verify it returns a 2xx/3xx response.
    Retries with linear backoff to handle slow startups.
    """
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            if 200 <= resp.status_code < 400:
                return True
        except requests.RequestException:
            pass
        if attempt < retries - 1:
            time.sleep(delay * (attempt + 1))
    return False


# ---------------------------------------------------------------------------
# Deploy result
# ---------------------------------------------------------------------------

@dataclass
class DeployResult:
    """Rich result from deploy_demo() with all deploy metadata."""
    url: str
    github_repo: str
    project_id: str
    service_id: str
    environment_id: str
    verified: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

def _github_headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _railway_headers():
    return {
        "Authorization": f"Bearer {os.environ['RAILWAY_TOKEN']}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Railway helper
# ---------------------------------------------------------------------------

def _railway(query: str, variables: dict) -> dict:
    resp = requests.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers=_railway_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Railway API error: {data['errors']}")
    return data["data"]


# ---------------------------------------------------------------------------
# Step 0: Parse demo builder output → {filepath: content}
# ---------------------------------------------------------------------------

def parse_demo_files(demo_output: str) -> dict:
    """
    Parse Claude's markdown output into {filepath: file_content}.

    Looks for patterns like:
      ## main.py           (or ### or **main.py**)
      ```python
      <content>
      ```

    Falls back to {"demo.md": demo_output} if no structured blocks found.
    """
    # Five patterns covering all formats Claude uses:
    #   **filename.py**[optional text]\n```lang\n<content>\n```
    #   ## filename.py\n```lang\n<content>\n```  (1–4 hashes, with or without backtick-wrapped name)
    #   ```lang\n# filename.py\n<content>\n```        (Python/shell comment)
    #   ```lang\n<!-- filename.html -->\n<content>\n```  (HTML comment)
    # (?:```|$) lets us recover the last file even if output was truncated mid-block
    # Filename capture allows backticks so ` `main.py` ` headers are handled
    bold_pat    = re.compile(r'\*\*`?([^\n*#]{1,80}?)`?\*\*[^\n]*\n+```[^\n]*\n(.*?)(?:```|$)', re.DOTALL)
    head_pat    = re.compile(r'#{1,4}\s+`?([^\n*#]{1,80}?)`?[ \t]*\n+```[^\n]*\n(.*?)(?:```|$)', re.DOTALL)
    py_cmt_pat  = re.compile(r'```[^\n]*\n#\s*([a-zA-Z0-9_./-]{1,80})\n(.*?)(?:```|$)', re.DOTALL)
    html_cmt_pat = re.compile(r'```[^\n]*\n<!--\s*([a-zA-Z0-9_./-]{1,80})\s*-->\n(.*?)(?:```|$)', re.DOTALL)
    pairs = (bold_pat.findall(demo_output) + head_pat.findall(demo_output)
             + py_cmt_pat.findall(demo_output) + html_cmt_pat.findall(demo_output))
    files = {}
    for filename, content in pairs:
        filename = filename.strip().strip("`").strip().rstrip(":- ")
        # Strip leading /demo-<slug>/ prefix that Claude sometimes adds
        filename = re.sub(r'^/demo-[^/]+/', '', filename)
        # Require at least one dot or a known extensionless name
        if filename and (
            '.' in filename
            or filename in ('Makefile', 'Dockerfile', 'Procfile')
        ):
            files[filename] = content.strip()

    if not files:
        files["demo.md"] = demo_output
    return files


# ---------------------------------------------------------------------------
# Step 1: GitHub — create repo
# ---------------------------------------------------------------------------

def create_github_repo(slug: str) -> tuple:
    """Create a public GitHub repo. Returns (full_name, owner_login).
    If the base name already exists, retries once with a date suffix (e.g. demo-slug-0304).
    """
    from datetime import datetime
    org = os.environ.get("GITHUB_ORG")

    def _try_create(name):
        endpoint = f"{GITHUB_API}/orgs/{org}/repos" if org else f"{GITHUB_API}/user/repos"
        return requests.post(
            endpoint,
            json={"name": name, "private": False, "auto_init": True},
            headers=_github_headers(),
            timeout=20,
        )

    repo_name = f"demo-{slug}"
    resp = _try_create(repo_name)

    if resp.status_code == 422:
        # Repo already exists — append timestamp (MMDD-HHMMSS) to ensure uniqueness
        suffix = datetime.now().strftime("%m%d-%H%M%S")
        repo_name = f"demo-{slug}-{suffix}"
        resp = _try_create(repo_name)

    if not resp.ok:
        # Surface the actual GitHub error message for easier diagnosis
        try:
            gh_err = resp.json()
        except Exception:
            gh_err = resp.text
        raise RuntimeError(
            f"GitHub repo creation failed ({resp.status_code}): {gh_err}"
        )
    data = resp.json()
    return data["full_name"], data["owner"]["login"]


# ---------------------------------------------------------------------------
# Step 2: GitHub — push all files in one commit (Git Tree API)
# ---------------------------------------------------------------------------

def push_files_to_github(full_name: str, files: dict) -> None:
    """
    Push all demo files to GitHub in a single initial commit.
    Uses the Git Tree API — no git CLI required.
    """
    h = _github_headers()

    # Get the SHA of the initial commit GitHub created (auto_init=True guarantees this exists)
    ref_resp = requests.get(
        f"{GITHUB_API}/repos/{full_name}/git/refs/heads/main",
        headers=h,
        timeout=20,
    )
    ref_resp.raise_for_status()
    base_sha = ref_resp.json()["object"]["sha"]

    # Build tree (all files as inline blobs)
    tree = [
        {"path": path, "mode": "100644", "type": "blob", "content": content}
        for path, content in files.items()
    ]
    tree_resp = requests.post(
        f"{GITHUB_API}/repos/{full_name}/git/trees",
        json={"tree": tree},
        headers=h,
        timeout=30,
    )
    tree_resp.raise_for_status()
    tree_sha = tree_resp.json()["sha"]

    # Create commit parented off the initial auto_init commit
    commit_resp = requests.post(
        f"{GITHUB_API}/repos/{full_name}/git/commits",
        json={
            "message": "Initial demo build by Demo Creator agent",
            "tree": tree_sha,
            "parents": [base_sha],
        },
        headers=h,
        timeout=20,
    )
    commit_resp.raise_for_status()
    commit_sha = commit_resp.json()["sha"]

    # Fast-forward main to our commit (PATCH — ref already exists from auto_init)
    update_resp = requests.patch(
        f"{GITHUB_API}/repos/{full_name}/git/refs/heads/main",
        json={"sha": commit_sha},
        headers=h,
        timeout=20,
    )
    update_resp.raise_for_status()


# ---------------------------------------------------------------------------
# Step 3: Railway — create project + service
# ---------------------------------------------------------------------------

def create_railway_project(slug: str, github_repo: str) -> tuple:
    """
    Create a Railway project and link it to the GitHub repo.
    Returns (project_id, environment_id, service_id).
    """
    # 1. Create project
    proj = _railway(
        """mutation projectCreate($input: ProjectCreateInput!) {
             projectCreate(input: $input) { id }
           }""",
        {"input": {"name": f"demo-{slug}"}},
    )
    project_id = proj["projectCreate"]["id"]

    # 2. Get the default environment ID ("production")
    env_data = _railway(
        """query project($id: String!) {
             project(id: $id) {
               environments { edges { node { id name } } }
             }
           }""",
        {"id": project_id},
    )
    environment_id = env_data["project"]["environments"]["edges"][0]["node"]["id"]

    # 3. Create service linked to GitHub repo
    svc = _railway(
        """mutation serviceCreate($input: ServiceCreateInput!) {
             serviceCreate(input: $input) { id }
           }""",
        {
            "input": {
                "projectId": project_id,
                "name": f"demo-{slug}",
                "source": {"repo": github_repo},
            }
        },
    )
    service_id = svc["serviceCreate"]["id"]

    return project_id, environment_id, service_id


# ---------------------------------------------------------------------------
# Step 3.5: Railway — inject environment variables
# ---------------------------------------------------------------------------

def inject_railway_variables(project_id: str, environment_id: str, service_id: str, extra_tokens: set = None) -> None:
    """Push the API keys to the newly created Railway service."""
    variables = {}
    
    # Use dedicated DEMO key if available, otherwise fallback to the builder key
    demo_anthropic_key = os.environ.get("DEMO_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if demo_anthropic_key:
        variables["ANTHROPIC_API_KEY"] = demo_anthropic_key
        
    # Inject the specific model to use for the deployed demo (default to cheaper Haiku)
    variables["ANTHROPIC_MODEL"] = os.environ.get("DEMO_ANTHROPIC_MODEL", "claude-3-haiku-20240307")
        
    # Pass along OpenAI key if present
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        variables["OPENAI_API_KEY"] = openai_key
            
    # Load demo.env if it exists and fetch requested skill tokens
    if extra_tokens:
        demo_env_path = Path(__file__).parent / "demo.env"
        demo_env_vars = {}
        if demo_env_path.exists():
            try:
                from dotenv import dotenv_values
                demo_env_vars = dotenv_values(demo_env_path)
            except ImportError:
                pass
        
        for t in extra_tokens:
            if t in demo_env_vars:
                variables[t] = demo_env_vars[t]
            elif t in os.environ:
                variables[t] = os.environ[t]

    if not variables:
        return
        
    _railway(
        """mutation variableCollectionUpsert($input: VariableCollectionUpsertInput!) {
             variableCollectionUpsert(input: $input)
           }""",
        {
            "input": {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": service_id,
                "variables": variables
            }
        },
    )


# ---------------------------------------------------------------------------
# Step 4: Railway — trigger deploy
# ---------------------------------------------------------------------------

def trigger_railway_deploy(service_id: str, environment_id: str) -> None:
    """Trigger a Railway deployment for the given service."""
    _railway(
        """mutation serviceInstanceDeploy($serviceId: String!, $environmentId: String!) {
             serviceInstanceDeploy(serviceId: $serviceId, environmentId: $environmentId)
           }""",
        {"serviceId": service_id, "environmentId": environment_id},
    )


# ---------------------------------------------------------------------------
# Step 5: Railway — create domain
# ---------------------------------------------------------------------------

def create_railway_domain(service_id: str, environment_id: str) -> str:
    """Create a Railway-generated domain. Returns the full https:// URL."""
    result = _railway(
        """mutation serviceDomainCreate($input: ServiceDomainCreateInput!) {
             serviceDomainCreate(input: $input) { domain }
           }""",
        {"input": {"serviceId": service_id, "environmentId": environment_id}},
    )
    domain = result["serviceDomainCreate"]["domain"]
    return f"https://{domain}"


# ---------------------------------------------------------------------------
# Step 6: Railway — poll until deployment succeeds
# ---------------------------------------------------------------------------

DEPLOY_TERMINAL_STATES = {"SUCCESS", "FAILED", "CRASHED", "REMOVED"}

def wait_for_deploy(project_id: str, service_id: str, timeout: int = 300) -> None:
    """
    Poll Railway deployments every 10 s until SUCCESS or a terminal failure.
    Raises RuntimeError on failure, TimeoutError if timeout exceeded.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = _railway(
            """query deployments($input: DeploymentListInput!) {
                 deployments(input: $input, first: 1) {
                   edges { node { id status } }
                 }
               }""",
            {"input": {"projectId": project_id, "serviceId": service_id}},
        )
        edges = result["deployments"]["edges"]
        if edges:
            status = edges[0]["node"]["status"]
            if status == "SUCCESS":
                return
            if status in DEPLOY_TERMINAL_STATES:
                raise RuntimeError(f"Railway deployment ended with status: {status}")
        time.sleep(10)

    raise TimeoutError(
        f"Railway deployment did not complete within {timeout}s. "
        "Check the Railway dashboard for details."
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def deploy_demo(demo_output: str, slug: str, classifier: dict = None,
                design_spec: dict = None, files: dict = None) -> DeployResult:
    """
    Full deploy pipeline:
      1. Parse demo builder output → files (or use pre-parsed files)
      2. Validate + inject skills
      3. Create GitHub repo + push files
      4. Create Railway project + service
      5. Trigger deploy + create domain
      6. Wait for SUCCESS
      7. Health check
      8. Return DeployResult

    Args:
        demo_output: Raw string returned by run_build()
        slug:        URL-safe customer slug
        classifier:  Optional understand output dict
        design_spec: Optional design output dict (for skill injection)
        files:       Optional pre-parsed files dict (skips parse_demo_files)

    Returns:
        DeployResult with all deploy metadata
    """
    # Railway project names have a 32 character limit
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")[:25].strip("-")

    # Step 0 — parse files (if not pre-parsed)
    if files is None:
        files = parse_demo_files(demo_output)

    # Step 0b — validate before pushing (raises ValidationError on hard failures)
    warnings = validate_demo_files(files)
    for w in warnings:
        print(f"  ⚠ {w}")

    # Inject skills into files
    required_skills = []
    tokens_to_inject = set()
    if design_spec:
        required_skills = design_spec.get("demo_spec", {}).get("required_skills", [])

    for skill in required_skills:
        skill_dir = Path(__file__).parent / "skills" / skill
        if not skill_dir.exists():
            continue

        adapter_path = skill_dir / "adapter.py"
        manifest_path = skill_dir / "manifest.json"

        if adapter_path.exists():
            files[f"skills/{skill}.py"] = adapter_path.read_text()
            files["skills/__init__.py"] = ""

        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                packages = manifest.get("packages", [])
                if packages and "requirements.txt" in files:
                    files["requirements.txt"] += "\n" + "\n".join(packages)
                for t in manifest.get("tokens", []):
                    tokens_to_inject.add(t)
            except Exception:
                pass

    # Step 1–2 — GitHub
    full_name, _ = create_github_repo(slug)
    push_files_to_github(full_name, files)

    # Step 3 — Railway project + service
    project_id, environment_id, service_id = create_railway_project(slug, full_name)

    # Step 3.5 — Inject environment variables (API Keys)
    inject_railway_variables(project_id, environment_id, service_id, extra_tokens=tokens_to_inject)

    # Step 4 — trigger deploy + provision domain
    trigger_railway_deploy(service_id, environment_id)
    live_url = create_railway_domain(service_id, environment_id)

    # Step 5 — wait for live
    wait_for_deploy(project_id, service_id)

    # Step 6 — health check
    verified = health_check(live_url)

    return DeployResult(
        url=live_url,
        github_repo=full_name,
        project_id=project_id,
        service_id=service_id,
        environment_id=environment_id,
        verified=verified,
        error=None if verified else f"Health check failed for {live_url}",
    )
