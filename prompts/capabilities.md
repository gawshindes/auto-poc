# CAPABILITIES REGISTRY

This document lists what the agency can provide, what must always be mocked, and what can be asked from the customer.
Use this as the ground truth when deciding how to handle each dependency.

## APIs & Services We Provide

| Name | Key | Use for |
|------|-----|---------|
| Claude API | anthropic_api | Any LLM/AI feature, chat agents, text processing |
| OpenAI API | openai_api | Alternative LLM, embeddings, vision |
| Gemini API | gemini_api | Alternative LLM, multimodal |
| Serper API | serper_api | Web search, Google results |
| SendGrid | sendgrid_api | Email sending in demos |
| Twilio | twilio_api | SMS demos |
| Railway | railway_hosting | Web UI hosting, always-on services |
| Modal | modal_hosting | Pipeline jobs, background automation, cron jobs |
| Vercel | vercel_hosting | Static frontend hosting |
| Supabase (demo instance) | supabase_demo | Database for demos that need persistence |
| Playwright | playwright | Web scraping, browser automation |
| BeautifulSoup | beautifulsoup | HTML parsing, scraping public pages |

## Systems to Always Mock

Never ask the customer for access to these. Always simulate with realistic fake data.

| System | Keywords | Mock Strategy | Example Data |
|--------|----------|---------------|--------------|
| Salesforce CRM | salesforce, sfdc, crm | Dummy JSON store with realistic SFDC field structure: Id, Name, Amount, StageName, CloseDate, AccountId, OwnerId | 10-20 realistic deal records in the customer's industry |
| HubSpot CRM | hubspot, hub spot | JSON file mimicking HubSpot contact/deal structure with realistic pipeline stages | Mix of leads, prospects, and closed deals |
| Pipedrive | pipedrive | JSON with deal stages, contact info, activity history | Realistic sales pipeline for their industry |
| SAP / ERP systems | sap, erp, oracle, netsuite | SQLite DB or JSON with inventory/order/financial data structure | 20-50 records with realistic industry data |
| Internal databases | our database, internal system, our backend, proprietary | SQLite with schema inferred from the workflow described in transcript | Realistic records using customer's actual industry terminology |
| Payment processors | stripe, payment, billing, invoice | Simulate payment responses with hardcoded mock transactions | Mix of successful, pending, and failed transactions |
| Enterprise OAuth / SSO | oauth, sso, active directory, okta, saml | Hardcode a demo user session — skip auth entirely in demo | Single pre-authenticated demo user |
| Slack / Teams workspace data | slack workspace, teams channels, internal messages | Mock message feed with realistic team communication samples | 5-10 realistic messages/threads relevant to the use case |
| Google Workspace (Drive, Sheets, Docs) | google drive, google sheets, google docs, gsuite | Use CSV/JSON files locally mimicking the spreadsheet or doc structure | Sample data relevant to their workflow |

## Things to Ask the Customer

Only ask for things the customer can provide in under an hour with zero IT involvement. Ordered by ease/time.

| Type | Keywords | Time to Get | How to Ask |
|------|----------|-------------|------------|
| Public URL | ebay store, website url, public profile, linkedin, amazon store | 5 minutes | Share the direct link to [X] so we pull from the right place |
| Simple API key | squarespace, notion, airtable, webflow, shopify | 10-15 minutes | Grab your API key from [Settings > Advanced > API Keys] and paste it here |
| Sample data file | csv, spreadsheet, export, data file | 10 minutes | Export a sample of [X] as a CSV — even 20-30 rows is perfect |
| Brand assets | logo, brand colors, company colors | 5 minutes | Send your logo file and brand colors — we'll make the demo feel like yours |
| Workflow confirmation | markup, percentage, pricing, threshold, rule | 2 minutes | Just confirming — [specific parameter] so we set this up the way you want |

## Tech Stack Constraint

**All demos must be built in Python. Never recommend or use React, Vue, Next.js, Vite, or any Node.js framework.**

Our deploy pipeline validates for `main.py`, `requirements.txt`, and `Procfile`. A React project fails deploy every time.

| Need | Use instead |
|------|-------------|
| Interactive UI | Plain HTML/JS served by FastAPI (`HTMLResponse` or Jinja2 templates) |
| Real-time updates | FastAPI server-sent events or polling — not WebSockets with Node |
| Charts / data viz | Chart.js via CDN in plain HTML — not React + Recharts |
| Any frontend | Inline HTML/CSS/JS in a FastAPI Jinja2 template or `HTMLResponse` |

The demo builder and dependency checker must always recommend: **Python + FastAPI + plain HTML/JS**.

## Hosting Decision Guide

| Demo Type | Recommended Host |
|-----------|-----------------|
| Pipeline automation | Modal — handles cron jobs, background tasks, serverless compute |
| Web UI with backend | Railway — full-stack, always-on, easy deploy |
| Static frontend only | Vercel — instant deploy, free tier |
| Chat agent | Railway — needs persistent server for API calls |
| Data processing job | Modal — pay per execution, no idle cost |
