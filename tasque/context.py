from collections.abc import Callable, Sequence
from typing import TypeVar

MessageT = TypeVar("MessageT")

HISTORY_GAP = None


def select_context(newest_first: Sequence[MessageT], is_conversation_message: Callable[[MessageT], bool],
                   conversation_limit: int, recent_limit: int) -> list[MessageT | None]:
    """Oldest-first selection: the newest `recent_limit` messages plus up to `conversation_limit`
    conversation messages, with HISTORY_GAP wherever unselected messages were skipped."""
    chosen_indices = set(range(min(recent_limit, len(newest_first))))
    conversation_count = 0
    for index, message in enumerate(newest_first):
        if conversation_count >= conversation_limit:
            break
        if is_conversation_message(message):
            chosen_indices.add(index)
            conversation_count += 1

    selected: list[MessageT | None] = []
    previous_index = None
    for index in sorted(chosen_indices, reverse=True):
        if previous_index is not None and previous_index - index > 1:
            selected.append(HISTORY_GAP)
        selected.append(newest_first[index])
        previous_index = index
    return selected
