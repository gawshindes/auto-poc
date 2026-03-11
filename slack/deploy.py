import os
import re
import json
import time
import requests

GITHUB_API = "https://api.github.com"
RAILWAY_API = "https://backboard.railway.app/graphql/v2"


class ValidationError(Exception):
    pass


# Packages that will break Railway builds on Python 3.13
_BANNED_PACKAGES = ["playwright", "greenlet"]
_BANNED_PYDANTIC = re.compile(r"pydantic\s*[=<>!]=?\s*2\.[0-6]\b|pydantic\s*[=<>!]=?\s*1\.")


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

    # 3. $PORT usage (soft warning)
    main_content = files["main.py"]
    if "PORT" not in main_content:
        warnings.append("main.py does not reference $PORT — app may not bind correctly on Railway")

    # 4. Python syntax check (in-memory, works anywhere)
    try:
        compile(main_content, "main.py", "exec")
    except SyntaxError as e:
        raise ValidationError(f"Syntax error in main.py: {e}")

    return warnings


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
# Registry writer
# ---------------------------------------------------------------------------

def register_deployment(slug: str, live_url: str, classifier: dict) -> None:
    """
    Append a new demo_tool entry to the solutions registry after a successful deploy.

    Args:
        slug:       URL-safe customer slug, e.g. "renocomputerfix"
        live_url:   Railway URL, e.g. "https://demo-renocomputerfix.up.railway.app"
        classifier: Output dict from run_classifier() — used for metadata
    """
    from storage import get_backend
    backend = get_backend()
    registry = backend.get_solutions()

    # Auto-increment ID
    existing_ids = [s['id'] for s in registry['solutions']]
    next_num = max((int(i.split('_')[1]) for i in existing_ids), default=0) + 1
    new_id = f"sol_{next_num:03d}"

    customer = classifier.get('customer', {})
    company = customer.get('company', slug)
    demo_type = classifier.get('demo_type', 'custom')
    core_problem = classifier.get('core_problem', '')
    proposed_solution = classifier.get('proposed_solution', '')

    new_entry = {
        'id': new_id,
        'name': f"{company} — {demo_type.replace('_', ' ').title()} Demo",
        'description': proposed_solution or core_problem or f"Demo built for {company}",
        'built_for': company,
        'demo_type': demo_type,
        'what_to_customize': classifier.get('constraints', []),
        'reuse_effort': 'low',
        'hosting': 'Railway',
        'stack': 'Auto-deployed via demo_tool',
        'source': 'demo_tool',
        'status': 'built',
        'demo_url': live_url,
    }

    backend.append_solution(new_entry, registry)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def deploy_demo(demo_output: str, slug: str, classifier: dict = None) -> str:
    """
    Full deploy pipeline:
      1. Parse demo builder output → files
      2. Create GitHub repo + push files
      3. Create Railway project + service linked to repo
      4. Trigger deploy + create domain
      5. Wait for SUCCESS
      6. Register deployment in solutions.json
      7. Return live URL

    Args:
        demo_output: Raw string returned by run_demo_builder()
        slug:        URL-safe customer slug, e.g. "renocomputerfix"
        classifier:  Optional classifier output dict — used to enrich the registry entry

    Returns:
        Live URL string, e.g. "https://demo-renocomputerfix.up.railway.app"
    """
    # Step 0 — parse files
    files = parse_demo_files(demo_output)

    # Step 0b — validate before pushing (raises ValidationError on hard failures)
    warnings = validate_demo_files(files)
    for w in warnings:
        print(f"  ⚠ {w}")

    # Step 1–2 — GitHub
    full_name, _ = create_github_repo(slug)
    push_files_to_github(full_name, files)

    # Step 3 — Railway project + service
    project_id, environment_id, service_id = create_railway_project(slug, full_name)

    # Step 4 — trigger deploy + provision domain in parallel order
    trigger_railway_deploy(service_id, environment_id)
    live_url = create_railway_domain(service_id, environment_id)

    # Step 5 — wait for live
    wait_for_deploy(project_id, service_id)

    # Step 6 — write to solutions registry
    register_deployment(slug, live_url, classifier or {})

    return live_url
