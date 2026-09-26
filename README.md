# Reddit Karma Scout 🚀

A Python 3.11 semi-automated Reddit Karma Scout designed to monitor rising threads, draft natural Gen-Z / Millennial comment suggestions via Google Gemini AI (`google-genai` SDK), and deliver one-click copyable alerts directly to your Discord channel via Webhooks.

Built to run 24/7 on **Render** (as a **Background Worker** or **Web Service**) or locally.

---

## 🌟 Key Features

1. **Dual-Mode Reddit Monitoring**:
   - **Public Mode (No API keys needed)**: Uses Reddit's public JSON and RSS endpoints with automatic fallback and rate-limit backoff.
   - **PRAW Authenticated Mode**: Automatically queries your account's total karma (`me.comment_karma + me.link_karma`) and dynamically selects optimal target subreddits:
     - **Tier 0 (< 50 karma)**: `AskReddit`, `NoStupidQuestions`, `CasualConversation`, `memes`, `aww`
     - **Tier 1 (50-250 karma)**: `technology`, `funny`, `Showerthoughts`, `explainlikeimfive`
     - **Tier 2 (> 250 karma)**: `buildapc`, `gaming`, `popheads`, `Discussion`
2. **AI Draft Generation (Google Gemini)**:
   - Powered by Google's new `google-genai` SDK (`gemini-2.5-flash` with automatic fallback).
   - Follows strict behavioral instructions:
     - 1-2 sentences maximum.
     - Casual lowercase style, messy phone punctuation, natural slang (`tbh`, `ngl`, `fr`, `bro`, `lowkey`).
     - Zero robotic bullet points or dashes.
3. **One-Click Discord Webhook Delivery**:
   - Posts rich embeds with thread title, direct link, subreddit, and comment count.
   - Embeds the suggested response in a **code block** so you can tap/click to instantly copy and paste into Reddit.
4. **Persistent Memory & Deduplication**:
   - Utilizes SQLite (`processed_posts.db`) with an in-memory set cache for $O(1)$ duplicate checks. Never alerts on the same post twice.
5. **Render-Ready Architecture**:
   - Includes `Procfile` (`worker: python main.py`) and `render.yaml`.
   - Built-in lightweight HTTP health check server if deployed as a **Render Web Service** (enabling the Render Free tier).

---

## 📁 Project Structure

```text
Reddit/
├── main.py               # Main execution loop & graceful shutdown handling
├── config.py             # Environment configuration & karma tiers
├── reddit_fetcher.py     # Dual-engine fetcher (PRAW + Public JSON/RSS)
├── ai_drafter.py         # Gemini AI comment generator with strict Gen-Z rules
├── discord_notifier.py   # Discord embed webhook dispatcher
├── storage.py            # SQLite database & in-memory deduplication cache
├── requirements.txt      # Python dependencies
├── Procfile              # Render worker process declaration
├── render.yaml           # Render 1-click blueprint specification
├── .env.example          # Sample environment variables template
└── .gitignore            # Excludes local database and secrets
```

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
| :--- | :---: | :---: | :--- |
| `GEMINI_API_KEY` | **Yes** | — | Google Gemini API key from [Google AI Studio](https://aistudio.google.com/). |
| `DISCORD_WEBHOOK_URL` | **Yes** | — | Webhook URL of your private Discord notifications channel. |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model name (falls back gracefully to `gemini-3.8-flash` / `gemini-1.5-flash`). |
| `REDDIT_CLIENT_ID` | No | `""` | Reddit App Client ID. Leave blank to run in **Public Mode**. |
| `REDDIT_CLIENT_SECRET` | No | `""` | Reddit App Client Secret. |
| `REDDIT_USER_AGENT` | No | `RedditKarmaScout/1.0` | Custom Reddit User Agent string. |
| `REDDIT_USERNAME` | No | `""` | Reddit account username (for karma tier detection). |
| `REDDIT_PASSWORD` | No | `""` | Reddit account password (for karma tier detection). |
| `SCAN_INTERVAL_SECONDS`| No | `300` | Delay between scan cycles in seconds (default: 5 minutes). |
| `TARGET_SUBREDDITS` | No | Tier 0 list | Comma-separated subreddits to monitor in Public Mode. |
| `POST_COMMENT_LIMIT` | No | `20` | Max comments for a post to be considered "early". |

---

## 🚀 Quickstart: Local Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in:
1. `GEMINI_API_KEY`: Get a free key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. `DISCORD_WEBHOOK_URL`:
   - In Discord: Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
3. *(Optional)* Reddit API credentials if you have them. If not, leave them blank and the app will use the public feed.

### 3. Run the Scout
```bash
python main.py
```

---

## ☁️ Deploying to Render

### Option A: Background Worker (Recommended)
1. Push this directory to a private GitHub or GitLab repository.
2. Go to [Render Dashboard](https://dashboard.render.com/) and click **New +** → **Background Worker**.
3. Connect your repository.
4. Set the following settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
5. In the **Environment Variables** section, add your `GEMINI_API_KEY`, `DISCORD_WEBHOOK_URL`, etc.
6. Click **Create Background Worker**.

### Option B: Web Service (Render Free Tier)
Because Render offers a free tier for Web Services (which require binding to an HTTP port), `main.py` contains an automatic lightweight HTTP server that binds to `$PORT`:
1. Click **New +** → **Web Service**.
2. Connect your repository.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python main.py`
5. Add your Environment Variables.
6. Click **Create Web Service**. Render will detect the health check server on `$PORT` and keep your worker running.

---

## 🔒 Security Best Practices
- Never commit your `.env` file or API keys to GitHub.
- Keep your Discord Webhook URL private so unauthorized users cannot spam your channel.
- The scout is strictly **read-only and semi-automated**: you review and submit the comments yourself, keeping full control over your Reddit accounts and remaining compliant with Reddit's policies.
