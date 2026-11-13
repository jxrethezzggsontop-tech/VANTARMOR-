import asyncio
import io
import json
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFilter

import welcome_system
from welcome_system import WELCOME_FILE


async def configure_free_welcome(interaction, channel, ping, show_number, message):
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        return False, "Este comando solo funciona dentro de un servidor."
    if not (member.guild_permissions.administrator or member.id == guild.owner_id):
        return False, "Solo un administrador o propietario puede configurar la bienvenida."
    if not isinstance(channel, discord.TextChannel) or channel.guild.id != guild.id:
        return False, "Selecciona un canal de texto de este servidor."
    if len(message) > 500:
        return False, "El mensaje admite hasta 500 caracteres."
    welcome_system.save_welcome(guild.id, {
        "font": "smallcaps",
        "background": "server",
        "image_url": "",
        "show_count": bool(show_number),
        "frame": "glow",
        "channel_id": channel.id,
        "ping": bool(ping),
        "message": message,
        "tier": "free",
    })
    return True, "✅ Bienvenida Free configurada. Usará el banner o icono del servidor como fondo."


def _server_background(guild):
    asset = guild.banner or guild.icon
    if asset is None:
        return None
    try:
        return welcome_system._public_image_bytes(asset.replace(size=1024).url)
    except (ValueError, OSError):
        return None


def _make_free_card(member, settings, background_bytes):
    width, height = 1000, 360
    if background_bytes:
        with Image.open(io.BytesIO(background_bytes)) as source:
            image = source.convert("RGB")
            scale = max(width / image.width, height / image.height)
            image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
            left, top = (image.width - width) // 2, (image.height - height) // 2
            image = image.crop((left, top, left + width, top + height)).filter(ImageFilter.GaussianBlur(2))
    else:
        image = Image.new("RGB", (width, height), (14, 17, 26))
    image = image.convert("RGBA")
    image.alpha_composite(Image.new("RGBA", (width, height), (6, 8, 15, 155)))
    draw = ImageDraw.Draw(image)
    color = (186, 218, 255, 255)
    draw.rounded_rectangle((14, 14, width - 15, height - 15), radius=30, outline=color, width=5)

    try:
        avatar_bytes = welcome_system._public_image_bytes(member.display_avatar.replace(size=256).url)
        with Image.open(io.BytesIO(avatar_bytes)) as source:
            avatar = source.convert("RGBA").resize((118, 118), Image.Resampling.LANCZOS)
        mask = Image.new("L", avatar.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 117, 117), fill=255)
        image.paste(avatar, (65, 110), mask)
        draw = ImageDraw.Draw(image)
        draw.ellipse((63, 108, 185, 230), outline=color, width=4)
    except (ValueError, OSError):
        pass

    count = member.guild.member_count or 0
    safe_name = member.display_name[:70]
    text = settings.get("message", "¡Bienvenido {mention}!")
    replacements = {
        "{user}": safe_name,
        "{mention}": safe_name,
        "{user.mention}": safe_name,
        "{member_count}": str(count),
        "{count}": str(count),
        "{server}": member.guild.name[:80],
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    text = welcome_system.stylize(text, "smallcaps")
    for index, line in enumerate([text[i:i + 47] for i in range(0, len(text), 47)][:3]):
        draw.text((215, 150 + index * 42), line, font=welcome_system._font(28 if len(line) < 32 else 23), fill=(255, 255, 255, 255))
    footer = f"{member.guild.name[:60]}  ·  MIEMBRO #{count}" if settings.get("show_count", True) else member.guild.name[:80]
    draw.text((215, 300), footer, font=welcome_system._font(17), fill=color)
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def dispatch_welcome_tiered(member):
    try:
        all_settings = json.loads(WELCOME_FILE.read_text(encoding="utf-8"))
        settings = all_settings.get(str(member.guild.id)) if isinstance(all_settings, dict) else None
    except (OSError, json.JSONDecodeError):
        settings = None
    if not settings:
        return
    if settings.get("background") != "server":
        await welcome_system.dispatch_welcome(member)
        return
    channel = member.guild.get_channel(int(settings.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        background = await asyncio.to_thread(_server_background, member.guild)
        card = await asyncio.to_thread(_make_free_card, member, settings, background)
        file = discord.File(card, filename="bienvenida.png")
        embed = discord.Embed(color=discord.Color.from_rgb(145, 190, 255))
        embed.set_image(url="attachment://bienvenida.png")
        content = member.mention if settings.get("ping") else None
        await channel.send(content=content, embed=embed, file=file, allowed_mentions=discord.AllowedMentions(users=bool(content), roles=False, everyone=False))
    except Exception as exc:
        print(f"Bienvenida no enviada en guild {member.guild.id}: {type(exc).__name__}: {exc}")
        try:
            await channel.send(f"¡Bienvenido/a, {member.mention}! Ya somos **{member.guild.member_count or 0}** miembros.", allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        except discord.HTTPException:
            pass
