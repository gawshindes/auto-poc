import io
import os
import re
import sys
import json
import requests
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from deploy import deploy_demo

# Import shared pipeline module
sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import (
    run_understand, run_design, run_build, run_guide,
    append_to_registry,
)
from storage import get_backend

app = App(token=os.environ["SLACK_BOT_TOKEN"])

_backend = get_backend()


def _save_state(channel_id: str, state: dict) -> None:
    _backend.save_slack_state(channel_id, state)


def _load_state(channel_id: str) -> dict | None:
    return _backend.get_slack_state(channel_id)


def format_slack_blocks(understand, design):
    customer = understand.get("customer", {})
    demo_type = understand.get("demo_type", "unknown")
    wow = understand.get("wow_moment", "")
    match_type = design.get("match_result", {}).get("type", "none") if "match_result" in design else "none"
    matched = design.get("match_result", {}).get("matched_solution", "") if "match_result" in design else ""
    effort = design.get("build_instruction", {}).get("estimated_effort", "unknown")
    can_build = understand.get("can_build_immediately", False)
    gaps = design.get("discovery_gaps", [])

    match_emoji = {"full": "♻️ Full match", "partial": "🔧 Partial match", "none": "🆕 Build new"}.get(match_type, "❓")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🎯 Demo Analysis: {customer.get('company', 'Unknown')}"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Customer:*\n{customer.get('name')} @ {customer.get('company')}"},
                {"type": "mrkdwn", "text": f"*Demo Type:*\n`{demo_type}`"},
                {"type": "mrkdwn", "text": f"*Solution Match:*\n{match_emoji}{' — ' + matched if matched else ''}"},
                {"type": "mrkdwn", "text": f"*Build Effort:*\n{effort}"}
            ]
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*💡 Wow Moment:*\n{wow}"}
        }
    ]

    if gaps:
        gap_text = "\n".join([f"• *{g['gap']}:* _{g['suggested_question']}_" for g in gaps[:3]])
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔍 Discovery Gaps (ask in demo meeting):*\n{gap_text}"}
        })

    sdr_msg = design.get("sdr_message", {})
    if sdr_msg.get("needed"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📧 SDR Action Required:*\n{sdr_msg.get('email_draft', '')}"}
        })
    elif can_build:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "✅ *No customer input needed — ready to build*"}
        })

    return blocks


def _run_pipeline(transcript, channel_id, user_id, say):
    try:
        # Stage 1 — Understand
        understand = run_understand(transcript)

        if understand.get("demo_decision") == "NO":
            say(f"❌ *No demo needed.*\nReason: {understand.get('reason', 'Insufficient signal.')}")
            return

        # Merge resolved knowledge into customer inputs
        customer_inputs = ""
        resolved = understand.get("dependencies", {}).get("resolved_by_knowledge", [])
        if resolved:
            customer_inputs = "\n\n".join(
                f"[Auto-resolved] {r['dependency']}:\n{r['answer']}"
                for r in resolved
            )

        # Stage 2 — Design
        design = run_design(understand, customer_inputs)

        # Skip build if ALL components already exist in registry
        matches = design.get("component_matches", [])
        if matches and all(
            m.get("action", "build_new").startswith("exists")
            for m in matches
        ):
            existing_urls = [m["demo_url"] for m in matches if m.get("demo_url")]
            sdr_note = design.get("build_instruction", {}).get("sdr_note", "")
            msg = sdr_note or "All required components already exist in solutions library."
            url_line = f"\nExisting demo: {existing_urls[0]}" if existing_urls else ""
            say(f"*All components exist — no new build needed.*\n{msg}{url_line}")
            return

        blocks = format_slack_blocks(understand, design)
        app.client.chat_postMessage(channel=channel_id, blocks=blocks)

        can_build = understand.get("can_build_immediately", False)
        ask_items = understand.get("dependencies", {}).get("ask_customer", [])

        if can_build or not ask_items:
            say("🔨 Building demo now...")
            demo = run_build(design, customer_inputs)
            say("🎉 *Demo built! Pushing to GitHub and deploying to Railway...*")
            slug = re.sub(r"[^a-z0-9-]", "-",
                          understand.get("customer", {}).get("company", "demo").lower())
            try:
                live_url = deploy_demo(demo, slug, classifier=understand)
                say(f"🚀 *Live at:* {live_url}")
                append_to_registry(design, understand, deploy_url=live_url)
                guide = run_guide(understand, demo, live_url=live_url)
                say(f"📋 *Demo Guide:*\n```{guide}```")
            except Exception as deploy_err:
                say(f"⚠️ Deploy failed: `{str(deploy_err)}`\n\nDemo code:\n\n{demo}")
        else:
            _save_state(channel_id, {
                "understand": understand,
                "design": design,
            })
            say("⏳ *Waiting for customer inputs before building.*\n"
                "Once the customer replies, paste their answer with `/demo-continue [customer reply]`.")

    except Exception as e:
        say(f"❌ Error: `{str(e)}`\nCheck transcript format and try again.")


@app.command("/demo")
def handle_demo(ack, say, body, command):
    ack()
    transcript = command.get("text", "").strip()
    if not transcript:
        say("Paste the transcript after the command: `/demo [transcript]`")
        return

    user_id = body["user_id"]
    channel = body["channel_id"]
    say(f"<@{user_id}> 🔍 Analyzing transcript... (~45 seconds)")
    _run_pipeline(transcript, channel, user_id, say)


@app.event("file_shared")
def handle_pdf_upload(event, say, client):
    import pdfplumber
    file_id = event["file_id"]
    channel_id = event["channel_id"]

    file_info = client.files_info(file=file_id)["file"]
    if file_info.get("mimetype") != "application/pdf":
        return

    user_id = event.get("user_id", "unknown")
    say(f"<@{user_id}> 📄 PDF received — analyzing transcript... (~45 seconds)")

    pdf_bytes = requests.get(
        file_info["url_private_download"],
        headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"},
    ).content

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        transcript = "\n".join(p.extract_text() for p in pdf.pages if p.extract_text())

    if not transcript.strip():
        say("❌ Could not extract text from PDF. Is it a text-based PDF (not a scanned image)?")
        return

    _run_pipeline(transcript, channel_id, user_id, say)


@app.command("/demo-continue")
def handle_demo_continue(ack, say, body, command):
    ack()
    customer_inputs = command.get("text", "").strip()
    channel_id = body["channel_id"]

    if not customer_inputs:
        say("Usage: `/demo-continue [paste customer reply here]`")
        return

    state = _load_state(channel_id)
    if not state:
        say("❌ No pending demo found for this channel. Run `/demo [transcript]` first.")
        return

    understand = state["understand"]
    design = state["design"]

    say(f"✅ Got it — building with customer inputs:\n```{customer_inputs}```")
    try:
        demo = run_build(design, customer_inputs=customer_inputs)
        say("🎉 *Demo built! Pushing to GitHub and deploying to Railway...*")
        slug = re.sub(r"[^a-z0-9-]", "-",
                      understand.get("customer", {}).get("company", "demo").lower())
        live_url = deploy_demo(demo, slug, classifier=understand)
        say(f"🚀 *Live at:* {live_url}")
        append_to_registry(design, understand, deploy_url=live_url)
        guide = run_guide(understand, demo, live_url=live_url)
        say(f"📋 *Demo Guide:*\n```{guide}```")
    except Exception as e:
        say(f"⚠️ Build/deploy failed: `{str(e)}`")

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
