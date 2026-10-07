import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

import aiohttp
import discord
from discord import app_commands
from discord.http import Route

from tasque.bedtime_filter import is_bedtime_talk
from tasque.character import Character
from tasque.context import HISTORY_GAP, select_context
from tasque.followup_judge import (build_decision_request, build_judge_prompt, parse_judge_verdict,
                                   reply_probability)
from tasque.memory_cutoffs import MemoryCutoffs
from tasque.mentions import (link_mentions, mentionable_people, unique_member_id_from_search,
                             unresolved_mention_names)
from tasque.message_splitter import DISCORD_MESSAGE_LIMIT, split_into_messages
from tasque.openrouter import OpenRouterClient, OpenRouterError
from tasque.prompt import build_prompt, clean_reply
from tasque.settings import Settings

log = logging.getLogger("tasque")

SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)
FOLLOWUP_JUDGE_CONTEXT_BEFORE_HER_MESSAGE = 4
REPLY_ATTEMPTS = 2


class CharacterBot(discord.Client):
    def __init__(self, settings: Settings, character: Character, llm: OpenRouterClient,
                 memory_cutoffs: MemoryCutoffs):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.character = character
        self.llm = llm
        self.memory_cutoffs = memory_cutoffs
        self.channel_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_spoke_at: dict[int, datetime] = {}
        self.judged_follow_up_ids: set[int] = set()
        self.newest_waiting_ids: dict[int, int] = {}
        alternation = "|".join(re.escape(name) for name in settings.trigger_names)
        self.name_trigger = re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)
        self.tree = app_commands.CommandTree(self)
        self._register_commands()

    async def setup_hook(self) -> None:
        await self.llm.open()
        synced_commands = await self.tree.sync()
        log.info("Synced slash commands: %s", ", ".join(f"/{command.name}" for command in synced_commands))

    def _register_commands(self) -> None:
        character_name = self.character.name

        @self.tree.command(name="lobotomise", description=f"Wipe {character_name}'s memory of this channel")
        async def lobotomise(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                f"🧠 *{character_name} has been lobotomised. She remembers nothing before this point.*")
            # The cutoff is the announcement itself, so she doesn't "remember" being lobotomised either.
            announcement = await interaction.original_response()
            self.memory_cutoffs.set(interaction.channel_id, announcement.id)
            log.info("%s wiped memory in channel %s", interaction.user, interaction.channel_id)

        @self.tree.command(name="say", description=f"Make {character_name} say exactly this")
        @app_commands.describe(text=f"What {character_name} should say")
        @app_commands.default_permissions(manage_messages=True)
        @app_commands.guild_only()
        async def say(interaction: discord.Interaction,
                      text: app_commands.Range[str, 1, DISCORD_MESSAGE_LIMIT]) -> None:
            try:
                await interaction.channel.send(text, allowed_mentions=SAFE_MENTIONS)
            except discord.HTTPException:
                await interaction.response.send_message("I can't post in this channel.", ephemeral=True)
                return
            await interaction.response.send_message("Sent.", ephemeral=True)
            log.info("%s used /say in channel %s", interaction.user, interaction.channel_id)

    async def close(self) -> None:
        await self.llm.close()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Logged in as %s, playing %s", self.user, self.character.name)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == self.user.id:
            self.last_spoke_at[message.channel.id] = message.created_at
            return
        if message.author.bot and not self.settings.respond_to_bots:
            return

        addressed = self._is_addressed(message)
        if not addressed and not self._spoke_recently(message):
            return
        channel_lock = self.channel_locks[message.channel.id]
        # Messages arriving while she's mid-reply aren't judged; they still reach her as context next time.
        if not addressed and channel_lock.locked():
            return
        if addressed:
            self.newest_waiting_ids[message.channel.id] = message.id

        async with channel_lock:
            # A newer message queued behind this one will see it as context, so one reply covers both.
            if addressed and self.newest_waiting_ids.get(message.channel.id) != message.id:
                log.info("Skipping superseded message from %s: %.80r", message.author.display_name,
                         message.clean_content)
                return
            try:
                if addressed or await self._judge_follow_up(message):
                    await self._respond(message)
            except OpenRouterError:
                log.exception("OpenRouter request failed")
            except discord.HTTPException:
                log.exception("Discord rejected a message")

    def _spoke_recently(self, message: discord.Message) -> bool:
        if not self.settings.followup_enabled:
            return False
        last_spoke_at = self.last_spoke_at.get(message.channel.id)
        return last_spoke_at is not None and (
            message.created_at - last_spoke_at <= timedelta(minutes=self.settings.followup_window_minutes))

    async def _judge_follow_up(self, message: discord.Message) -> bool:
        memory_cutoff_id = self.memory_cutoffs.get(message.channel.id)
        recent_newest_first = []
        judge_context_limit = self.settings.followup_window_messages + FOLLOWUP_JUDGE_CONTEXT_BEFORE_HER_MESSAGE
        async for past in message.channel.history(limit=judge_context_limit, before=message):
            if memory_cutoff_id is not None and past.id <= memory_cutoff_id:
                break
            recent_newest_first.append(past)

        own_message_positions = [position for position, past in enumerate(recent_newest_first)
                                 if past.author.id == self.user.id]
        if not own_message_positions or own_message_positions[0] >= self.settings.followup_window_messages:
            return False

        transcript = list(reversed(recent_newest_first)) + [message]
        verdict = await self._decide_follow_up(transcript)
        should_reply = verdict >= self.settings.followup_reply_threshold
        if should_reply:
            self.judged_follow_up_ids.add(message.id)
        log.info("Follow-up judge said %s (%.2f) to %s: %.80r", "YES" if should_reply else "NO", verdict,
                 message.author.display_name, message.clean_content)
        return should_reply

    async def _decide_follow_up(self, transcript: list[discord.Message]) -> float:
        judge_model = self.settings.followup_judge_model
        if judge_model:
            state, questions = build_decision_request(self.character.name, transcript, self.user)
            try:
                return reply_probability(await self.llm.decide(judge_model, state, questions))
            except (OpenRouterError, aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError):
                log.warning("%s judge failed, falling back to the main model", judge_model, exc_info=True)
        raw_verdict = await self.llm.complete(build_judge_prompt(self.character.name, transcript, self.user),
                                              temperature=0, max_tokens=5)
        return 1.0 if parse_judge_verdict(raw_verdict) else 0.0

    def _is_addressed(self, message: discord.Message) -> bool:
        if self.user in message.mentions:
            return True
        referenced = message.reference.resolved if message.reference else None
        if isinstance(referenced, discord.Message) and referenced.author.id == self.user.id:
            return True
        return bool(self.name_trigger.search(message.content))

    def _is_conversation_message(self, message: discord.Message) -> bool:
        return (message.author.id == self.user.id or message.id in self.judged_follow_up_ids
                or self._is_addressed(message))

    async def _respond(self, message: discord.Message) -> None:
        channel = message.channel
        memory_cutoff_id = self.memory_cutoffs.get(channel.id)
        async with channel.typing():
            newest_first = [message]
            async for past in channel.history(limit=self.settings.history_scan_limit, before=message):
                if memory_cutoff_id is not None and past.id <= memory_cutoff_id:
                    break
                newest_first.append(past)
            history = select_context(newest_first, self._is_conversation_message,
                                     self.settings.conversation_history_limit, self.settings.recent_history_limit)
            prompt = build_prompt(self.character, history, self.user, message.author.display_name,
                                  hide_own_bedtime_talk=self.settings.filter_bedtime_talk)
            participant_names = {past.author.display_name for past in history
                                 if past is not HISTORY_GAP and past.author.id != self.user.id}
            for _attempt in range(REPLY_ATTEMPTS):
                raw_reply = await self.llm.complete(prompt)
                chunks = self._reply_chunks(raw_reply, participant_names)
                if chunks:
                    break
                log.warning("Model returned nothing usable: %r", raw_reply)
            else:
                return

        people_in_chat = mentionable_people(newest_first, self.user.id)
        chunks = [await self._link_server_members(link_mentions(chunk, people_in_chat), message.guild)
                  for chunk in chunks]

        for chunk_index, chunk in enumerate(chunks):
            if chunk_index > 0:
                async with channel.typing():
                    await asyncio.sleep(self._typing_delay(chunk))
            reply_reference = message.to_reference(fail_if_not_exists=False) if chunk_index == 0 else None
            await channel.send(chunk, reference=reply_reference, allowed_mentions=SAFE_MENTIONS)

    def _reply_chunks(self, raw_reply: str, participant_names: set[str]) -> list[str]:
        reply = clean_reply(raw_reply, self.character.name, participant_names)
        chunks = split_into_messages(reply, self.settings.max_messages_per_reply,
                                     self.settings.drop_trailing_periods)
        if not self.settings.filter_bedtime_talk:
            return chunks
        dropped = [chunk for chunk in chunks if is_bedtime_talk(chunk)]
        if dropped:
            log.info("Dropped bedtime talk: %r", dropped)
        return [chunk for chunk in chunks if not is_bedtime_talk(chunk)]

    async def _link_server_members(self, reply: str, guild: discord.Guild | None) -> str:
        if guild is None:
            return reply
        for typed_name in unresolved_mention_names(reply):
            # discord.py has no wrapper for this endpoint; unlike query_members it also matches global display names.
            search_route = Route("GET", "/guilds/{guild_id}/members/search", guild_id=guild.id)
            try:
                search_results = await self.http.request(search_route, params={"query": typed_name, "limit": 10})
            except discord.HTTPException:
                log.warning("Member search failed for @%s", typed_name)
                continue
            member_id = unique_member_id_from_search(search_results, typed_name)
            if member_id is None:
                log.info("No unique member for @%s, leaving it as text", typed_name)
                continue
            reply = link_mentions(reply, {typed_name.lower(): member_id})
        return reply

    def _typing_delay(self, chunk: str) -> float:
        natural_delay = len(chunk) * self.settings.typing_seconds_per_char
        return min(self.settings.max_typing_seconds, max(self.settings.min_typing_seconds, natural_delay))
