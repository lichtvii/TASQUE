import re

BEDTIME_TALK = re.compile(
    r"\b(?:bed|bedtime|sleep\w*|asleep|slept|naps?|good ?night|gn|log(?:ging)? off|heading out|gtg|gotta go"
    r"|midnight|\d{1,2}(?::\d{2})?\s?a\.?m"
    r"|(?:it'?s|so|too|getting|up|this|stay(?:ing)? up) late)\b",
    re.IGNORECASE)


def is_bedtime_talk(text: str) -> bool:
    return bool(BEDTIME_TALK.search(text))
