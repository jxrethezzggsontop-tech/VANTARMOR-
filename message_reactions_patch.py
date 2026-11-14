from pathlib import Path

REACTION_MARKER = "# VANTARMOR_MESSAGE_REACTIONS_V2"
REACTION_HELPERS = r'''# VANTARMOR_MESSAGE_REACTIONS_V2
BANANA_GIFS = (
    "https://media.tenor.com/nBEH0FvRR0UAAAAM/banana-anime.gif",
    "https://media.giphy.com/media/vk7VesvyZEwuY/giphy.gif",
)
REACTION_GIF_ENDPOINTS = {
    "kiss": ("https://nekos.best/api/v2/kiss", "https://api.waifu.pics/sfw/kiss"),
    "slap": ("https://nekos.best/api/v2/slap", "https://api.waifu.pics/sfw/slap"),
    "spank": ("https://nekos.best/api/v2/spank", "https://api.waifu.pics/sfw/spank", "https://api.waifu.pics/sfw/slap"),
    "hug": ("https://nekos.best/api/v2/hug", "https://api.waifu.pics/sfw/hug"),
}
REACTION_GIF_FALLBACKS = {
    "kiss": ("https://media.tenor.com/-I2QfQvG8fEAAAAC/anime-kiss.gif", "https://media.giphy.com/media/10UVJ0IXjUbPug/giphy.gif"),
    "slap": ("https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif", "https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif"),
    "spank": ("https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif",),
    "hug": ("https://media.tenor.com/1XqT5gW0AAAAM/anime-hug.gif", "https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif"),
}


async def random_anime_gif(action):
    import json
    import urllib.request

    def fetch():
        endpoints = list(REACTION_GIF_ENDPOINTS.get(action, ()))
        random.shuffle(endpoints)
        for endpoint in endpoints:
            try:
                request = urllib.request.Request(
                    endpoint,
                    headers={"User-Agent": "Vantarmor-Commands/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=4) as response:
                    data = json.loads(response.read(256 * 1024).decode("utf-8"))
                results = data.get("results", [])
                url = results[0].get("url") if results else data.get("url")
                if isinstance(url, str) and url.startswith("https://"):
                    return url
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                continue
        return None

    try:
        url = await asyncio.to_thread(fetch)
    except (OSError, ValueError, KeyError, TypeError):
        url = None
    if url:
        return url
    fallbacks = REACTION_GIF_FALLBACKS.get(action, ())
    return random.choice(fallbacks) if fallbacks else None


class HugReturnView(discord.ui.View):
    def __init__(self, initiator, recipient):
        super().__init__(timeout=300)
        self.initiator = initiator
        self.recipient = recipient
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.recipient.id:
            await interaction.response.send_message("Este botón es para la persona abrazada.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("Este abrazo ya fue devuelto.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🤗 Devolver abrazo", style=discord.ButtonStyle.success)
    async def return_hug(self, interaction, button):
        self.finished = True
        button.disabled = True
        embed = discord.Embed(
            description=f"🤗 {self.recipient.mention} le devuelve el abrazo a {self.initiator.mention}.",
            color=discord.Color.pink(),
        )
        embed.set_author(name=f"{self.recipient} 🤗 {self.initiator}", icon_url=self.recipient.display_avatar.url)
        embed.set_image(url=await random_anime_gif("hug"))
        await interaction.response.edit_message(embed=embed, view=self, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))


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
        embed = discord.Embed(description=text, color=discord.Color.blurple())
        if image:
            embed.set_image(url=image)
        await interaction.response.edit_message(content=None, embed=embed, view=self, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))

    async def match(self, interaction):
        await self.finish(interaction, "match")

    async def reject(self, interaction):
        await self.finish(interaction, "reject")

    async def return_slap(self, interaction):
        await self.finish(interaction, "return")


async def handle_reaction_command(message, content):
    command = content.split(maxsplit=1)[0].casefold() if content else ""

    if command == "?banana":
        target = message.mentions[0] if message.mentions else message.author
        if getattr(target, "bot", False):
            target = message.author
        size = random.randint(1, 40)
        embed = discord.Embed(
            description=f"La banana de {target.mention} mide **{size} cm** 🍌",
            color=discord.Color.green(),
        )
        embed.set_author(name=str(target), icon_url=target.display_avatar.url)
        embed.set_image(url=random.choice(BANANA_GIFS))
        embed.set_footer(text=f"Evaluación de la banana de {target}", icon_url=target.display_avatar.url)
        await message.reply(
            embed=embed,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        return True

    if command in ("?hug", "?spank"):
        target = message.mentions[0] if message.mentions else None
        if target is None and message.reference and message.reference.message_id:
            try:
                replied = message.reference.resolved or await message.channel.fetch_message(message.reference.message_id)
                target = getattr(replied, "author", None)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target = None
        if target is None:
            await message.reply(f"Menciona o responde a alguien con `{command}`.", mention_author=False)
            return True
        if target.bot or target.id == message.author.id:
            await message.reply("Menciona o responde a otra persona distinta de ti.", mention_author=False)
            return True
        if command == "?hug":
            embed = discord.Embed(
                description=f"🤗 {message.author.mention} ha abrazado a {target.mention}.",
                color=discord.Color.pink(),
            )
            embed.set_author(name=f"{message.author} 🤗 {target}", icon_url=message.author.display_avatar.url)
            embed.set_image(url=await random_anime_gif("hug"))
            await message.reply(
                embed=embed,
                view=HugReturnView(message.author, target),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            return True
        embed = discord.Embed(
            description=f"🍑 {message.author.mention} le dio una nalgada a {target.mention}.",
            color=discord.Color.orange(),
        )
        embed.set_image(url=await random_anime_gif("spank"))
        await message.reply(
            embed=embed,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        return True

    if command not in ("?kiss", "?slap"):
        return False
    reference = message.reference
    target = message.mentions[0] if message.mentions else None
    if target is None and reference and reference.message_id:
        referenced = reference.resolved
        if referenced is None or not hasattr(referenced, "author"):
            try:
                channel = message.guild.get_channel(reference.channel_id) or await client.fetch_channel(reference.channel_id)
                referenced = await channel.fetch_message(reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                referenced = None
        target = getattr(referenced, "author", None)
    if target is None:
        await message.reply(f"Menciona o responde a una persona con `{command}`.", mention_author=False)
        return True
    if target.bot or target.id == message.author.id:
        await message.reply("Usa el comando con otra persona, no con un bot ni contigo mismo.", mention_author=False)
        return True
    action = "kiss" if command == "?kiss" else "slap"
    verb = "ha besado a" if action == "kiss" else "ha abofeteado a"
    embed = discord.Embed(
        description=f"{'💋' if action == 'kiss' else '👋'} {message.author.mention} {verb} {target.mention}.",
        color=discord.Color.blurple(),
    )
    embed.set_image(url=await random_anime_gif(action))
    await message.reply(
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
        raise RuntimeError("No encontré on_message en app.py para instalar comandos de reacción.")

    if REACTION_MARKER in source:
        start = source.index(REACTION_MARKER)
        end = source.index(event_marker, start)
        source = source[:start] + source[end:]
    source = source.replace(event_marker, REACTION_HELPERS + "\n\n" + event_marker, 1)

    content_line = "    content = message.content.strip()\n"
    dispatch = "    if await handle_reaction_command(message, content):\n        return\n"
    if content_line not in source:
        raise RuntimeError("No encontré el contenido de on_message para instalar comandos de reacción.")
    if dispatch not in source:
        source = source.replace(content_line, content_line + dispatch, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app"]
