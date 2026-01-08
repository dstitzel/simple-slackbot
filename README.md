# Claude Slack Bot

A Slack bot powered by Claude that can answer questions about your project and edit markdown documentation.

## Features

- **Answer Questions**: Searches project markdown files and provides relevant answers
- **Edit Files**: Makes find-and-replace edits to markdown files via natural language
- **Weekly Updates**: Summarizes recent git commits
- **Conversation Memory**: Maintains context within channels (30 min timeout, 20 message limit)
- **Channel Access Control**: Optionally restrict which folders each channel can access

## Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Enable **Socket Mode** and generate an App Token (`xapp-...`)
3. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `app_mentions:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `im:write`
4. Install the app to your workspace and copy the Bot Token (`xoxb-...`)
5. Under **Event Subscriptions**, subscribe to:
   - `app_mention`
   - `message.im`

### 2. Get an Anthropic API Key

Get your API key from [console.anthropic.com](https://console.anthropic.com)

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your tokens
```

### 4. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt
```

### 5. Configure Projects

Edit `bot.py` and update the `PROJECTS` dict with your project directories:

```python
PROJECTS = {
    "project_alpha": "Project Alpha",
    "project_beta": "Project Beta",
}
```

Optionally configure `CHANNEL_ACCESS` to restrict which channels can access which folders.

### 6. Run

```bash
python bot.py
```

## Usage

- **In channels**: Mention the bot with `@YourBot what are the current todos?`
- **In DMs**: Just message the bot directly

The bot reads all `.md` files from your project directories and uses them as context for answering questions.

## License

MIT
