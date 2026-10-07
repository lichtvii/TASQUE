import re

import discord

from tasque.bedtime_filter import is_bedtime_talk
from tasque.character import Character
from tasque.context import HISTORY_GAP

GROUP_CHAT_RULES = """\
You are {char}, chatting in a Discord server. Every user message starts with the sender's display name, like `Name: message`. Several people may be talking at once, so keep track of who said what and who you're answering.
You see your earlier conversations plus the latest few channel messages. "[skipped messages]" marks where unrelated chat was left out, so time may have passed there.
Write only {char}'s next message. Never write lines for anyone else, and don't start with your own name.
Your message is sent as a Discord reply to the newest message, so that person already knows it's for them. Never ping them.
When you turn to speak directly to someone other than that person, ping them by writing @ followed by the name they have in this chat (like @Name; leave out any emoji or symbols in it). Only ping people you're talking to, never people you're just talking about, and don't keep pinging the same person.
If several people spoke to you since your last message, answer them together in this one reply instead of only the latest.
Talk like a real person on Discord: casual and usually short. Put each separate message you'd send on its own line."""

SKIPPED_MESSAGES_MARKER = "[skipped messages]"
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def build_prompt(character: Character, history: list[discord.Message | None], bot_user: discord.ClientUser,
                 speaker_name: str, hide_own_bedtime_talk: bool = False) -> list[dict]:
    system_prompt = character.render(character.system_prompt, speaker_name)
    rules = character.render(GROUP_CHAT_RULES.format(char="{{char}}"), speaker_name)
    prompt = [{"role": "system", "content": f"{system_prompt}\n\n{rules}"}]

    for past_message in history:
        if past_message is HISTORY_GAP:
            _append_turn(prompt, "user", SKIPPED_MESSAGES_MARKER)
            continue
        text = render_message_text(past_message, bot_user)
        if not text:
            continue
        if past_message.author.id == bot_user.id:
            # Her own old bedtime lines would otherwise keep re-seeding the bit in every later reply.
            if hide_own_bedtime_talk and is_bedtime_talk(text):
                continue
            _append_turn(prompt, "assistant", text)
        else:
            _append_turn(prompt, "user", f"{past_message.author.display_name}: {text}")

    if character.post_history_instructions:
        prompt.append({
            "role": "system",
            "content": character.render(character.post_history_instructions, speaker_name),
        })
    return prompt


def clean_reply(raw_reply: str, character_name: str, participant_names: set[str]) -> str:
    reply = THINK_BLOCK.sub("", raw_reply).strip()
    own_prefix = f"{character_name}:".lower()

    kept_lines = []
    for line in reply.split("\n"):
        if any(line.startswith(f"{name}:") for name in participant_names):
            break
        if line.lower().startswith(own_prefix):
            line = line[len(own_prefix):].lstrip()
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def _append_turn(prompt: list[dict], role: str, text: str) -> None:
    # Merging same-role neighbours keeps strict-alternation providers happy and rejoins split bot replies.
    if prompt[-1]["role"] == role:
        prompt[-1]["content"] += "\n" + text
    else:
        prompt.append({"role": role, "content": text})


def render_message_text(message: discord.Message, bot_user: discord.ClientUser) -> str:
    parts = []
    referenced = message.reference.resolved if message.reference else None
    if isinstance(referenced, discord.Message) and message.author.id != bot_user.id:
        parts.append(f"(replying to {referenced.author.display_name})")
    if message.clean_content:
        parts.append(message.clean_content)
    parts.extend(f"[attached {attachment.content_type or 'file'}: {attachment.filename}]"
                 for attachment in message.attachments)
    parts.extend(f"[sticker: {sticker.name}]" for sticker in message.stickers)
    return " ".join(parts).strip()
