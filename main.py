from __future__ import annotations
import asyncio
import pathlib
from typing import TYPE_CHECKING, override

import aiohttp
import discord
from discord.ext import commands

from asqlite import Pool, create_pool
import mystbin

from utils import ConfigParsed

EXTENSION: list[str] = [
    "jishaku",
    "commands",
]

if TYPE_CHECKING:
    from mystbin import Paste

    from ._types import DBPaste, DBPasteBlock


class MystbinBot(commands.Bot):
    db: Pool

    @override
    def __init__(self, *, session: aiohttp.ClientSession) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents(
                messages=True,
                message_content=True,
                guilds=True,
            ),
            allowed_contexts=discord.app_commands.AppCommandContext(
                guild=True,
                dm_channel=False,
                private_channel=False,
            ),
            allowed_installs=discord.app_commands.AppInstallationType(
                user=True,
                guild=True,
            ),
        )
        self.session: aiohttp.ClientSession = session
        self.config: ConfigParsed = ConfigParsed(pathlib.Path("config.toml"))

        self.api_client: mystbin.Client = mystbin.Client(
            session=session, root_url=self.config.mystbin.root_url
        )

        # id: paste
        self._db_pastes: dict[str, DBPaste] = {}
        self._db_paste_blocks: dict[int, DBPasteBlock] = {}

    async def _init_db(self) -> None:
        self.db = await create_pool(self.config.db.filename)
        async with self.db.acquire() as conn:
            with open("schema.sql", "r") as f:
                await conn.executescript(f.read())

            await conn.commit()

        await self.fetch_all_pasts_from_db()
        await self.fetch_all_paste_blocks()

    @override
    async def setup_hook(self) -> None:
        await self._init_db()
        for ext in EXTENSION:
            await self.load_extension(ext)

        await self.tree.sync()

    @override
    async def start(self, token: str | None = None, *, reconnect: bool = True) -> None:
        token = token or self.config.bot.token
        return await super().start(token, reconnect=reconnect)

    # DB

    async def insert_paste_to_db(
        self, paste_id: str, user_id: int, message_id: int, safety_token: str
    ) -> None:
        async with self.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO pastes (id, user_id, message_id, safety_token) VALUES (?, ?, ?, ?)",
                (paste_id, user_id, message_id, safety_token),
            )
            await conn.commit()

    async def insert_paste_block(self, message_id: int) -> None:
        async with self.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO paste_blocks (message_id) VALUES (?)",
                (message_id,),
            )
            await conn.commit()

    async def delete_paste_from_db(
        self, id: str, user_id: int, message_id: int
    ) -> None:
        delete_paste = (
            "DELETE FROM pastes WHERE id = ? AND user_id = ? AND message_id = ?"
        )
        insert_block = "INSERT INTO paste_blocks (message_id) VALUES (?)"

        async with self.db.acquire() as conn:
            await conn.execute(
                delete_paste,
                (id, user_id, message_id),
            )
            await conn.execute(
                insert_block,
                (message_id,),
            )
            await conn.commit()

    async def delete_paste_block(self, message_id: int) -> None:
        async with self.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM paste_blocks WHERE message_id = ?",
                (message_id,),
            )
            await conn.commit()

    async def fetch_paste_from_db(self, id: str) -> DBPaste | None:
        if id in self._db_pastes:
            return self._db_pastes[id]

        async with self.db.acquire() as conn:
            row = await conn.fetchone(
                "SELECT id, user_id, message_id, safety_token FROM pastes WHERE id = ?",
                (id,),
            )
            if not row:
                return None

            self._db_pastes[id] = dict(row)  # pyright: ignore[reportArgumentType]

        return self._db_pastes[id]

    async def fetch_paste_block(self, message_id: int) -> DBPasteBlock | None:
        if message_id in self._db_paste_blocks:
            return self._db_paste_blocks[message_id]

        async with self.db.acquire() as conn:
            row = await conn.fetchone(
                "SELECT message_id FROM paste_blocks WHERE message_id = ?",
                (message_id,),
            )
            if not row:
                return None

            self._db_paste_blocks[message_id] = dict(row)  # pyright: ignore[reportArgumentType]

        return self._db_paste_blocks[message_id]

    async def fetch_all_pasts_from_db(self) -> dict[str, DBPaste]:
        async with self.db.acquire() as conn:
            rows = await conn.fetchall(
                "SELECT id, user_id, message_id, safety_token FROM pastes"
            )
            for row in rows:
                paste = dict(row)  # pyright: ignore[reportArgumentType]
                self._db_pastes[paste["id"]] = paste  # pyright: ignore[reportArgumentType]

        return self._db_pastes

    async def fetch_all_paste_blocks(self) -> dict[int, DBPasteBlock]:
        async with self.db.acquire() as conn:
            rows = await conn.fetchall("SELECT message_id FROM paste_blocks")
            for row in rows:
                block = dict(row)  # pyright: ignore[reportArgumentType]
                self._db_paste_blocks[block["message_id"]] = block  # pyright: ignore[reportArgumentType]

        return self._db_paste_blocks

    # API

    async def fetch_paste(self, id: str, *, password: str | None = None) -> Paste:
        try:
            paste = await self.api_client.get_paste(paste_id=id, password=password)
        except Exception as e:
            raise e
        return paste

    async def delete_paste(
        self,
        paste: DBPaste,
    ) -> None:
        try:
            await self.api_client.delete_paste(paste["safety_token"])
        except aiohttp.ClientResponseError as e:
            if e.status != 404:
                raise
        finally:
            async with self.db.acquire() as conn:
                await conn.execute("DELETE FROM pastes WHERE id = ?", (paste["id"],))
                await conn.commit()

            await self.insert_paste_block(message_id=paste["message_id"])

    # Helpers

    async def is_blocked(self, message_id: int) -> bool:
        block = await self.fetch_paste_block(message_id)
        return block is not None

    async def paste_by_message_id(self, message_id: int) -> Paste | None:
        async with self.db.acquire() as conn:
            row = await conn.fetchone(
                "SELECT id FROM pastes WHERE message_id = ?", (message_id,)
            )
            if not row:
                return None

            paste_id = row["id"]
            return await self.fetch_paste(paste_id)


async def main() -> None:
    discord.utils.setup_logging()
    async with aiohttp.ClientSession() as session:
        bot = MystbinBot(session=session)
        await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
