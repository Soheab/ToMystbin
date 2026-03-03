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
import pathlib
from typing import TYPE_CHECKING, Any, Self

from discord import ui
import discord

import tomllib

if TYPE_CHECKING:
    from ._types import CodeBlock
    from main import MystbinBot


class LRUCache[K, V]:
    def __init__(self, capacity: int) -> None:
        self.capacity: int = capacity
        self.cache: dict[K, V] = {}
        self.order: list[K] = []

    def __contains__(self, key: object) -> bool:
        return key in self.cache

    def __getitem__(self, key: K) -> V:
        if key not in self.cache:
            raise KeyError(key)

        self.order.remove(key)
        self.order.append(key)
        return self.cache[key]

    def __setitem__(self, key: K, value: V) -> None:
        self.put(key, value)

    def __delitem__(self, key: K) -> None:
        if key not in self.cache:
            raise KeyError(key)

        del self.cache[key]
        self.order.remove(key)

    def __len__(self) -> int:
        return len(self.cache)

    def get[D: Any = None](self, key: K, default: D | None = None) -> V | D | None:
        try:
            return self[key]
        except KeyError:
            return default

    def put(self, key: K, value: V) -> None:
        if key in self.cache:
            self.order.remove(key)
        elif len(self.cache) >= self.capacity:
            oldest_key = self.order.pop(0)
            del self.cache[oldest_key]
        self.cache[key] = value
        self.order.append(key)


class CodeBlocks:
    def __init__(self, blocks: list[CodeBlock]) -> None:
        self.blocks: list[CodeBlock] = blocks

    @classmethod
    def convert(cls, content: str) -> Self:
        splat: list[str] = content.split("\n")

        in_block: bool = False
        lang: str | None = None
        lines: list[str] = []
        blocks: list[CodeBlock] = []

        for line in splat:
            if in_block and "```" not in line:
                lines.append(line)

            elif not in_block and "```" in line:
                lang = line[line.index("`") :].split()[0].strip("```") or None
                line = line.replace("```", "", 1)

                if "```" in line:
                    data = line.replace("```", "")

                    if data:
                        blocks.append({"language": None, "content": data})

                    lang = None
                    lines = []
                    continue

                in_block = True

            elif in_block and "```" in line:
                if not lines:
                    continue

                joined: str = "\n".join(lines)
                blocks.append({"language": lang, "content": joined})

                lang = None
                lines = []

                in_block = False

        return cls(blocks)


class ConfirmView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)
        self.result: bool | None = None

    @ui.button(label="Yes", style=discord.ButtonStyle.green)
    async def yes(
        self, interaction: discord.Interaction[MystbinBot], button: ui.Button[Self]
    ) -> None:
        self.result = True
        self.stop()

    @ui.button(label="No", style=discord.ButtonStyle.red)
    async def no(
        self, interaction: discord.Interaction[MystbinBot], button: ui.Button[Self]
    ) -> None:
        self.result = False
        self.stop()


class MBPasteView(ui.View):
    def __init__(self, bot: MystbinBot, *, paste_id: str = "") -> None:
        self.bot: MystbinBot = bot
        self.paste_id: str = paste_id

        super().__init__(timeout=None)

        url_button: ui.Button[Self] = ui.Button(
            label="View Paste", url=f"https://mystbin.abstractumbra.dev/{paste_id}"
        )
        del_button: ui.Button[Self] = ui.Button(
            label="Delete", style=discord.ButtonStyle.red, custom_id=f"d_{paste_id}"
        )
        del_button.callback = self.del_callback

        self.add_item(url_button)
        self.add_item(del_button)

    async def del_callback(self, interaction: discord.Interaction[MystbinBot]) -> None:
        await interaction.response.defer(ephemeral=True)

        paste = await self.bot.fetch_paste_from_db(
            id=self.paste_id,
        )
        if not paste:
            await interaction.followup.send(
                "Only the message author may delete this paste.", ephemeral=True
            )
            return

        confirm: ConfirmView = ConfirmView()
        confmsg = (
            "Are you sure you would like to remove this paste? **This action can not be undone.**\n\n"
            "- No one will be able to send this message to MystBin in the future!\n"
            "- If you are worried about tokens: MystBin automatically invalidates all tokens from `Discord`, `Github` and `PyPi`\n"
            "- Someone may have been viewing this paste to assist you; make sure to let them know you removed your paste.\n\n"
        )
        await interaction.followup.send(confmsg, view=confirm, ephemeral=True)
        await confirm.wait()

        if not confirm.result:
            return

        try:
            await self.bot.delete_paste(paste)
        except Exception as e:
            await interaction.followup.send(
                f"An unexpected error occurred, please try again: {e}", ephemeral=True
            )
            return

        await interaction.followup.send(
            "Successfully removed this paste and data.", ephemeral=True
        )
        await interaction.delete_original_response()


if TYPE_CHECKING:

    class ConfigParsedBot:
        token: str

    class ConfigParsedMystbin:
        root_url: str

    class ConfigParsedDB:
        filename: str


class ConfigParsed:
    bot: ConfigParsedBot
    mystbin: ConfigParsedMystbin
    db: ConfigParsedDB

    def __init__(self, file: pathlib.Path) -> None:
        self._data: dict[str, Any] = tomllib.load(file.open("rb"))
        self.__recusive_set_from_dict(self._data)

    def __recusive_set_from_dict(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, type("Config", (), value)())  # pyright: ignore[reportUnknownArgumentType]
                self.__recusive_set_from_dict(value)  # pyright: ignore[reportUnknownArgumentType]
            else:
                setattr(self, key, value)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]
