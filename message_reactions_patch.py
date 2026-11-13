from pathlib import Path

REACTION_MARKER = "# VANTARMOR_MESSAGE_REACTIONS_V2"
REACTION_HELPERS = r'''# VANTARMOR_MESSAGE_REACTIONS_V2
import json
import urllib.request

# Prefer a matching anime-reaction category, then try a broadly available
# SFW anime reaction so an absent niche endpoint never leaves the embed blank.
REACTION_GIF_ENDPOINTS = {
    "kiss": ("https://nekos.best/api/v2/kiss", "https://api.waifu.pics/sfw/kiss"),
    "slap": ("https://nekos.best/api/v2/slap", "https://api.waifu.pics/sfw/slap"),
    "spank": ("https://nekos.best/api/v2/spank", "https://api.waifu.pics/sfw/spank", "https://api.waifu.pics/sfw/slap"),
    "kill": ("https://api.waifu.pics/sfw/kill", "https://nekos.best/api/v2/kill", "https://nekos.best/api/v2/fight", "https://api.waifu.pics/sfw/slap"),
    "revenge": ("https://nekos.best/api/v2/fight", "https://api.waifu.pics/sfw/kill", "https://api.waifu.pics/sfw/slap"),
    "scare": ("https://api.waifu.pics/sfw/scary", "https://nekos.best/api/v2/scare", "https://nekos.best/api/v2/ghost"),
}
REACTION_GIF_FALLBACKS = {
    "kiss": ("https://media.tenor.com/-I2QfQvG8fEAAAAC/anime-kiss.gif", "https://media.giphy.com/media/10UVJ0IXjUbPug/giphy.gif"),
    "slap": ("https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif", "https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif"),
    # Spank endpoints are inconsistent; keep an anime slap GIF as a visible fallback.
    "spank": ("https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif", "https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif"),
    # Fictional anime action fallback; no realistic or graphic imagery.
    "kill": ("https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif", "https://media.tenor.com/v1a5sM-9VnoAAAAC/anime-slap.gif"),
    "revenge": ("https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif",),
    "scare": ("https://media.giphy.com/media/3XlEk2RxPS1m8/giphy.gif",),
}


async def random_anime_gif(action):
    def fetch():
        for endpoint in REACTION_GIF_ENDPOINTS.get(action, ()):
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
        elif action == "slap":
            counter = discord.ui.Button(label="😡 Devolver", style=discord.ButtonStyle.danger)
            counter.callback = self.return_slap
            self.add_item(counter)
        elif action == "spank":
            counter = discord.ui.Button(label="🙎 Devolver", style=discord.ButtonStyle.danger)
            counter.callback = self.return_spank
            self.add_item(counter)
        elif action == "kill":
            revenge = discord.ui.Button(label="💀 Vengar", style=discord.ButtonStyle.danger)
            scare = discord.ui.Button(label="👻 Asustar", style=discord.ButtonStyle.secondary)
            revenge.callback = self.revenge
            scare.callback = self.scare
            self.add_item(revenge)
            self.add_item(scare)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.recipient.id:
            await interaction.response.send_message("Este botón es para la persona mencionada en el mensaje.", ephemeral=True)
            return False
        if self.finished:
            await interaction.response.send_message("Esta interacción ya terminó.", ephemeral=True)
            return False
        return True

    async def finish(self, interaction, outcome):
        if self.finished:
            await interaction.response.send_message("Esta interacción ya terminó.", ephemeral=True)
            return
        self.finished = True
        for item in self.children:
            item.disabled = True

        if self.action == "kiss" and outcome == "match":
            text = f"💋 {self.recipient.mention} ha devuelto el beso a {self.initiator.mention}."
            image_action = "kiss"
        elif self.action == "kiss":
            text = f"🤦 {self.recipient.mention} ha rechazado el beso de {self.initiator.mention}."
            image_action = None
        elif self.action == "slap":
            text = f"😡 {self.recipient.mention} ha devuelto la bofetada a {self.initiator.mention}."
            image_action = "slap"
        elif self.action == "spank":
            text = f"🙎 {self.recipient.mention} le ha devuelto el spank a {self.initiator.mention}."
            image_action = "spank"
        elif outcome == "revenge":
            text = f"💀 {self.recipient.mention}, derrotado en la escena ficticia por {self.initiator.mention}, ha vuelto para vengarse."
            image_action = "revenge"
        else:
            text = f"👻 {self.recipient.mention}, derrotado en la escena ficticia por {self.initiator.mention}, ha vuelto como fantasma para asustar a {self.initiator.mention}."
            image_action = "scare"

        embed = discord.Embed(color=discord.Color.blurple())
        if image_action:
            image = await random_anime_gif(image_action)
            if image:
                embed.set_image(url=image)

        # Keep the original action message; disable its buttons and post the
        # outcome as a separate public message.
        await interaction.response.defer()
        try:
            await interaction.message.edit(view=self)
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.followup.send(
            content=text,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    async def match(self, interaction):
        await self.finish(interaction, "match")

    async def reject(self, interaction):
        await self.finish(interaction, "reject")

    async def return_slap(self, interaction):
        await self.finish(interaction, "return")

    async def return_spank(self, interaction):
        await self.finish(interaction, "return")

    async def revenge(self, interaction):
        await self.finish(interaction, "revenge")

    async def scare(self, interaction):
        await self.finish(interaction, "scare")


async def handle_reaction_command(message, content):
    command = content.split(maxsplit=1)[0].casefold() if content else ""
    if command not in ("?kiss", "?slap", "?spank", "?kill"):
        return False
    labels = {
        "?kiss": ("kiss", "ha besado a", "💋"),
        "?slap": ("slap", "ha abofeteado a", "👋"),
        "?spank": ("spank", "ha nalgueado a", "🙎"),
        "?kill": ("kill", "ha derrotado en una escena ficticia de anime a", "💀"),
    }
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
    action, verb, emoji = labels[command]
    image = await random_anime_gif(action)
    embed = discord.Embed(color=discord.Color.blurple())
    if image:
        embed.set_image(url=image)
    await message.reply(
        content=f"{emoji} {message.author.mention} {verb} {target.mention}.",
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
        raise RuntimeError("No encontré on_message en app.py para instalar ?kiss, ?slap, ?spank y ?kill.")

    if REACTION_MARKER in source:
        start = source.index(REACTION_MARKER)
        end = source.index(event_marker, start)
        source = source[:start] + source[end:]
    source = source.replace(event_marker, REACTION_HELPERS + "\n\n" + event_marker, 1)

    content_line = "    content = message.content.strip()\n"
    dispatch = "    if await handle_reaction_command(message, content):\n        return\n"
    if content_line not in source:
        raise RuntimeError("No encontré el contenido de on_message para instalar los comandos de reacción.")
    if dispatch not in source:
        source = source.replace(content_line, content_line + dispatch, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app"]
