import re

DISCORD_MESSAGE_LIMIT = 2000

CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]*_~]*(?=\s|$)")
TRAILING_WORD = re.compile(r"(\S+)$")
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "jr", "sr", "prof"}


def split_into_messages(text: str, max_messages: int, drop_trailing_periods: bool = False) -> list[str]:
    pieces: list[str] = []
    for segment, is_code in _code_aware_segments(text):
        if is_code:
            pieces.append(segment.strip())
            continue
        for line in segment.split("\n"):
            pieces.extend(_split_sentences(line))

    pieces = [piece for piece in pieces if piece]
    if drop_trailing_periods:
        pieces = [_drop_single_trailing_period(piece) for piece in pieces]
    pieces = _fold_overflow_into_last(pieces, max_messages)
    return [chunk for piece in pieces for chunk in _fit_discord_limit(piece)]


def _code_aware_segments(text: str):
    cursor = 0
    for code_match in CODE_BLOCK.finditer(text):
        yield text[cursor:code_match.start()], False
        yield code_match.group(), True
        cursor = code_match.end()
    yield text[cursor:], False


def _split_sentences(line: str) -> list[str]:
    sentences = []
    sentence_start = 0
    for boundary in SENTENCE_END.finditer(line):
        if _is_abbreviation(line[sentence_start:boundary.start()], boundary.group()):
            continue
        sentences.append(line[sentence_start:boundary.end()].strip())
        sentence_start = boundary.end()
    sentences.append(line[sentence_start:].strip())
    return [sentence for sentence in sentences if sentence]


def _is_abbreviation(text_before_punctuation: str, punctuation: str) -> bool:
    if punctuation != ".":
        return False
    trailing_word = TRAILING_WORD.search(text_before_punctuation)
    return bool(trailing_word) and trailing_word.group(1).lower() in ABBREVIATIONS


def _drop_single_trailing_period(piece: str) -> str:
    if piece.endswith(".") and not piece.endswith(".."):
        return piece[:-1]
    return piece


def _fold_overflow_into_last(pieces: list[str], max_messages: int) -> list[str]:
    if max_messages < 1 or len(pieces) <= max_messages:
        return pieces
    kept = pieces[:max_messages - 1]
    kept.append(" ".join(pieces[max_messages - 1:]))
    return kept


def _fit_discord_limit(piece: str) -> list[str]:
    chunks = []
    while len(piece) > DISCORD_MESSAGE_LIMIT:
        cut = piece.rfind(" ", 0, DISCORD_MESSAGE_LIMIT)
        if cut <= 0:
            cut = DISCORD_MESSAGE_LIMIT
        chunks.append(piece[:cut].rstrip())
        piece = piece[cut:].lstrip()
    chunks.append(piece)
    return chunks
