# Railway Setup — Account Token + GitHub App

The deploy pipeline creates a Railway project per demo, links it to the GitHub repo, triggers a deploy, provisions a public domain, and polls until live.

---

## Step 1 — Create a Railway account

Sign up at **railway.com** if you don't have one. The Hobby plan ($5/month) is enough — it gives you enough compute hours for multiple always-on demo services.

---

## Step 2 — Install the Railway GitHub App

Railway needs access to your GitHub repos to pull and deploy code.

1. In Railway dashboard → click your avatar → **Settings → Integrations → GitHub**
2. Click **Connect GitHub**
3. When prompted by GitHub, choose **All repositories** (or select specific ones — but since deploy.py creates new repos dynamically, "All repositories" is easier)
4. Authorize the Railway GitHub App

This is a one-time setup. After this, any repo you create via the GitHub API will automatically be accessible to Railway for deployment.

---

## Step 3 — Create an Account-Level API Token

> **Important:** Railway has two token types — *project tokens* and *account tokens*. The deploy pipeline needs an **account token** because it creates new projects programmatically. A project token only works within an existing project.

1. Go to **railway.com/account/tokens**
   - Or: click your avatar → **Account Settings → Tokens**

2. Click **Create Token**

3. Set:
   - **Name**: `demo-creator-agent`
   - **Team**: your personal account (not a team workspace unless that's where you want projects created)

4. Copy the token

5. Paste it into your `.env`:
   ```
   RAILWAY_TOKEN=your-token-here
   ```

---

## What the token is used for

`deploy.py` makes these Railway GraphQL API calls to `https://backboard.railway.app/graphql/v2`:

| Operation | What it does |
|---|---|
| `projectCreate` | Creates a new Railway project named `demo-{slug}` |
| `project(id)` | Fetches the default environment ID (used in all subsequent calls) |
| `serviceCreate` | Creates a service inside the project, linked to the GitHub repo |
| `serviceInstanceDeploy` | Triggers the first deployment |
| `serviceDomainCreate` | Provisions a `*.up.railway.app` public URL |
| `deployments` (poll) | Polls every 10s until status is `SUCCESS` (up to 5 minutes) |

---

## Expected deploy flow

After `/demo` completes stage 5 in Slack, you'll see:

```
🎉 Demo built! Pushing to GitHub and deploying to Railway...
🚀 Live at: https://demo-renocomputerfix.up.railway.app
```

In your Railway dashboard, a new project called `demo-renocomputerfix` will appear with one service, deployed from the GitHub repo.

---

## Troubleshooting

**"Railway API error: Unauthorized"**
→ Token is wrong or expired. Regenerate at railway.com/account/tokens.

**"Railway API error: [...] source repo not found"**
→ Railway GitHub App doesn't have access to the newly created repo. Go back to Step 2 and make sure "All repositories" is selected, or manually add the repo.

**Deploy times out (>5 minutes)**
→ The default timeout is 300s. Check the Railway dashboard for build logs — the most common cause is a missing `requirements.txt` or a `main.py` that crashes on startup.

**Domain not accessible after deploy**
→ Railway may take 1-2 minutes after `SUCCESS` to propagate DNS. Wait and retry.
