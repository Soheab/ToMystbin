"""
Copyright 2024-2024 Mysty<evieepy@gmail.com> ;
Copyright 2026-present Soheab

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations
import datetime
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
import mystbin

from utils import LRUCache, CodeBlocks, MBPasteView

if TYPE_CHECKING:
    from main import MystbinBot


ALLOWED_INSTALL: app_commands.AppInstallationType = app_commands.AppInstallationType(
    user=True, guild=True
)
ALLOWED_CONTEXT: app_commands.AppCommandContext = app_commands.AppCommandContext(
    guild=True,
    dm_channel=True,
    private_channel=True,
)
MYSTBIN_API: str = "https://mystb.in/api/paste"
MYSTBIN_URL: str = "https://mystb.in/"


class TempPaste:
    def __init__(self, *, id: str, last_edit: datetime.datetime | None) -> None:
        self.id: str = id
        self.last_edit: datetime.datetime | None = last_edit


class MystBin(commands.Cog):
    def __init__(self, bot: MystbinBot) -> None:
        self.bot: MystbinBot = bot
        self.ctxmenu: app_commands.ContextMenu = app_commands.ContextMenu(
            name="Message to MystBin",
            callback=self.convert_mystbin,
            allowed_installs=ALLOWED_INSTALL,
            allowed_contexts=ALLOWED_CONTEXT,
        )

        self._cache: LRUCache[int, TempPaste] = LRUCache(50)

    async def cog_load(self) -> None:
        self.ctxmenu.on_error = self.mystbin_error
        self.bot.tree.add_command(self.ctxmenu)
        self.session = aiohttp.ClientSession()

    async def cog_unload(self) -> None:
        if self.session:
            try:
                await self.session.close()
            finally:
                self.session = None

        self.bot.tree.remove_command(self.ctxmenu.name, type=self.ctxmenu.type)

    # @commands.hybrid_command()
    # @app_commands.allowed_installs(guilds=True, users=True)
    # async def mystbin(self, context: commands.Context[MystbinBot], *, content: str) -> None: ...

    @app_commands.checks.cooldown(2, 10.0)
    async def convert_mystbin(
        self, interaction: discord.Interaction[MystbinBot], message: discord.Message
    ) -> None:
        assert self.session
        await interaction.response.defer()

        if (
            await self.bot.is_blocked(message.id)
            and message.author.id != interaction.user.id
        ):
            msg = f"{message.author.mention} has blocked this message from being added to MystBin."
            await interaction.followup.send(
                msg,
                allowed_mentions=discord.AllowedMentions.none(),
                silent=True,
                ephemeral=True,
            )
            return

        cached = self._cache.get(message.id)
        if cached and cached.last_edit == message.edited_at:
            try:
                paste = await self.bot.fetch_paste(cached.id)
            except aiohttp.ClientResponseError as e:
                if e.status != 404:
                    await interaction.followup.send(
                        f"An unknown error occurred fetching this paste: `{e.status}`"
                    )
                    return
            else:
                await interaction.followup.send(paste.url)
                return

        parsed: CodeBlocks = CodeBlocks.convert(message.content)
        files: list[mystbin.File] = []
        content: str

        for attachment in message.attachments:
            content_type: str = attachment.content_type or "text/"

            if content_type.startswith("text/") or content_type == "application/json":
                content = (await attachment.read()).decode("UTF-8")
                filename: str = attachment.filename.removesuffix(".txt")

                files.append(mystbin.File(filename=filename, content=content[:300_000]))

        for index, block in enumerate(parsed.blocks, 1):
            name = f"block_{index}.{block['language'] or 'txt'}"
            files.append(mystbin.File(filename=name, content=block["content"]))

        if len(files) < 5:
            content = (
                f"{message.author}({message.author.id}) in {message.channel}({message.channel.id})\n"
                f"{message.created_at}\n\n{message.content}"
            )
            files.append(mystbin.File(filename=f"{message.id}.txt", content=content))

        try:
            paste = await self.bot.api_client.create_paste(files=files[:5])
        except aiohttp.ClientResponseError as e:
            await interaction.followup.send(
                f"An error occurred creating this paste: `{e.status}`"
            )
            return
        identifier: str = paste.id
        url: str = paste.url
        token: str | None = paste.security_token

        node = TempPaste(id=identifier, last_edit=message.edited_at)
        self._cache[message.id] = node
        view: MBPasteView = MBPasteView(self.bot, paste_id=identifier)

        msg = (
            f"{message.author.mention} your message was shared on [MystBin]({url}).\n"
            "You may delete this data at any time using the button below."
        )

        new = await interaction.followup.send(msg, view=view, wait=True)
        await self.bot.insert_paste_to_db(
            paste=paste,
            user_id=new.author.id,
            message_id=new.id,
            safety_token=token,  # type: ignore
        )

    async def mystbin_error(
        self,
        interaction: discord.Interaction[MystbinBot],
        error: app_commands.AppCommandError,
    ) -> None:
        send = interaction.response.send_message
        if interaction.response.is_done():
            send = interaction.followup.send

        await send(f"An error occurred: {error}", ephemeral=True)


async def setup(bot: MystbinBot) -> None:
    await bot.add_cog(MystBin(bot))
