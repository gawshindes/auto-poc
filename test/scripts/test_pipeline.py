#!/usr/bin/env python3
"""
CLI test runner for the demo creation pipeline (4-stage).
Runs all stages against a transcript file — no Slack required.

Usage:
    python test/scripts/test_pipeline.py                                                   # built-in sample transcript
    python test/scripts/test_pipeline.py test/data/transcripts/renocomputerfix.txt        # plain text
    python test/scripts/test_pipeline.py test/data/transcripts/transcript.pdf             # PDF (Spiky export)
    python test/scripts/test_pipeline.py transcript.txt --deploy                          # also trigger Railway deploy
    python test/scripts/test_pipeline.py transcript.txt --stage 1                         # run only stage 1
"""

import os
import sys
import json
import time
import argparse
import textwrap
from datetime import datetime
from pathlib import Path

# Load .env before anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional if env vars are set directly

# Project root is 3 levels up from test/scripts/test_pipeline.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR  = PROJECT_ROOT / "test" / "data" / "outputs"
TRANSCRIPTS_DIR = PROJECT_ROOT / "test" / "data" / "transcripts"

# Import shared pipeline module
sys.path.insert(0, str(PROJECT_ROOT))
from pipeline import (
    run_understand, run_design, run_build, run_guide,
    append_to_registry, read_transcript, PROMPTS,
)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"


def _die(msg):
    print(f"{RED}✗ {msg}{RESET}", file=sys.stderr)
    sys.exit(1)


def _header(text):
    print(f"\n{BOLD}{CYAN}{'─' * 60}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * 60}{RESET}")


def _ok(label, value=""):
    print(f"{GREEN}✓{RESET} {BOLD}{label}{RESET}" + (f"  {DIM}{value}{DIM}" if value else ""))


def _warn(label, value=""):
    print(f"{YELLOW}⚠{RESET}  {BOLD}{label}{RESET}" + (f"  {DIM}{value}{DIM}" if value else ""))


def _elapsed(start):
    return f"{time.time() - start:.1f}s"


def _preview(obj, max_chars=400):
    """Print a short preview of a dict or string."""
    text = json.dumps(obj, indent=2) if isinstance(obj, dict) else str(obj)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n{DIM}... ({len(text) - max_chars} chars truncated){RESET}"
    for line in text.splitlines():
        print(f"  {DIM}{line}{RESET}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test the demo creation pipeline locally without Slack.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python test/scripts/test_pipeline.py
              python test/scripts/test_pipeline.py test/data/transcripts/renocomputerfix.txt
              python test/scripts/test_pipeline.py transcript.txt --deploy
              python test/scripts/test_pipeline.py transcript.txt --stage 2
              python test/scripts/test_pipeline.py --redeploy latest
              python test/scripts/test_pipeline.py --rebuild-demo latest              # re-run only stage 3
              python test/scripts/test_pipeline.py --rebuild-demo latest --deploy    # rebuild + deploy
        """),
    )
    parser.add_argument(
        "transcript",
        nargs="?",
        default=str(TRANSCRIPTS_DIR / "renocomputerfix.txt"),
        help="Path to transcript file (default: test/data/transcripts/renocomputerfix.txt)",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="After stage 3, trigger full GitHub + Railway deploy",
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=[1, 2, 3, 4],
        default=4,
        help="Stop after this stage (default: 4 = run all)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON file path (default: test_output_<slug>_<ts>.json)",
    )
    parser.add_argument(
        "--redeploy",
        metavar="JSON_FILE",
        default=None,
        help="Skip all stages — deploy from an existing test output JSON file",
    )
    parser.add_argument(
        "--rebuild-demo",
        metavar="JSON_FILE",
        default=None,
        help="Load stages 1-2 from saved JSON, re-run only stage 3 (optionally with --deploy)",
    )
    args = parser.parse_args()

    # ── Redeploy shortcut — no Claude calls ───────────────────────────────
    if args.redeploy:
        import re as _re
        sys.path.insert(0, str(PROJECT_ROOT / "slack"))
        from deploy import deploy_demo

        redeploy_path = args.redeploy
        if redeploy_path == "latest":
            candidates = sorted(OUTPUTS_DIR.glob("test_output_*.json"), key=lambda p: p.stat().st_mtime)
            if not candidates:
                _die(f"No test_output_*.json files found in {OUTPUTS_DIR}.")
            redeploy_path = str(candidates[-1])
            _ok("Using latest", redeploy_path)
        saved = json.loads(Path(redeploy_path).read_text())
        demo = saved.get("stage_3_demo")
        understand = saved.get("stage_1_understand", {})
        customer = understand.get("customer", {})

        if not demo:
            _die(f"No stage_3_demo found in {args.redeploy}. Run with --stage 3 first.")

        _header(f"Redeploy from {args.redeploy}")
        slug = _re.sub(r"[^a-z0-9-]", "-", customer.get("company", "demo").lower())
        _ok("Slug", slug)
        t = time.time()
        try:
            live_url = deploy_demo(demo, slug, classifier=understand)
            _ok("Deployed", _elapsed(t))
            print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
        except Exception as e:
            _warn("Deploy failed", str(e))
        return

    # ── Rebuild demo — load stages 1-2 from JSON, re-run only stage 3 ────
    if args.rebuild_demo:
        import re as _re
        rebuild_path = args.rebuild_demo
        if rebuild_path == "latest":
            candidates = sorted(OUTPUTS_DIR.glob("test_output_*.json"), key=lambda p: p.stat().st_mtime)
            if not candidates:
                _die(f"No test_output_*.json files found in {OUTPUTS_DIR}.")
            rebuild_path = str(candidates[-1])
            _ok("Using latest", rebuild_path)

        saved = json.loads(Path(rebuild_path).read_text())
        understand = saved.get("stage_1_understand", {})
        design = saved.get("stage_2_design", {})
        customer = understand.get("customer", {})

        if not understand or not design:
            _die(f"Missing stages 1-2 in {rebuild_path}. Run full pipeline first.")

        can_build = understand.get("can_build_immediately", False)

        # Prompt for customer inputs
        customer_inputs = ""
        ask_items = understand.get("dependencies", {}).get("ask_customer", [])
        if ask_items:
            _header("Customer Inputs")
            print(f"  {DIM}Enter values the customer needs to provide. Press Enter to skip any item.{RESET}\n")
            answers = []
            for item in ask_items:
                dep = item.get("dependency", "?")
                hint = item.get("how_to_get", "")
                urgency = item.get("urgency", "")
                tag = f"{RED}[must have]{RESET}" if urgency.startswith("needed before build") else f"{DIM}[nice to have]{RESET}"
                print(f"  {BOLD}•{RESET} {dep} {tag}")
                if hint:
                    print(f"    {DIM}Hint: {hint}{RESET}")
                try:
                    val = input(f"    Value (Enter to skip): ").strip()
                except (EOFError, KeyboardInterrupt):
                    val = ""
                if val:
                    answers.append(f"{dep}: {val}")
                print()
            if answers:
                customer_inputs = "\n".join(answers)
                _ok("Customer inputs collected", f"{len(answers)} item(s)")
            else:
                _ok("No inputs provided", "building with mocks")

        if not can_build and not customer_inputs:
            _warn("Skipped", "can_build_immediately=False and no customer inputs provided")
            return

        _header("Stage 3 — Build (rebuild)")
        t = time.time()
        demo = run_build(design, customer_inputs=customer_inputs)
        _ok("Completed", _elapsed(t))

        # Update saved JSON with new demo
        saved["stage_3_demo"] = demo
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _re.sub(r"[^a-z0-9_]", "_", customer.get("company", "run").lower())[:20]
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUTS_DIR / f"test_output_{slug}_{ts}.json"
        out_path.write_text(json.dumps(saved, indent=2))
        _ok("Output saved", str(out_path))

        lines = demo.splitlines()
        for line in lines[:60]:
            print(f"  {DIM}{line}{RESET}")
        if len(lines) > 60:
            print(f"  {DIM}... ({len(lines) - 60} more lines — see {out_path}){RESET}")

        # Validate before deploying
        sys.path.insert(0, str(PROJECT_ROOT / "slack"))
        from deploy import parse_demo_files, validate_demo_files, ValidationError
        _header("Pre-deploy Validation")
        _files = parse_demo_files(demo)
        _ok("Files parsed", ", ".join(_files.keys()))
        try:
            _warnings = validate_demo_files(_files)
            _ok("Validation passed")
            for w in _warnings:
                _warn(w)
        except ValidationError as ve:
            print(f"\n{RED}✗ Validation failed:{RESET}\n  {ve}")
            return

        # Reuse previously deployed URL if available and not redeploying
        live_url = saved.get("deploy_url", "")
        if args.deploy:
            _header("Deploy — GitHub + Railway")
            from deploy import deploy_demo
            slug = _re.sub(r"[^a-z0-9-]", "-", customer.get("company", "demo").lower())
            t = time.time()
            try:
                live_url = deploy_demo(demo, slug, classifier=understand)
                saved["deploy_url"] = live_url
                _ok("Deployed", _elapsed(t))
                print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
            except Exception as e:
                _warn("Deploy failed", str(e))

        # Stage 4 — Guide
        _header("Stage 4 — Guide")
        if live_url and not args.deploy:
            _ok("Using existing deploy URL", live_url)
        t = time.time()
        guide = run_guide(understand, demo, live_url=live_url)
        _ok("Completed", _elapsed(t))
        print()
        for line in guide.splitlines():
            print(f"  {line}")
        print()
        append_to_registry(design, understand, deploy_url=live_url or None)
        return

    # Verify project structure is intact
    if not (PROJECT_ROOT / "prompts").is_dir() or not (PROJECT_ROOT / "registry").is_dir():
        _die(f"Could not find prompts/ or registry/ under {PROJECT_ROOT}")

    # Load transcript
    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        _die(f"Transcript file not found: {transcript_path}")
    try:
        transcript = read_transcript(transcript_path)
    except (ValueError, RuntimeError) as e:
        _die(str(e))

    print(f"\n{BOLD}Demo Creation Pipeline — Local Test Runner{RESET}")
    print(f"{DIM}Transcript: {transcript_path}  ({len(transcript)} chars){RESET}")
    print(f"{DIM}Running stages 1–{args.stage}{RESET}")

    results = {}
    run_start = time.time()

    # ── Stage 1: Understand ──────────────────────────────────────────────
    _header("Stage 1 — Understand")
    t = time.time()
    understand = run_understand(transcript)
    results["stage_1_understand"] = understand
    _ok("Completed", _elapsed(t))

    decision = understand.get("demo_decision", "?")
    customer = understand.get("customer", {})
    _ok("Customer", f"{customer.get('name')} @ {customer.get('company')}")
    _ok("Demo decision", decision)
    if decision == "YES":
        _ok("Demo type", understand.get("demo_type", "?"))
        _ok("Demo approach", understand.get("demo_approach", "?"))
        _ok("Wow moment", understand.get("wow_moment", "?"))
        print()
        print(f"  {BOLD}Problem understood:{RESET}")
        print(f"  {DIM}{understand.get('core_problem', '—')}{RESET}")
        print()
        print(f"  {BOLD}Proposed solution:{RESET}")
        print(f"  {DIM}{understand.get('proposed_solution', '—')}{RESET}")
        systems = understand.get("systems_mentioned", [])
        if systems:
            print()
            print(f"  {BOLD}Systems mentioned:{RESET}  {DIM}{', '.join(systems)}{RESET}")
        deps = understand.get("dependencies", {})
        ask_items = deps.get("ask_customer", [])
        resolved = deps.get("resolved_by_knowledge", [])
        can_build = understand.get("can_build_immediately", False)
        _ok("Can build immediately", str(can_build))
        if resolved:
            _ok("Self-resolved items", str(len(resolved)))
        if ask_items:
            _warn("Customer input needed", f"{len(ask_items)} item(s)")
    else:
        _warn("Pipeline exit", understand.get("reason", ""))
        _save_results(results, args, customer)
        print(f"\n{YELLOW}Stopped: understand returned demo_decision=NO{RESET}\n")
        return

    if args.stage < 2:
        _save_results(results, args, customer)
        return

    # ── Stage 2: Design ──────────────────────────────────────────────────
    _header("Stage 2 — Design")
    t = time.time()

    # Merge resolved knowledge into customer inputs for design
    customer_inputs = ""
    if resolved:
        customer_inputs = "\n\n".join(
            f"[Auto-resolved] {r['dependency']}:\n{r['answer']}"
            for r in resolved
        )

    design = run_design(understand, customer_inputs)
    results["stage_2_design"] = design
    _ok("Completed", _elapsed(t))

    # Skip build if ALL components exist
    _component_matches = design.get("component_matches", [])
    if _component_matches and all(
        m.get("action", "build_new").startswith("exists")
        for m in _component_matches
    ):
        sdr_note = design.get("build_instruction", {}).get("sdr_note", "")
        _warn("All components exist — Build skipped", sdr_note or "No new build needed.")
        _save_results(results, args, customer)
        return

    build = design.get("build_instruction", {})
    _ok("Approach", build.get("approach", "?"))
    _ok("Estimated effort", build.get("estimated_effort", "?"))

    gaps = design.get("discovery_gaps", [])
    if gaps:
        print(f"\n  {BOLD}Discovery gaps:{RESET}")
        for g in gaps[:3]:
            print(f"  {YELLOW}•{RESET} {g.get('gap')}: {DIM}{g.get('suggested_question')}{RESET}")

    sdr_msg = design.get("sdr_message", {})
    if sdr_msg.get("needed"):
        print(f"\n  {BOLD}SDR Email Draft:{RESET}")
        for line in sdr_msg.get("email_draft", "").splitlines():
            print(f"  {DIM}{line}{RESET}")

    if args.stage < 3:
        _save_results(results, args, customer)
        return

    # ── Customer input prompts (before Stage 3) ───────────────────────────
    if ask_items:
        _header("Customer Inputs")
        print(f"  {DIM}Enter values the customer needs to provide. Press Enter to skip any item.{RESET}\n")
        answers = []
        for item in ask_items:
            dep = item.get("dependency", "?")
            hint = item.get("how_to_get", "")
            urgency = item.get("urgency", "")
            tag = f"{RED}[must have]{RESET}" if urgency.startswith("needed before build") else f"{DIM}[nice to have]{RESET}"
            print(f"  {BOLD}•{RESET} {dep} {tag}")
            if hint:
                print(f"    {DIM}Hint: {hint}{RESET}")
            try:
                val = input(f"    Value (Enter to skip): ").strip()
            except (EOFError, KeyboardInterrupt):
                val = ""
            if val:
                answers.append(f"{dep}: {val}")
            print()
        if answers:
            extra = "\n".join(answers)
            customer_inputs = (customer_inputs + "\n\n" + extra).strip() if customer_inputs else extra
            _ok("Customer inputs collected", f"{len(answers)} item(s)")
        else:
            _ok("No inputs provided", "building with mocks")

    # ── Stage 3: Build ─────────────────────────────────────────────────
    if not can_build and not customer_inputs:
        _header("Stage 3 — Build")
        _warn("Skipped", "can_build_immediately=False and no customer inputs provided")
        results["stage_3_demo"] = None
        _save_results(results, args, customer)
        return

    _header("Stage 3 — Build")
    t = time.time()
    demo = run_build(design, customer_inputs=customer_inputs)
    results["stage_3_demo"] = demo
    _ok("Completed", _elapsed(t))
    print()
    lines = demo.splitlines()
    for line in lines[:80]:
        print(f"  {DIM}{line}{RESET}")
    if len(lines) > 80:
        print(f"  {DIM}... ({len(lines) - 80} more lines — see output file){RESET}")

    # ── Pre-deploy validation ─────────────────────────────────────────────
    _header("Pre-deploy Validation")
    sys.path.insert(0, str(PROJECT_ROOT / "slack"))
    from deploy import parse_demo_files, validate_demo_files, ValidationError
    _files = parse_demo_files(demo)
    _ok("Files parsed", ", ".join(_files.keys()))
    try:
        _warnings = validate_demo_files(_files)
        _ok("Validation passed")
        for w in _warnings:
            _warn(w)
    except ValidationError as ve:
        print(f"\n{RED}✗ Validation failed — fix before deploying:{RESET}")
        print(f"  {str(ve)}")
        results["validation_error"] = str(ve)
        _save_results(results, args, customer)
        return

    # ── Optional: Deploy ──────────────────────────────────────────────────
    live_url = ""
    if args.deploy:
        _header("Deploy — GitHub + Railway")
        try:
            import re as _re
            from deploy import deploy_demo

            slug = _re.sub(r"[^a-z0-9-]", "-",
                           customer.get("company", "demo").lower())
            t = time.time()
            live_url = deploy_demo(demo, slug, classifier=understand)
            results["deploy_url"] = live_url
            _ok("Deployed", _elapsed(t))
            print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
        except Exception as e:
            _warn("Deploy failed", str(e))
            results["deploy_error"] = str(e)

    # ── Stage 4: Guide ───────────────────────────────────────────────────
    _header("Stage 4 — Guide")
    t = time.time()
    guide = run_guide(understand, demo, live_url=live_url)
    results["stage_4_guide"] = guide
    _ok("Completed", _elapsed(t))
    print()
    for line in guide.splitlines():
        print(f"  {line}")
    print()

    # ── Registry update ───────────────────────────────────────────────────
    new_id = append_to_registry(design, understand, deploy_url=live_url or None)
    if new_id:
        _ok("Registry updated", new_id)
    else:
        _ok("Registry", "Skipped (duplicate or add_to_registry_after_build=false)")

    # ── Summary ───────────────────────────────────────────────────────────
    _header("Summary")
    _ok("Total time", _elapsed(run_start))
    _ok("Stages run", str(args.stage))
    out_path = _save_results(results, args, customer)
    _ok("Output saved", out_path)
    print()


def _save_results(results, args, customer):
    import re as _re
    slug = customer.get("company", "run") if isinstance(customer, dict) else "run"
    slug = _re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")[:20]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUTPUTS_DIR / f"test_output_{slug}_{ts}.json"
    out_path.write_text(json.dumps(results, indent=2))
    return str(out_path)




if __name__ == "__main__":
    main()
