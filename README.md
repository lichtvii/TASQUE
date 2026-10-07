# Tasque

A Discord bot that talks as a character, using a similar customization, using OpenRouter API. 
Replies when @mentioned, replied to, or called by name, and sends its answer as several short messages (split into realistic messages).

**Tested with DeepSeek V4.1 Flash**

## Setup

1. In the [Discord Developer Portal](https://discord.com/developers/applications), open your bot → **Bot** → enable **Message Content Intent**. Copy the token.
2. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` and `OPENROUTER_API_KEY`.
3. Copy `config.example.toml` to `config.toml` and `characters/example.toml` to your own file (e.g. `characters/mychar.toml`), then point `character_file`, `character_name` and `trigger_names` in `config.toml` at it. You can also point `character_file` at a SillyTavern `.json`/`.png` card. Your `config.toml` and characters are gitignored, so they stay local.
4. Double-click **`Start TASQUE.bat`**. The first launch sets up the Python environment; later launches start right away. Close the window to stop it.

To run it silently in the background at every pc startup, use **`Enable TASQUE Autostart.bat`** (and **`Disable TASQUE Autostart.bat`** to undo).

Manual equivalent:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

## Follow-ups

Right after the character speaks, it can also answer messages that don't mention it (e.g. "derivatives" after it asked "what kind of math"). TypeSafe's Jev decision model (`typesafe/jev-1.13`, ~0.3s per check) scores whether the message is meant for the character; if Jev is unavailable, a YES/NO call to the main model decides instead. `reply_threshold` sets how chatty it is. Settings in the `[followup]` section of `config.toml`; decisions are logged in `data/tasque.log`.

## Commands

- `/lobotomise`: anyone can use it. The character forgets everything in that channel before this point. Survives restarts (stored in `data/`).
- `/say text`: the character posts exactly `text`. Only shown to members with Manage Messages by default; change who can use it in Server Settings → Integrations → your bot.

## Tuning

Everything is in `config.toml`: trigger names, history length, model, temperature, max messages per reply, typing speed, and `drop_trailing_periods` for the lowercase-no-period texting feel.
