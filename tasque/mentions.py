import re
from collections import defaultdict
from collections.abc import Iterable

import discord

DECORATION = re.compile(r"[^\w\s.'-]")
UNRESOLVED_MENTION = re.compile(r"(?<![\w<])@([^\s@<>]{2,32})")
TRAILING_PUNCTUATION = ".,!?:;)'\""
UNPINGABLE_NAMES = {"everyone", "here"}
MIN_FIRST_WORD_ALIAS_LENGTH = 3


def simplify_name(name: str) -> str:
    """'stray ✦' -> 'stray', 'Mira 🌸' -> 'mira': what people actually type after the @."""
    return " ".join(DECORATION.sub(" ", name).split()).lower()


def name_aliases(names: Iterable[str | None]) -> set[str]:
    aliases = set()
    for name in names:
        if not name:
            continue
        aliases.add(name.lower())
        simplified = simplify_name(name)
        if simplified:
            aliases.add(simplified)
            first_word = simplified.split()[0]
            if len(first_word) >= MIN_FIRST_WORD_ALIAS_LENGTH:
                aliases.add(first_word)
    return aliases


def unique_aliases(aliases_by_user_id: dict[int, set[str]]) -> dict[str, int]:
    """Drops any alias shared by two people, so an ambiguous @name never pings the wrong person."""
    owner_ids_by_alias: defaultdict[str, set[int]] = defaultdict(set)
    for user_id, aliases in aliases_by_user_id.items():
        for alias in aliases:
            owner_ids_by_alias[alias].add(user_id)
    return {alias: next(iter(owner_ids)) for alias, owner_ids in owner_ids_by_alias.items()
            if len(owner_ids) == 1 and alias not in UNPINGABLE_NAMES}


def mentionable_people(history: Iterable[discord.Message | None], bot_user_id: int) -> dict[str, int]:
    aliases_by_user_id: defaultdict[int, set[str]] = defaultdict(set)
    for past_message in history:
        if past_message is None:
            continue
        for person in [past_message.author, *past_message.mentions]:
            if person.id != bot_user_id:
                aliases_by_user_id[person.id] |= name_aliases(
                    (person.name, getattr(person, "global_name", None), person.display_name))
    return unique_aliases(aliases_by_user_id)


def link_mentions(text: str, user_id_by_name: dict[str, int]) -> str:
    if not user_id_by_name:
        return text
    # Longest names first, so "@Big Bob" isn't claimed by a user called "Big".
    names = sorted(user_id_by_name, key=len, reverse=True)
    mention_pattern = re.compile(r"(?<!\w)@(" + "|".join(re.escape(name) for name in names) + r")(?!\w)",
                                 re.IGNORECASE)
    return mention_pattern.sub(lambda match: f"<@{user_id_by_name[match.group(1).lower()]}>", text)


def unresolved_mention_names(text: str) -> list[str]:
    names = []
    for match in UNRESOLVED_MENTION.finditer(text):
        name = match.group(1).rstrip(TRAILING_PUNCTUATION)
        if name and name.lower() not in UNPINGABLE_NAMES and name not in names:
            names.append(name)
    return names


def unique_member_id_from_search(search_results: list[dict], typed_name: str) -> int | None:
    aliases_by_user_id = {
        int(result["user"]["id"]): name_aliases(
            (result["user"]["username"], result["user"].get("global_name"), result.get("nick")))
        for result in search_results if not result["user"].get("bot")
    }
    return unique_aliases(aliases_by_user_id).get(typed_name.lower())
