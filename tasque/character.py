import base64
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHAR_MACRO = re.compile(r"\{\{char\}\}|<BOT>", re.IGNORECASE)
USER_MACRO = re.compile(r"\{\{user\}\}|<USER>", re.IGNORECASE)


@dataclass
class Character:
    name: str
    system_prompt: str
    post_history_instructions: str = ""

    def render(self, template: str, user_name: str) -> str:
        with_char = CHAR_MACRO.sub(lambda _: self.name, template)
        return USER_MACRO.sub(lambda _: user_name, with_char)


def load_character(path: Path, fallback_name: str) -> Character:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return _character_from_card(_read_png_card(path), fallback_name)
    if suffix == ".json":
        return _character_from_card(json.loads(path.read_text(encoding="utf-8")), fallback_name)
    if suffix == ".toml":
        return _character_from_card(tomllib.loads(path.read_text(encoding="utf-8")), fallback_name)
    return Character(name=fallback_name, system_prompt=path.read_text(encoding="utf-8").strip())


def _character_from_card(card: dict, fallback_name: str) -> Character:
    fields = card.get("data", card)
    name = fields.get("name") or fallback_name

    sections = [
        fields.get("system_prompt", "").replace("{{original}}", ""),
        fields.get("description", ""),
        _labeled("{{char}}'s personality", fields.get("personality", "")),
        _labeled("Scenario", fields.get("scenario", "")),
        _labeled("Example messages", fields.get("mes_example", "")),
    ]
    system_prompt = "\n\n".join(section.strip() for section in sections if section.strip())
    return Character(
        name=name,
        system_prompt=system_prompt,
        post_history_instructions=fields.get("post_history_instructions", "").strip(),
    )


def _labeled(label: str, body: str) -> str:
    return f"{label}:\n{body}" if body.strip() else ""


def _read_png_card(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG file")

    text_chunks: dict[str, bytes] = {}
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        chunk_type = data[position + 4:position + 8]
        body = data[position + 8:position + 8 + length]
        position += 12 + length
        if chunk_type == b"tEXt":
            keyword, _, value = body.partition(b"\0")
            text_chunks[keyword.decode("latin-1").lower()] = value

    encoded_card = text_chunks.get("ccv3") or text_chunks.get("chara")
    if encoded_card is None:
        raise ValueError(f"{path} has no embedded character card")
    return json.loads(base64.b64decode(encoded_card).decode("utf-8"))
