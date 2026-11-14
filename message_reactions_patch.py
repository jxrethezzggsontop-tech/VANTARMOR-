from pathlib import Path
import re

REACTION_MARKER = "# VANTARMOR_MESSAGE_REACTIONS_V2"
REACTION_HELPERS = r'''# VANTARMOR_MESSAGE_REACTIONS_V2
KISS_GIFS = (
    "https://media.tenor.com/-I2QfQvG8fEAAAAC/anime-kiss.gif",
    "https://media.giphy.com/media/10UVJ0IXjUbPug/giphy.gif",
)
SLAP_GIFS = (
    "https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif",
    "https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif",
)
SPANK_GIFS = (
    "https://media.tenor.com/1YpI6pT0sGkAAAAC/anime-spank.gif",
    "https://media.tenor.com/0w1Y4gI0kYgAAAAC/anime-spank.gif",
    "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
)
BANANA_GIFS = (
    "https://media.giphy.com/media/vk7VesvyZEwuY/giphy.gif",
)


async def random_anime_gif(action):
    import json
    import urllib.request

    endpoint = "kiss" if action == "kiss" else "slap"
    fallback = KISS_GIFS if action == "kiss" else SPANK_GIFS if action == "spank" else SLAP_GIFS

    def fetch():
        request = urllib.request.Request(
            f"https://nekos.best/api/v2/{endpoint}",
            headers={"User-Agent": "Vantarmor-Commands/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read(256 * 1024).decode("utf-8"))
        results = data.get("results", [])
        url = results[0].get("url") if results else None
        return url if isinstance(url, str) and url.startswith("https://") else None

    try:
        return await asyncio.to_thread(fetch) or random.choice(fallback)
    except (OSError, ValueError, KeyError, TypeError):
        return random.choice(fallback)


class ReactionChoiceView(discord.ui.View):
    def __init__(self, initiator, recipient, action):
        super().__init__(timeout=300)
        self.initiator = initiator
        self.recipient = recipient
        self.action = action
        self.finished = False
        if action == "kiss":
            accept = discord.ui.Button(label="💋 Coincidir", style=discord.ButtonStyle.success)
            reject = discord.ui.Button(label="Rechazar", style=discord.ButtonStyle.secondary)
            accept.callback = self.match
            reject.callback = self.reject
            self.add_item(accept)
            self.add_item(reject)
        else:
            counter = discord.ui.Button(label="😡 Devolver", style=discord.ButtonStyle.danger)
            counter.callback = self.return_slap
            self.add_item(counter)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.recipient.id:
            await interaction.response.send_message("Este botón es para la persona mencionada.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("Esta interacción ya terminó.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction, outcome):
        self.finished = True
        for item in self.children:
            item.disabled = True
        if self.action == "kiss" and outcome == "match":
            text = f"💋 {self.recipient.mention} ha devuelto el beso a {self.initiator.mention}."
            image = await random_anime_gif("kiss")
        elif self.action == "kiss":
            text = f"🤦 {self.recipient.mention} ha rechazado el beso de {self.initiator.mention}."
            image = None
        else:
            text = f"😡 {self.recipient.mention} ha devuelto la bofetada a {self.initiator.mention}."
            image = await random_anime_gif("slap")
        embed = discord.Embed(color=discord.Color.blurple())
        if image:
            embed.set_image(url=image)
        await interaction.response.edit_message(content=text, embed=embed, view=self, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    async def match(self, interaction):
        await self.finish(interaction, "match")

    async def reject(self, interaction):
        await self.finish(interaction, "reject")

    async def return_slap(self, interaction):
        await self.finish(interaction, "return")


async def handle_reaction_command(message, content):
    command = content.split(maxsplit=1)[0].casefold() if content else ""

    if command == "?banana":
        target = message.author
        if message.mentions:
            target = message.mentions[0]
        if getattr(target, "bot", False):
            target = message.author
        size = random.randint(1, 40)
        embed = discord.Embed(color=discord.Color.gold())
        embed.set_image(url=random.choice(BANANA_GIFS))
        await message.reply(
            f"🍌 {target.mention} mide **{size} cm** de banana.",
            embed=embed,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        return True

    if command == "?spank":
        target = None
        if message.mentions:
            target = message.mentions[0]
        elif message.reference and message.reference.message_id:
            try:
                replied = message.reference.resolved or await message.channel.fetch_message(message.reference.message_id)
                if getattr(replied, "author", None):
                    target = replied.author
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target = None
        if target is None:
            await message.reply("Menciona o responde a alguien con `?spank`.", mention_author=False)
            return True
        if target.bot or target.id == message.author.id:
            await message.reply("Menciona o responde a otra persona distinta de ti.", mention_author=False)
            return True
        image = await random_anime_gif("spank")
        embed = discord.Embed(color=discord.Color.orange())
        embed.set_image(url=image)
        await message.reply(
            f"🍑 {message.author.mention} le dio una nalgada a {target.mention}.",
            embed=embed,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        return True

    if command not in ("?kiss", "?slap"):
        return False
    reference = message.reference
    if reference is None or reference.message_id is None:
        await message.reply(f"Responde al mensaje de una persona con `{command}`.", mention_author=False)
        return True
    referenced = reference.resolved
    if referenced is None or not hasattr(referenced, "author"):
        try:
            channel = message.guild.get_channel(reference.channel_id) or await client.fetch_channel(reference.channel_id)
            referenced = await channel.fetch_message(reference.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await message.reply("No pude encontrar el mensaje al que respondiste.", mention_author=False)
            return True
    target = referenced.author
    if target.bot or target.id == message.author.id:
        await message.reply("Responde al mensaje de otra persona, no de un bot ni a ti mismo.", mention_author=False)
        return True
    action = "kiss" if command == "?kiss" else "slap"
    verb = "ha besado a" if action == "kiss" else "ha abofeteado a"
    image = await random_anime_gif(action)
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_image(url=image)
    await message.reply(
        content=f"{'💋' if action == 'kiss' else '👋'} {message.author.mention} {verb} {target.mention}.",
        embed=embed,
        view=ReactionChoiceView(message.author, target, action),
        mention_author=False,
        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
    )
    return True
'''


def patch_app(app_file: Path) -> None:
    source = app_file.read_text(encoding="utf-8")
    event_marker = "@client.event\nasync def on_message(message):\n"
    if event_marker not in source:
        raise RuntimeError("No encontré on_message en app.py para instalar ?kiss y ?slap.")

    if REACTION_MARKER in source:
        start = source.index(REACTION_MARKER)
        end = source.index(event_marker, start)
        source = source[:start] + source[end:]
    source = source.replace(event_marker, REACTION_HELPERS + "\n\n" + event_marker, 1)

    content_line = "    content = message.content.strip()\n"
    dispatch = "    if await handle_reaction_command(message, content):\n        return\n"
    if content_line not in source:
        raise RuntimeError("No encontré el contenido de on_message para instalar ?kiss y ?slap.")
    if dispatch not in source:
        source = source.replace(content_line, content_line + dispatch, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app"]
