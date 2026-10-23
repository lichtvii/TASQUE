import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Settings:
    bot_id: str
    discord_token_env: str
    discord_token: str
    openrouter_api_key: str
    character_file: Path
    character_name: str
    trigger_names: list[str]
    conversation_history_limit: int
    recent_history_limit: int
    history_scan_limit: int
    respond_to_bots: bool
    bot_reply_limit: int
    model_id: str
    temperature: float
    max_tokens: int
    reasoning_enabled: bool | None
    max_messages_per_reply: int
    drop_trailing_periods: bool
    filter_bedtime_talk: bool
    typing_seconds_per_char: float
    min_typing_seconds: float
    max_typing_seconds: float
    followup_enabled: bool
    followup_window_messages: int
    followup_window_minutes: float
    followup_judge_model: str
    followup_reply_threshold: float


def load_settings(project_root: Path) -> list[Settings]:
    load_dotenv(project_root / ".env")
    config_path = project_root / "config.toml"
    if not config_path.exists():
        config_path = project_root / "config.example.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    openrouter_api_key = _required_env("OPENROUTER_API_KEY")
    bot_tables = config["bots"] if "bots" in config else [config["bot"]]
    return [_bot_settings(project_root, config, bot, openrouter_api_key) for bot in bot_tables]


def _bot_settings(project_root: Path, config: dict, bot: dict, openrouter_api_key: str) -> Settings:
    model = {**config["model"], **bot.get("model", {})}
    messages = {**config["messages"], **bot.get("messages", {})}
    followup = {**config.get("followup", {}), **bot.get("followup", {})}
    discord_token_env = bot.get("token_env", "DISCORD_TOKEN")

    return Settings(
        bot_id=re.sub(r"[^a-z0-9]+", "_", bot["character_name"].lower()).strip("_"),
        discord_token_env=discord_token_env,
        discord_token=os.getenv(discord_token_env, "").strip(),
        openrouter_api_key=openrouter_api_key,
        character_file=project_root / bot["character_file"],
        character_name=bot["character_name"],
        trigger_names=bot["trigger_names"],
        conversation_history_limit=bot.get("conversation_history_limit", 50),
        recent_history_limit=bot.get("recent_history_limit", 10),
        history_scan_limit=bot.get("history_scan_limit", 400),
        respond_to_bots=bot.get("respond_to_bots", False),
        bot_reply_limit=bot.get("bot_reply_limit", 2),
        model_id=model["id"],
        temperature=model.get("temperature", 0.9),
        max_tokens=model.get("max_tokens", 400),
        reasoning_enabled=model.get("reasoning"),
        max_messages_per_reply=messages.get("max_messages_per_reply", 6),
        drop_trailing_periods=messages.get("drop_trailing_periods", False),
        filter_bedtime_talk=messages.get("filter_bedtime_talk", True),
        typing_seconds_per_char=messages.get("typing_seconds_per_char", 0.02),
        min_typing_seconds=messages.get("min_typing_seconds", 0.3),
        max_typing_seconds=messages.get("max_typing_seconds", 1.5),
        followup_enabled=followup.get("enabled", True),
        followup_window_messages=followup.get("window_messages", 8),
        followup_window_minutes=followup.get("window_minutes", 5),
        followup_judge_model=followup.get("judge_model", "typesafe/jev-1.13"),
        followup_reply_threshold=followup.get("reply_threshold", 0.5),
    )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Put it in .env (see .env.example).")
    return value
