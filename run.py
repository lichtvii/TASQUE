import logging
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
import discord

from tasque.bot import CharacterBot
from tasque.character import load_character
from tasque.memory_cutoffs import MemoryCutoffs
from tasque.openrouter import OpenRouterClient
from tasque.settings import load_settings

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_PATH = DATA_DIR / "tasque.log"
SINGLE_INSTANCE_PORT = 47321
CONNECT_RETRY_SECONDS = 30

log = logging.getLogger("tasque")


def main() -> None:
    configure_logging()
    instance_lock = claim_single_instance()
    if instance_lock is None:
        log.error("TASQUE is already running (probably in the background). Not starting a second copy.")
        sys.exit(1)

    try:
        run_until_stopped()
    except BaseException as error:
        if not isinstance(error, KeyboardInterrupt):
            log.exception("TASQUE stopped because of an error")
        raise


def run_until_stopped() -> None:
    settings = load_settings(PROJECT_ROOT)
    character = load_character(settings.character_file, settings.character_name)
    memory_cutoffs = MemoryCutoffs(DATA_DIR / "memory_cutoffs.json")

    # At login the network is often not up yet; a failed first connection must not end the background process.
    while True:
        llm = OpenRouterClient(
            api_key=settings.openrouter_api_key,
            model_id=settings.model_id,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            reasoning_enabled=settings.reasoning_enabled,
        )
        bot = CharacterBot(settings, character, llm, memory_cutoffs)
        try:
            bot.run(settings.discord_token, log_handler=None)
            return
        except (aiohttp.ClientConnectionError, OSError, discord.GatewayNotFound, discord.DiscordServerError):
            log.warning("Can't reach Discord, retrying in %s seconds", CONNECT_RETRY_SECONDS)
            time.sleep(CONNECT_RETRY_SECONDS)


def configure_logging() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def claim_single_instance() -> socket.socket | None:
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        lock_socket.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    except OSError:
        lock_socket.close()
        return None
    return lock_socket


if __name__ == "__main__":
    main()
