import re

import discord

from tasque.prompt import render_message_text

JUDGE_INSTRUCTIONS = """\
You decide whether {char} should reply in a Discord group chat. {char} is a member of the chat.
{char} replies only when the newest message is meant for her and invites an answer: it answers something she asked, asks her something, pushes back on what she said, or clearly continues a conversation with her.
She stays quiet when people are talking to each other, when the message is general chatter, when it's just a reaction like "lol" or "lmao" that doesn't need an answer, or when it's unclear it's for her.
Answer with exactly one word: YES or NO."""

FIRST_WORD = re.compile(r"[A-Za-z]+")
REPLY_QUESTION = "should_reply"


def transcript_lines(character_name: str, transcript: list[discord.Message],
                     bot_user: discord.ClientUser) -> list[str]:
    lines = []
    for past_message in transcript:
        speaker = character_name if past_message.author.id == bot_user.id else past_message.author.display_name
        lines.append(f"{speaker}: {render_message_text(past_message, bot_user)}")
    return lines


def build_decision_request(character_name: str, transcript: list[discord.Message],
                           bot_user: discord.ClientUser) -> tuple[dict, dict]:
    lines = transcript_lines(character_name, transcript, bot_user)
    state = {"character": character_name, "chat_oldest_first": "\n".join(lines), "newest_message": lines[-1]}
    instructions_without_answer_format = JUDGE_INSTRUCTIONS.format(char=character_name).rsplit("\n", 1)[0]
    questions = {REPLY_QUESTION: {
        "type": "noul",
        "instructions": instructions_without_answer_format,
        "criteria": {"true": f"{character_name} should reply to the newest message.",
                     "false": f"{character_name} should stay quiet."},
    }}
    return state, questions


def reply_probability(answers: dict) -> float:
    return float(answers[REPLY_QUESTION]["noul"])


def build_judge_prompt(character_name: str, transcript: list[discord.Message],
                       bot_user: discord.ClientUser) -> list[dict]:
    lines = transcript_lines(character_name, transcript, bot_user)
    newest_line = lines[-1]
    return [
        {"role": "system", "content": JUDGE_INSTRUCTIONS.format(char=character_name)},
        {"role": "user", "content": "Chat, oldest first:\n" + "\n".join(lines)
            + f"\n\nNewest message:\n{newest_line}\n\nShould {character_name} reply to the newest message?"},
    ]


def parse_judge_verdict(raw_verdict: str) -> bool:
    without_thinking = re.sub(r"<think>.*?</think>", "", raw_verdict, flags=re.DOTALL | re.IGNORECASE)
    first_word = FIRST_WORD.search(without_thinking)
    return bool(first_word) and first_word.group().upper() == "YES"
