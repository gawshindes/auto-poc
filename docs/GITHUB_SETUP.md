# GitHub Setup — Personal Access Token

The deploy pipeline creates a public GitHub repo per demo and pushes the generated code to it. Railway then pulls from that repo to deploy.

---

## Step 1 — Create a Personal Access Token

1. Go to **github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   - Direct link: https://github.com/settings/tokens

2. Click **Generate new token (classic)**

3. Set:
   - **Note**: `demo-creator-agent`
   - **Expiration**: No expiration (or 1 year)
   - **Scopes**: check `repo` (the top-level checkbox — this grants all repo sub-scopes)

4. Click **Generate token**

5. Copy the token immediately — it starts with `ghp-` and is only shown once

6. Paste it into your `.env`:
   ```
   GITHUB_TOKEN=ghp-xxxxxxxxxxxxxxxxxxxx
   ```

---

## What the token is used for

`deploy.py` makes these GitHub API calls using your token:

| Call | What it does |
|---|---|
| `POST /user/repos` | Creates `demo-{slug}` as a public repo under your account |
| `POST /repos/{name}/git/trees` | Uploads all demo files as a single git tree |
| `POST /repos/{name}/git/commits` | Creates the initial commit |
| `POST /repos/{name}/git/refs` | Creates the `main` branch pointing to that commit |

---

## Notes

- Repos are created **public** so Railway can clone them without extra auth
- Each deploy creates a new repo named `demo-{company-slug}`, e.g. `demo-renocomputerfix`
- If a repo with that name already exists, the deploy will fail with a 422 — delete the old repo or the pipeline will handle it as a deploy error and fall back to posting raw code to Slack
- The token needs the `repo` scope only — no other scopes required
