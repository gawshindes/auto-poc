#!/usr/bin/env python3
"""
Cleanup script — delete GitHub repos and/or Railway projects matching a slug pattern.

Usage:
    python3 cleanup_deploy.py demo-viewplus          # dry-run, show what would be deleted
    python3 cleanup_deploy.py viewplus --github      # delete GitHub repos matching *viewplus*
    python3 cleanup_deploy.py viewplus --railway     # delete Railway projects matching *viewplus*
    python3 cleanup_deploy.py viewplus --github --railway  # both
    python3 cleanup_deploy.py demo-                  # wipe ALL demo-* repos/projects
    python3 cleanup_deploy.py demo- --github --railway --confirm

Flags:
    --github    Target GitHub repos
    --railway   Target Railway projects
    --confirm   Actually delete (default is dry-run)
"""

import os
import sys
import argparse
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GITHUB_API = "https://api.github.com"
RAILWAY_API = "https://backboard.railway.app/graphql/v2"

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _gh_headers():
    token = os.environ.get("GITHUB_TOKEN_CLEANUP")
    if not token:
        print(f"{RED}✗ GITHUB_TOKEN_CLEANUP not set{RESET}", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _rw_headers():
    token = os.environ.get("RAILWAY_TOKEN")
    if not token:
        print(f"{RED}✗ RAILWAY_TOKEN not set{RESET}", file=sys.stderr)
        sys.exit(1)
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _railway(query, variables):
    resp = requests.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers=_rw_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Railway API error: {data['errors']}")
    return data["data"]


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def list_github_repos(pattern: str) -> list:
    """List org repos whose names contain pattern (case-insensitive)."""
    org = os.environ.get("GITHUB_ORG")
    headers = _gh_headers()
    repos = []
    page = 1
    while True:
        if org:
            url = f"{GITHUB_API}/orgs/{org}/repos"
        else:
            url = f"{GITHUB_API}/user/repos"
        resp = requests.get(url, headers=headers, params={"per_page": 100, "page": page}, timeout=20)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for r in batch:
            if pattern.lower() in r["full_name"].lower():
                repos.append(r["full_name"])
        page += 1
    return repos


def delete_github_repo(full_name: str) -> None:
    resp = requests.delete(f"{GITHUB_API}/repos/{full_name}", headers=_gh_headers(), timeout=20)
    if resp.status_code == 204:
        print(f"  {GREEN}✓ Deleted GitHub repo:{RESET} {full_name}")
    else:
        print(f"  {RED}✗ Failed to delete {full_name}: {resp.status_code} {resp.text}{RESET}")


# ---------------------------------------------------------------------------
# Railway
# ---------------------------------------------------------------------------

def list_railway_projects(pattern: str) -> list:
    """List Railway projects whose names contain pattern (case-insensitive)."""
    data = _railway(
        """query { projects { edges { node { id name } } } }""",
        {},
    )
    matched = []
    for edge in data["projects"]["edges"]:
        node = edge["node"]
        if pattern.lower() in node["name"].lower():
            matched.append((node["id"], node["name"]))
    return matched


def delete_railway_project(project_id: str, project_name: str) -> None:
    _railway(
        """mutation projectDelete($id: String!) { projectDelete(id: $id) }""",
        {"id": project_id},
    )
    print(f"  {GREEN}✓ Deleted Railway project:{RESET} {project_name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Delete GitHub repos and Railway projects matching a slug pattern.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pattern", help="Substring to match against repo/project names (e.g. 'viewplus' or 'demo-')")
    parser.add_argument("--github",  action="store_true", help="Delete matching GitHub repos")
    parser.add_argument("--railway", action="store_true", help="Delete matching Railway projects")
    parser.add_argument("--confirm", action="store_true", help="Actually delete (default is dry-run)")
    args = parser.parse_args()

    if not args.github and not args.railway:
        print(f"{YELLOW}⚠  No target specified — add --github and/or --railway{RESET}")
        parser.print_help()
        sys.exit(0)

    dry = not args.confirm
    if dry:
        print(f"{YELLOW}DRY RUN — pass --confirm to actually delete{RESET}\n")

    # ── GitHub ───────────────────────────────────────────────────────────
    if args.github:
        print(f"{BOLD}GitHub repos matching '{args.pattern}':{RESET}")
        repos = list_github_repos(args.pattern)
        if not repos:
            print(f"  {DIM}None found{RESET}")
        else:
            for r in repos:
                if dry:
                    print(f"  {DIM}would delete:{RESET} {r}")
                else:
                    delete_github_repo(r)
        print()

    # ── Railway ──────────────────────────────────────────────────────────
    if args.railway:
        print(f"{BOLD}Railway projects matching '{args.pattern}':{RESET}")
        projects = list_railway_projects(args.pattern)
        if not projects:
            print(f"  {DIM}None found{RESET}")
        else:
            for pid, pname in projects:
                if dry:
                    print(f"  {DIM}would delete:{RESET} {pname}  ({pid})")
                else:
                    try:
                        delete_railway_project(pid, pname)
                    except Exception as e:
                        print(f"  {RED}✗ Failed to delete {pname}: {e}{RESET}")
        print()

    if dry and (repos if args.github else []) + (projects if args.railway else []):
        print(f"{YELLOW}Re-run with --confirm to execute deletions.{RESET}")


if __name__ == "__main__":
    main()
