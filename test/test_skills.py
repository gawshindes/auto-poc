import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Force Python to load our local modules instead of PyPI packages
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline import run_understand, run_design
from deploy import parse_demo_files

transcript = """
Founder: Hey, thanks for jumping on a call. So we've got a prospect — TechFlow IT Solutions. They're an IT services company, about 30 employees.

SDR: Cool, what are they looking for?

Founder: They want a simple web page with a 'Contact Us' form. When someone submits the form with their name, email, and a message, they want a Slack notification sent to their #inbound channel so the team knows immediately. They said they're losing leads because nobody checks the contact form inbox.

SDR: Makes sense. So it's a lead capture form that pings Slack in real-time?

Founder: Exactly. Nothing fancy — just a clean form, maybe use AI to categorize the inquiry type (sales, support, partnership), and fire off a Slack message with all the details. They want to demo it to their ops manager next week.

SDR: Got it. We can definitely build that. The Slack integration is straightforward since we have that skill already.
"""

print("Running Understand...")
u = run_understand(transcript)

print("Running Design...")
d = run_design(u)

spec = d.get("demo_spec", {})
skills = spec.get("required_skills", [])
print(f"Required Skills chosen by LLM: {skills}")

if "slack" not in skills:
    print("FAILED: The LLM did not request the 'slack' skill.")
    print(json.dumps(spec, indent=2))
else:
    print("SUCCESS: LLM correctly requested the 'slack' skill!")

# Let's mock the deployment parsing step to see if files get injected correctly
from deploy import deploy_demo
# we won't actually deploy, we just want to see the files mapping
files = parse_demo_files("## requirements.txt\n```\nfastapi\n```")

required_skills = ["slack"]
tokens_to_inject = set()

for skill in required_skills:
    skill_dir = Path("skills") / skill
    if not skill_dir.exists():
        continue
        
    adapter_path = skill_dir / "adapter.py"
    manifest_path = skill_dir / "manifest.json"
    
    if adapter_path.exists():
        files[f"skills/{skill}.py"] = adapter_path.read_text()
        files["skills/__init__.py"] = ""
        
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        packages = manifest.get("packages", [])
        if packages and "requirements.txt" in files:
            files["requirements.txt"] += "\n" + "\n".join(packages)
        for t in manifest.get("tokens", []):
            tokens_to_inject.add(t)

print(f"\nFiles after parsing + injection: {list(files.keys())}")
print(f"Tokens required: {tokens_to_inject}")
print(f"Requirements: \n{files.get('requirements.txt')}")
