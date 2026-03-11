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
    run_classifier, run_dependency_checker, run_solutions_matcher,
    run_sdr_messenger, run_demo_builder, run_demo_guide,
    append_to_registry,
)
from storage import get_backend

app = App(token=os.environ["SLACK_BOT_TOKEN"])

_backend = get_backend()


def _save_state(channel_id: str, state: dict) -> None:
    _backend.save_slack_state(channel_id, state)


def _load_state(channel_id: str) -> dict | None:
    return _backend.get_slack_state(channel_id)


def format_slack_blocks(classifier, dependency, matcher, messenger_output):
    customer = classifier.get("customer", {})
    demo_type = classifier.get("demo_type", "unknown")
    wow = classifier.get("wow_moment", "")
    match_type = matcher.get("match_result", {}).get("type", "none")
    matched = matcher.get("match_result", {}).get("matched_solution", "")
    effort = matcher.get("build_instruction", {}).get("estimated_effort", "unknown")
    can_build = dependency.get("can_build_immediately", False)
    gaps = matcher.get("discovery_gaps", [])

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

    if not can_build:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📧 SDR Action Required:*\n{messenger_output}"}
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "✅ *No customer input needed — ready to build*"}
        })

    return blocks


def _run_pipeline(transcript, channel_id, user_id, say):
    try:
        classifier = run_classifier(transcript)

        if classifier.get("demo_decision") == "NO":
            say(f"❌ *No demo needed.*\nReason: {classifier.get('reason', 'Insufficient signal.')}")
            return

        dependency = run_dependency_checker(classifier)

        if any(
            item.get("urgency", "").startswith("needed before build")
            for item in dependency.get("ask_customer", [])
        ):
            dependency["can_build_immediately"] = False

        matcher = run_solutions_matcher(classifier, dependency)

        # Skip builder if ALL components already exist in registry (Python decides, not LLM)
        _component_matches = matcher.get("component_matches", [])
        if _component_matches and all(
            m.get("action", "build_new").startswith("exists")
            for m in _component_matches
        ):
            existing_urls = [m["demo_url"] for m in _component_matches if m.get("demo_url")]
            sdr_note = matcher.get("build_instruction", {}).get("sdr_note", "")
            msg = sdr_note or "All required components already exist in solutions library."
            url_line = f"\nExisting demo: {existing_urls[0]}" if existing_urls else ""
            say(f"*All components exist — no new build needed.*\n{msg}{url_line}")
            return

        messenger_output = ""
        if dependency.get("ask_customer"):
            messenger_output = run_sdr_messenger(classifier, dependency, matcher)

        blocks = format_slack_blocks(classifier, dependency, matcher, messenger_output)
        app.client.chat_postMessage(channel=channel_id, blocks=blocks)

        if dependency.get("can_build_immediately"):
            say("🔨 Building demo now...")
            demo = run_demo_builder(classifier, dependency, matcher)
            say("🎉 *Demo built! Pushing to GitHub and deploying to Railway...*")
            slug = re.sub(r"[^a-z0-9-]", "-",
                          classifier.get("customer", {}).get("company", "demo").lower())
            try:
                live_url = deploy_demo(demo, slug, classifier=classifier)
                say(f"🚀 *Live at:* {live_url}")
                append_to_registry(matcher, classifier, deploy_url=live_url)
                guide = run_demo_guide(classifier, demo, live_url=live_url)
                say(f"📋 *Demo Guide:*\n```{guide}```")
            except Exception as deploy_err:
                say(f"⚠️ Deploy failed: `{str(deploy_err)}`\n\nDemo code:\n\n{demo}")
        else:
            _save_state(channel_id, {
                "classifier": classifier,
                "dependency": dependency,
                "matcher": matcher,
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
    say(f"<@{user_id}> 🔍 Analyzing transcript across 3 stages... (~45 seconds)")
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

    classifier = state["classifier"]
    dependency = state["dependency"]
    matcher = state["matcher"]

    say(f"✅ Got it — building with customer inputs:\n```{customer_inputs}```")
    try:
        demo = run_demo_builder(classifier, dependency, matcher, customer_inputs=customer_inputs)
        say("🎉 *Demo built! Pushing to GitHub and deploying to Railway...*")
        slug = re.sub(r"[^a-z0-9-]", "-",
                      classifier.get("customer", {}).get("company", "demo").lower())
        live_url = deploy_demo(demo, slug, classifier=classifier)
        say(f"🚀 *Live at:* {live_url}")
        append_to_registry(matcher, classifier, deploy_url=live_url)
        guide = run_demo_guide(classifier, demo, live_url=live_url)
        say(f"📋 *Demo Guide:*\n```{guide}```")
    except Exception as e:
        say(f"⚠️ Build/deploy failed: `{str(e)}`")

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
