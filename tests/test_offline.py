import base64
import json
import struct
import zlib

from tasque.character import load_character
from tasque.message_splitter import split_into_messages
from tasque.prompt import clean_reply


def test_outline_example_splits_per_sentence():
    assert split_into_messages("I'm cool. What about you? I think.", 6) == [
        "I'm cool.", "What about you?", "I think."]


def test_drop_trailing_periods_keeps_ellipses():
    assert split_into_messages("I'm cool. well...", 6, drop_trailing_periods=True) == ["I'm cool", "well..."]


def test_abbreviations_decimals_and_urls_stay_whole():
    text = "Dr. Who is 3.5 times cooler, see https://x.com/a.b ok."
    assert split_into_messages(text, 6) == [text]


def test_newlines_split_and_code_blocks_stay_intact():
    text = "look\n```py\nx = 1. y = 2\n```\ndone!"
    assert split_into_messages(text, 6) == ["look", "```py\nx = 1. y = 2\n```", "done!"]


def test_overflow_folds_into_last_message():
    assert split_into_messages("a. b. c. d.", 2) == ["a.", "b. c. d."]


def test_long_piece_respects_discord_limit():
    chunks = split_into_messages("word " * 900, 6)
    assert all(len(chunk) <= 2000 for chunk in chunks) and len(chunks) == 3


def test_clean_reply_strips_own_name_and_impersonation():
    raw = "<think>hmm</think>Nell: hey\nwhat's up\nBob: I'm fine"
    assert clean_reply(raw, "Nell", {"Bob"}) == "hey\nwhat's up"


def test_clean_reply_strips_own_name_on_every_line():
    raw = "homework\nNell: so mostly staring at it\nnell: might go out later"
    assert clean_reply(raw, "Nell", {"Bob"}) == "homework\nso mostly staring at it\nmight go out later"


def test_png_card_loads_and_renders_macros(tmp_path):
    card = {"spec": "chara_card_v2", "data": {
        "name": "Nell", "description": "{{char}} teases {{user}}.", "personality": "dry",
        "post_history_instructions": "stay short"}}
    encoded = base64.b64encode(json.dumps(card).encode())

    def png_chunk(chunk_type: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + chunk_type + body + struct.pack(">I", zlib.crc32(chunk_type + body))

    png = (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + png_chunk(b"tEXt", b"chara\0" + encoded) + png_chunk(b"IEND", b""))
    card_path = tmp_path / "card.png"
    card_path.write_bytes(png)

    character = load_character(card_path, "Fallback")
    assert character.name == "Nell"
    assert character.render(character.system_prompt, "Bob").startswith("Nell teases Bob.")
    assert character.post_history_instructions == "stay short"


def test_toml_character_keeps_sillytavern_field_order(tmp_path):
    character_path = tmp_path / "nell.toml"
    character_path.write_text('''
name = "Nell"
system_prompt = "PRE"
description = "DESC"
personality = "PERS"
scenario = ""
mes_example = "{{user}}: hi"
post_history_instructions = "POST"
''', encoding="utf-8")

    character = load_character(character_path, "Fallback")
    rendered = character.render(character.system_prompt, "Bob")
    positions = [rendered.index(marker) for marker in ("PRE", "DESC", "PERS", "Example messages:\nBob: hi")]
    assert positions == sorted(positions)
    assert "Scenario:" not in rendered
    assert character.post_history_instructions == "POST"


def test_context_keeps_recent_plus_conversation_with_gaps():
    from tasque.context import HISTORY_GAP, select_context
    # newest first; "A" marks a message to/from Nell
    channel = ["now", "r1", "r2", "x1", "A-new", "x2", "x3", "A-mid", "x4", "A-old", "A-oldest"]
    selected = select_context(channel, lambda message: message.startswith("A"),
                              conversation_limit=3, recent_limit=3)
    assert selected == ["A-old", HISTORY_GAP, "A-mid", HISTORY_GAP, "A-new", HISTORY_GAP, "r2", "r1", "now"]


def test_context_without_gaps_when_everything_is_adjacent():
    from tasque.context import select_context
    selected = select_context(["c", "b", "a"], lambda message: True, conversation_limit=50, recent_limit=10)
    assert selected == ["a", "b", "c"]


def test_prompt_marks_skipped_messages():
    from types import SimpleNamespace
    from tasque.character import Character
    from tasque.context import HISTORY_GAP
    from tasque.prompt import build_prompt

    def message(author_id, name, text):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, display_name=name), reference=None,
                               clean_content=text, attachments=[], stickers=[])

    history = [message(2, "Bob", "nell hi"), message(1, "Nell", "hey"), HISTORY_GAP, message(3, "Mira", "lol")]
    prompt = build_prompt(Character("Nell", "sys"), history, SimpleNamespace(id=1), "Mira")
    assert [turn["role"] for turn in prompt] == ["system", "user", "assistant", "user"]
    assert prompt[-1]["content"] == "[skipped messages]\nMira: lol"


def test_memory_cutoffs_persist_across_restarts(tmp_path):
    from tasque.memory_cutoffs import MemoryCutoffs
    store_path = tmp_path / "data" / "memory_cutoffs.json"
    MemoryCutoffs(store_path).set(111, 999)
    reloaded = MemoryCutoffs(store_path)
    assert reloaded.get(111) == 999
    assert reloaded.get(222) is None


def test_judge_verdict_parsing():
    from tasque.followup_judge import parse_judge_verdict
    assert parse_judge_verdict("YES")
    assert parse_judge_verdict(" yes.\n")
    assert parse_judge_verdict("<think>hmm, no idea</think>Yes")
    assert not parse_judge_verdict("NO")
    assert not parse_judge_verdict("")
    assert not parse_judge_verdict("Nope, yes")


def test_judge_prompt_labels_speakers_and_newest_message():
    from types import SimpleNamespace
    from tasque.followup_judge import build_judge_prompt

    def message(author_id, name, text):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, display_name=name), reference=None,
                               clean_content=text, attachments=[], stickers=[])

    transcript = [message(1, "NellBot", "what kind of math"), message(2, "Bob", "derivatives")]
    prompt = build_judge_prompt("Nell", transcript, SimpleNamespace(id=1))
    assert "Nell: what kind of math\nBob: derivatives" in prompt[1]["content"]
    assert prompt[1]["content"].endswith("Newest message:\nBob: derivatives\n\nShould Nell reply to the newest message?")


def test_link_mentions_turns_known_names_into_pings():
    from tasque.mentions import link_mentions
    people = {"bob": 20, "big bob": 21, "mira": 30}
    assert link_mentions("@Bob go to sleep", people) == "<@20> go to sleep"
    assert link_mentions("ask @big bob", people) == "ask <@21>"
    assert link_mentions("@Bobby and @kai and @everyone", people) == "@Bobby and @kai and @everyone"
    assert link_mentions("@mira, @MIRA.", people) == "<@30>, <@30>."
    assert link_mentions("email me@bob.com", people) == "email me@bob.com"


def _person(user_id, username, display_name, global_name=None):
    from types import SimpleNamespace
    return SimpleNamespace(id=user_id, name=username, global_name=global_name, display_name=display_name)


def test_mentionable_people_collects_authors_and_mentions_but_not_the_bot():
    from types import SimpleNamespace
    from tasque.mentions import mentionable_people

    bob, mira, nell = _person(20, "bob_99", "Bob"), _person(30, "mira.x", "Mira"), _person(1, "nell", "Nell")
    history = [SimpleNamespace(author=bob, mentions=[mira, nell]), None, SimpleNamespace(author=nell, mentions=[])]
    people = mentionable_people(history, bot_user_id=1)
    assert people["bob"] == people["bob_99"] == 20
    assert people["mira"] == people["mira.x"] == 30
    assert "nell" not in people


def test_decorated_names_ping_by_their_plain_form():
    from types import SimpleNamespace
    from tasque.mentions import link_mentions, mentionable_people

    stray = _person(40, "traumt", "stray ✦", global_name="stray ✦")
    lily = _person(50, "lily_x", "🌸 Lily Moon 🌸")
    people = mentionable_people([SimpleNamespace(author=stray, mentions=[lily])], bot_user_id=1)
    assert link_mentions("@stray get over here", people) == "<@40> get over here"
    assert link_mentions("@stray ✦ hi", people) == "<@40> hi"
    assert link_mentions("@lily moon and @Lily", people) == "<@50> and <@50>"


def test_shared_first_word_is_ambiguous_and_never_pings():
    from types import SimpleNamespace
    from tasque.mentions import link_mentions, mentionable_people

    people = mentionable_people([SimpleNamespace(author=_person(20, "a1", "Big Bob"),
                                                 mentions=[_person(21, "a2", "Big Ben")])], bot_user_id=1)
    assert link_mentions("@big what", people) == "@big what"
    assert link_mentions("@big ben what", people) == "<@21> what"


def test_unresolved_mention_names_skips_linked_and_everyone():
    from tasque.mentions import unresolved_mention_names
    text = "<@20> hey @stray, and @Kai! also @everyone @here me@mail.com @stray"
    assert unresolved_mention_names(text) == ["stray", "Kai"]


def test_member_search_result_needs_a_unique_human_match():
    from tasque.mentions import unique_member_id_from_search
    stray = {"user": {"id": "40", "username": "traumt", "global_name": "stray ✦"}, "nick": None}
    strayhound = {"user": {"id": "41", "username": "strayhound", "global_name": None}, "nick": None}
    stray_bot = {"user": {"id": "42", "username": "stray", "global_name": None, "bot": True}, "nick": None}
    assert unique_member_id_from_search([stray, strayhound, stray_bot], "stray") == 40
    assert unique_member_id_from_search([strayhound], "stray") is None
    assert unique_member_id_from_search([], "stray") is None


def test_queued_pings_collapse_into_one_reply_to_the_newest():
    import asyncio
    from collections import defaultdict
    from types import SimpleNamespace
    from tasque.bot import CharacterBot

    answered = []

    async def respond(message):
        await asyncio.sleep(0.05)
        answered.append(message.id)

    bot = SimpleNamespace(user=SimpleNamespace(id=1), settings=SimpleNamespace(respond_to_bots=False),
                          channel_locks=defaultdict(asyncio.Lock), newest_waiting_ids={},
                          replies_to_bots_since_human=defaultdict(int), log=SimpleNamespace(info=print),
                          _is_addressed=lambda message: True, _respond=respond)

    def ping(message_id):
        return SimpleNamespace(id=message_id, channel=SimpleNamespace(id=7), clean_content="nell",
                               author=SimpleNamespace(id=2, bot=False, display_name="Bob"))

    async def burst():
        first = asyncio.create_task(CharacterBot.on_message(bot, ping(100)))
        await asyncio.sleep(0.01)
        await asyncio.gather(first, *(CharacterBot.on_message(bot, ping(message_id)) for message_id in (101, 102, 103)))

    asyncio.run(burst())
    assert answered == [100, 103]


def test_decision_request_asks_jev_about_the_newest_message():
    from types import SimpleNamespace
    from tasque.followup_judge import build_decision_request, reply_probability

    def message(author_id, name, text):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, display_name=name), reference=None,
                               clean_content=text, attachments=[], stickers=[])

    transcript = [message(1, "NellBot", "what kind of math"), message(2, "Bob", "derivatives")]
    state, questions = build_decision_request("Nell", transcript, SimpleNamespace(id=1))
    assert state["chat_oldest_first"] == "Nell: what kind of math\nBob: derivatives"
    assert state["newest_message"] == "Bob: derivatives"
    assert questions["should_reply"]["type"] == "noul"
    assert "YES or NO" not in questions["should_reply"]["instructions"]
    assert reply_probability({"should_reply": {"type": "noul", "noul": 0.87}}) == 0.87


def test_bedtime_filter_drops_sleep_talk_but_not_normal_chat():
    from tasque.bedtime_filter import is_bedtime_talk
    for bedtime_line in ("i'm going to bed", "it's 2am", "go to sleep liam", "gn", "logging off", "it's late"):
        assert is_bedtime_talk(bedtime_line), bedtime_line
    for normal_line in ("curry", "i'm late for council", "what are you doing tonight", "my wrists are tired",
                        "gnarly", "i am not doing your homework"):
        assert not is_bedtime_talk(normal_line), normal_line


def test_prompt_hides_her_old_bedtime_messages():
    from types import SimpleNamespace
    from tasque.character import Character
    from tasque.prompt import build_prompt

    def message(author_id, name, text):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, display_name=name), reference=None,
                               clean_content=text, attachments=[], stickers=[])

    history = [message(1, "Nell", "it's 2am"), message(1, "Nell", "curry obviously"), message(2, "Bob", "nell hi")]
    prompt = build_prompt(Character("Nell", "sys"), history, SimpleNamespace(id=1), "Bob", hide_own_bedtime_talk=True)
    assert [turn["content"] for turn in prompt[1:]] == ["curry obviously", "Bob: nell hi"]


def test_settings_load_every_bot_with_shared_sections_and_overrides(tmp_path, monkeypatch):
    from tasque.settings import load_settings
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("DISCORD_TOKEN", "aoko-token")
    monkeypatch.delenv("DISCORD_TOKEN_ALICE", raising=False)
    (tmp_path / "config.toml").write_text('''
[model]
id = "shared-model"
temperature = 0.9
[messages]
max_messages_per_reply = 4

[[bots]]
character_file = "characters/aoko.toml"
character_name = "Aoko"
trigger_names = ["aoko"]

[[bots]]
character_file = "characters/alice.toml"
character_name = "Alice Kuonji"
trigger_names = ["alice"]
token_env = "DISCORD_TOKEN_ALICE"
bot_reply_limit = 1
[bots.model]
temperature = 0.7
''', encoding="utf-8")

    aoko, alice = load_settings(tmp_path)
    assert (aoko.bot_id, aoko.discord_token, aoko.temperature, aoko.bot_reply_limit) == ("aoko", "aoko-token", 0.9, 2)
    assert (alice.bot_id, alice.discord_token, alice.temperature, alice.model_id) == (
        "alice_kuonji", "", 0.7, "shared-model")
    assert alice.bot_reply_limit == 1 and alice.max_messages_per_reply == 4


def test_single_bot_table_still_loads(tmp_path, monkeypatch):
    from tasque.settings import load_settings
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    (tmp_path / "config.toml").write_text('''
[bot]
character_file = "characters/aoko.toml"
character_name = "Aoko"
trigger_names = ["aoko"]
[model]
id = "m"
[messages]
''', encoding="utf-8")
    [aoko] = load_settings(tmp_path)
    assert aoko.discord_token == "token" and aoko.bot_reply_limit == 2


def _bot_chat_harness(bot_reply_limit=2):
    import asyncio
    from collections import defaultdict
    from types import SimpleNamespace
    from tasque.bot import CharacterBot

    answered = []

    async def respond(message):
        answered.append(message.id)

    async def judge_yes(message, require_own_recent_message=True):
        return True

    bot = SimpleNamespace(user=SimpleNamespace(id=1), tasque_bot_ids={1, 9}, log=SimpleNamespace(info=print),
                          settings=SimpleNamespace(respond_to_bots=False, bot_reply_limit=bot_reply_limit),
                          channel_locks=defaultdict(asyncio.Lock), newest_waiting_ids={},
                          replies_to_bots_since_human=defaultdict(int), newest_bot_turn_ids={},
                          bot_turn_addressed_channels=set(), _is_addressed=lambda message: True,
                          _spoke_recently=lambda message: True, _judge_follow_up=judge_yes, _respond=respond)
    bot._may_answer_bots = lambda channel_id: CharacterBot._may_answer_bots(bot, channel_id)
    bot._on_bot_message = lambda message: CharacterBot._on_bot_message(bot, message)

    def post(message_id, author_id, is_bot):
        message = SimpleNamespace(id=message_id, channel=SimpleNamespace(id=7), clean_content="hey",
                                  author=SimpleNamespace(id=author_id, bot=is_bot, display_name="x"))
        return CharacterBot.on_message(bot, message)

    return bot, answered, post


def test_other_character_gets_two_answers_until_a_human_speaks(monkeypatch):
    import asyncio
    import tasque.bot
    monkeypatch.setattr(tasque.bot, "BOT_TURN_SETTLE_SECONDS", 0)
    _bot, answered, post = _bot_chat_harness()

    async def chat():
        for message_id in (1, 2, 3):
            await post(message_id, author_id=9, is_bot=True)
        await post(4, author_id=50, is_bot=False)
        await post(5, author_id=9, is_bot=True)

    asyncio.run(chat())
    assert answered == [1, 2, 4, 5]


def test_unknown_bots_are_ignored_unless_enabled(monkeypatch):
    import asyncio
    import tasque.bot
    monkeypatch.setattr(tasque.bot, "BOT_TURN_SETTLE_SECONDS", 0)
    _bot, answered, post = _bot_chat_harness()
    asyncio.run(post(1, author_id=77, is_bot=True))
    assert answered == []


def test_one_answer_per_burst_from_the_other_character(monkeypatch):
    import asyncio
    import tasque.bot
    monkeypatch.setattr(tasque.bot, "BOT_TURN_SETTLE_SECONDS", 0.05)
    bot, answered, post = _bot_chat_harness()

    async def burst():
        await asyncio.gather(post(1, 9, True), post(2, 9, True), post(3, 9, True))

    asyncio.run(burst())
    assert answered == [3] and bot.replies_to_bots_since_human[7] == 1


def test_only_the_character_who_spoke_last_judges_a_human_follow_up():
    from types import SimpleNamespace
    from tasque.bot import CharacterBot

    def message(author_id, is_bot):
        return SimpleNamespace(author=SimpleNamespace(id=author_id, bot=is_bot))

    aoko = SimpleNamespace(user=SimpleNamespace(id=1), tasque_bot_ids={1, 9},
                           settings=SimpleNamespace(followup_window_messages=16))
    human, alice = message(50, False), message(9, True)
    alice_spoke_after_aoko = [message(9, True), message(50, False), message(1, True)]
    aoko_spoke_last = [message(1, True), message(9, True)]
    assert not CharacterBot._spoke_last(aoko, alice_spoke_after_aoko, human)
    assert CharacterBot._spoke_last(aoko, aoko_spoke_last, human)
    assert CharacterBot._spoke_last(aoko, alice_spoke_after_aoko, alice)


def test_characters_called_together_answer_one_after_the_other():
    import asyncio
    from collections import defaultdict
    from types import SimpleNamespace
    from tasque.bot import CharacterBot

    events = []
    shared_channel_locks = defaultdict(asyncio.Lock)

    def character(user_id, name):
        async def respond(message):
            events.append(f"{name} starts")
            await asyncio.sleep(0.02)
            events.append(f"{name} done")

        return SimpleNamespace(user=SimpleNamespace(id=user_id), settings=SimpleNamespace(),
                               channel_locks=shared_channel_locks, newest_waiting_ids={},
                               replies_to_bots_since_human=defaultdict(int), log=SimpleNamespace(info=print),
                               _is_addressed=lambda message: True, _respond=respond)

    ping = SimpleNamespace(id=100, channel=SimpleNamespace(id=7), clean_content="aoko alice",
                           author=SimpleNamespace(id=50, bot=False, display_name="Bob"))
    aoko, alice = character(1, "aoko"), character(9, "alice")

    async def both_called():
        await asyncio.gather(CharacterBot.on_message(aoko, ping), CharacterBot.on_message(alice, ping))

    asyncio.run(both_called())
    assert events == ["aoko starts", "aoko done", "alice starts", "alice done"]
