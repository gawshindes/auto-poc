#!/usr/bin/env python3
"""
CLI test runner for the demo creation pipeline.
Runs all 5 stages against a transcript file — no Slack required.

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
    run_classifier, run_dependency_checker, run_solutions_matcher,
    run_sdr_messenger, run_demo_builder, run_demo_guide,
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
              python test/scripts/test_pipeline.py transcript.txt --stage 3
              python test/scripts/test_pipeline.py --redeploy latest
              python test/scripts/test_pipeline.py --rebuild-demo latest              # re-run only stage 5
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
        help="After stage 5, trigger full GitHub + Railway deploy",
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=[1, 2, 3, 4, 5],
        default=5,
        help="Stop after this stage (default: 5 = run all)",
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
        help="Load stages 1-4 from saved JSON, re-run only stage 5 (optionally with --deploy)",
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
        demo = saved.get("stage_5_demo")
        classifier = saved.get("stage_1_classifier", {})
        customer = classifier.get("customer", {})

        if not demo:
            _die(f"No stage_5_demo found in {args.redeploy}. Run with --stage 5 first.")

        _header(f"Redeploy from {args.redeploy}")
        slug = _re.sub(r"[^a-z0-9-]", "-", customer.get("company", "demo").lower())
        _ok("Slug", slug)
        t = time.time()
        try:
            live_url = deploy_demo(demo, slug, classifier=classifier)
            _ok("Deployed", _elapsed(t))
            print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
        except Exception as e:
            _warn("Deploy failed", str(e))
        return

    # ── Rebuild demo — load stages 1-4 from JSON, re-run only stage 5 ────
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
        classifier = saved.get("stage_1_classifier", {})
        dependency = saved.get("stage_2_dependency", {})
        matcher = saved.get("stage_3_matcher", {})
        customer = classifier.get("customer", {})

        if not classifier or not dependency or not matcher:
            _die(f"Missing stages 1-3 in {rebuild_path}. Run full pipeline first.")

        # Mirror the can_build override
        if any(
            item.get("urgency", "").startswith("needed before build")
            for item in dependency.get("ask_customer", [])
        ):
            dependency["can_build_immediately"] = False
        can_build = dependency.get("can_build_immediately", False)

        # Prompt for customer inputs
        customer_inputs = ""
        ask_items = dependency.get("ask_customer", [])
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
            _warn("Skipped", "can_build_immediately=False and no customer inputs — pass eBay URL above")
            return

        _header("Stage 5 — Demo Builder (rebuild)")
        t = time.time()
        demo = run_demo_builder(classifier, dependency, matcher,
                                customer_inputs=customer_inputs)
        _ok("Completed", _elapsed(t))

        # Update saved JSON with new demo
        saved["stage_5_demo"] = demo
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
                live_url = deploy_demo(demo, slug, classifier=classifier)
                saved["deploy_url"] = live_url
                _ok("Deployed", _elapsed(t))
                print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
            except Exception as e:
                _warn("Deploy failed", str(e))

        # Demo Guide
        _header("Stage 6 — Demo Guide")
        if live_url and not args.deploy:
            _ok("Using existing deploy URL", live_url)
        t = time.time()
        guide = run_demo_guide(classifier, demo, live_url=live_url)
        _ok("Completed", _elapsed(t))
        print()
        for line in guide.splitlines():
            print(f"  {line}")
        print()
        append_to_registry(matcher, classifier, deploy_url=live_url or None)
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

    # ── Stage 1: Classifier ──────────────────────────────────────────────
    _header("Stage 1 — Classifier")
    t = time.time()
    classifier = run_classifier(transcript)
    results["stage_1_classifier"] = classifier
    _ok("Completed", _elapsed(t))

    decision = classifier.get("demo_decision", "?")
    customer = classifier.get("customer", {})
    _ok("Customer", f"{customer.get('name')} @ {customer.get('company')}")
    _ok("Demo decision", decision)
    if decision == "YES":
        _ok("Demo type", classifier.get("demo_type", "?"))
        _ok("Wow moment", classifier.get("wow_moment", "?"))
        print()
        print(f"  {BOLD}Problem understood:{RESET}")
        print(f"  {DIM}{classifier.get('core_problem', '—')}{RESET}")
        print()
        print(f"  {BOLD}Proposed solution:{RESET}")
        print(f"  {DIM}{classifier.get('proposed_solution', '—')}{RESET}")
        systems = classifier.get("systems_mentioned", [])
        if systems:
            print()
            print(f"  {BOLD}Systems mentioned:{RESET}  {DIM}{', '.join(systems)}{RESET}")
        constraints = classifier.get("constraints", [])
        if constraints:
            print()
            print(f"  {BOLD}Constraints:{RESET}")
            for c in constraints:
                print(f"  {DIM}• {c}{RESET}")
    else:
        _warn("Pipeline exit", classifier.get("reason", ""))
        _save_results(results, args, customer)
        print(f"\n{YELLOW}Stopped: classifier returned demo_decision=NO{RESET}\n")
        return

    if args.stage < 2:
        _save_results(results, args, customer)
        return

    # ── Stage 2: Dependency Checker ──────────────────────────────────────
    _header("Stage 2 — Dependency Checker")
    t = time.time()
    dependency = run_dependency_checker(classifier)
    results["stage_2_dependency"] = dependency
    _ok("Completed", _elapsed(t))

    # Mirror bot.py: any "needed before build" item overrides can_build_immediately
    if any(
        item.get("urgency", "").startswith("needed before build")
        for item in dependency.get("ask_customer", [])
    ):
        dependency["can_build_immediately"] = False

    can_build = dependency.get("can_build_immediately", False)
    ask_customer = dependency.get("ask_customer", False)
    _ok("Can build immediately", str(can_build))
    if ask_customer:
        _warn("Customer input needed", "SDR messenger stage will run")
    _preview(dependency)

    if args.stage < 3:
        _save_results(results, args, customer)
        return

    # ── Stage 3: Solutions Matcher ────────────────────────────────────────
    _header("Stage 3 — Solutions Matcher")
    t = time.time()
    matcher = run_solutions_matcher(classifier, dependency)
    results["stage_3_matcher"] = matcher

    # Skip builder if ALL components already exist in registry (Python decides, not LLM)
    _component_matches = matcher.get("component_matches", [])
    if _component_matches and all(
        m.get("action", "build_new").startswith("exists")
        for m in _component_matches
    ):
        sdr_note = matcher.get("build_instruction", {}).get("sdr_note", "")
        _warn("All components exist — Stage 5 skipped", sdr_note or "No new build needed.")
        _save_results(results, args, customer)
        return

    _ok("Completed", _elapsed(t))
    match = matcher.get("match_result", {})
    build = matcher.get("build_instruction", {})
    _ok("Match type", match.get("type", "?"))
    if match.get("matched_solution"):
        _ok("Matched solution", match["matched_solution"])
        source = build.get("source", "?")
        demo_url = build.get("demo_url")
        _ok("Source", source)
        if source == "demo_tool" and demo_url:
            _ok("Live URL (existing)", demo_url)
        elif source == "manual":
            _warn("No URL", "Solution was built manually — founder must share/record")
        if build.get("sdr_note"):
            _ok("SDR note", build["sdr_note"])
    _ok("Approach", build.get("approach", "?"))
    _ok("Estimated effort", build.get("estimated_effort", "?"))

    gaps = matcher.get("discovery_gaps", [])
    if gaps:
        print(f"\n  {BOLD}Discovery gaps:{RESET}")
        for g in gaps[:3]:
            print(f"  {YELLOW}•{RESET} {g.get('gap')}: {DIM}{g.get('suggested_question')}{RESET}")

    if args.stage < 4:
        _save_results(results, args, customer)
        return

    # ── Stage 4: SDR Messenger (only if customer input needed) ───────────
    messenger_output = ""
    if ask_customer:
        _header("Stage 4 — SDR Messenger")
        t = time.time()
        messenger_output = run_sdr_messenger(classifier, dependency, matcher)
        results["stage_4_messenger"] = messenger_output
        _ok("Completed", _elapsed(t))
        print()
        for line in messenger_output.splitlines():
            print(f"  {line}")
    else:
        _header("Stage 4 — SDR Messenger")
        _ok("Skipped", "No customer input needed — can build immediately")
        results["stage_4_messenger"] = None

    if args.stage < 5:
        _save_results(results, args, customer)
        return

    # ── Customer input prompts (before Stage 5) ───────────────────────────
    customer_inputs = ""
    ask_items = dependency.get("ask_customer", [])
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

    # ── Stage 5: Demo Builder ─────────────────────────────────────────────
    if not can_build and not customer_inputs:
        _header("Stage 5 — Demo Builder")
        _warn("Skipped", "can_build_immediately=False and no customer inputs provided")
        results["stage_5_demo"] = None
        _save_results(results, args, customer)
        return

    _header("Stage 5 — Demo Builder")
    t = time.time()
    demo = run_demo_builder(classifier, dependency, matcher,
                            customer_inputs=customer_inputs)
    results["stage_5_demo"] = demo
    _ok("Completed", _elapsed(t))
    print()
    # Print first 80 lines of demo output
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
            live_url = deploy_demo(demo, slug, classifier=classifier)
            results["deploy_url"] = live_url
            _ok("Deployed", _elapsed(t))
            print(f"\n  {GREEN}{BOLD}🚀  {live_url}{RESET}\n")
        except Exception as e:
            _warn("Deploy failed", str(e))
            results["deploy_error"] = str(e)

    # ── Stage 6: Demo Guide ───────────────────────────────────────────────
    _header("Stage 6 — Demo Guide")
    t = time.time()
    guide = run_demo_guide(classifier, demo, live_url=live_url)
    results["stage_6_demo_guide"] = guide
    _ok("Completed", _elapsed(t))
    print()
    for line in guide.splitlines():
        print(f"  {line}")
    print()

    # ── Registry update ───────────────────────────────────────────────────
    new_id = append_to_registry(matcher, classifier, deploy_url=live_url or None)
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
