import asyncio
import io
import ipaddress
import json
import os
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import discord
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from premium_store import is_premium_user

DATA_DIR = Path(os.getenv("VANTARMOR_DATA_DIR", "."))
WELCOME_FILE = DATA_DIR / "welcome_settings.json"
_lock = threading.RLock()

FONT_MAPS = {
    "smallcaps": ("ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ", "abcdefghijklmnopqrstuvwxyz"),
    "fraktur": ("𝔞𝔟𝔠𝔡𝔢𝔣𝔤𝔥𝔦𝔧𝔨𝔩𝔪𝔫𝔬𝔭𝔮𝔯𝔰𝔱𝔲𝔳𝔴𝔵𝔶𝔷", "abcdefghijklmnopqrstuvwxyz"),
    "boldfraktur": ("𝖆𝖇𝖈𝖉𝖊𝖋𝖌𝖍𝖎𝖏𝖐𝖑𝖒𝖓𝖔𝖕𝖖𝖗𝖘𝖙𝖚𝖛𝖜𝖝𝖞𝖟", "abcdefghijklmnopqrstuvwxyz"),
    "double": ("𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫", "abcdefghijklmnopqrstuvwxyz"),
    "bold": ("𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳", "abcdefghijklmnopqrstuvwxyz"),
    "italic": ("𝑎𝑏𝑐𝑑𝑒𝑓𝑔ℎ𝑖𝑗𝑘𝑙𝑚𝑛𝑜𝑝𝑞𝑟𝑠𝑡𝑢𝑣𝑤𝑥𝑦𝑧", "abcdefghijklmnopqrstuvwxyz"),
    "script": ("𝒶𝒷𝒸𝒹ℯ𝒻ℊ𝒽𝒾𝒿𝓀𝓁𝓂𝓃ℴ𝓅𝓆𝓇𝓈𝓉𝓊𝓋𝓌𝓍𝓎𝓏", "abcdefghijklmnopqrstuvwxyz"),
    "boldscript": ("𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃", "abcdefghijklmnopqrstuvwxyz"),
    "fullwidth": ("ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ", "abcdefghijklmnopqrstuvwxyz"),
    "mono": ("𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣", "abcdefghijklmnopqrstuvwxyz"),
    "sansbold": ("𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇", "abcdefghijklmnopqrstuvwxyz"),
    "strike": ("a̶b̶c̶d̶e̶f̶g̶h̶i̶j̶k̶l̶m̶n̶o̶p̶q̶r̶s̶t̶u̶v̶w̶x̶y̶z̶", "abcdefghijklmnopqrstuvwxyz"),
}


def stylize(text, style):
    upper, lower = FONT_MAPS.get(style, ("", ""))
    if not lower:
        return text
    mapping = dict(zip("abcdefghijklmnopqrstuvwxyz", lower))
    mapping.update(dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", upper)))
    return "".join(mapping.get(char, char) for char in text)


def _load_settings():
    try:
        value = json.loads(WELCOME_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_welcome(guild_id, settings):
    with _lock:
        data = _load_settings()
        data[str(guild_id)] = settings
        WELCOME_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = WELCOME_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(WELCOME_FILE)


def disable_welcome(guild_id):
    with _lock:
        data = _load_settings()
        existed = data.pop(str(guild_id), None) is not None
        WELCOME_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = WELCOME_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(WELCOME_FILE)
        return existed


def _public_image_bytes(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("La imagen debe ser una URL HTTPS pública.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("No se pudo encontrar el servidor de la imagen.") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("La URL debe apuntar a una dirección pública segura.")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "Vantarmor-Commands/1.0"})
    try:
        with opener.open(request, timeout=8) as response:
            if response.status != 200 or not response.headers.get("Content-Type", "").lower().startswith("image/"):
                raise ValueError("La URL debe responder con una imagen válida.")
            data = response.read(5 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("No se pudo descargar la imagen HTTPS indicada.") from exc
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("La imagen supera el límite de 5 MB.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("El enlace no contiene una imagen compatible.") from exc
    return data


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _make_card(member, settings, background_bytes):
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
    overlay = Image.new("RGBA", (width, height), (6, 8, 15, 150))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    frame = settings.get("frame", "glow")
    colors = {"glow": (186, 218, 255, 255), "gold": (255, 205, 115, 255), "violet": (204, 165, 255, 255), "mint": (137, 255, 210, 255)}
    color = colors.get(frame, colors["glow"])
    draw.rounded_rectangle((14, 14, width - 15, height - 15), radius=30, outline=color, width=5)
    draw.rounded_rectangle((27, 27, width - 28, height - 28), radius=24, outline=(255, 255, 255, 110), width=1)
    avatar_url = member.display_avatar.replace(size=256).url
    try:
        avatar_bytes = _public_image_bytes(avatar_url)
        with Image.open(io.BytesIO(avatar_bytes)) as avatar_source:
            avatar = avatar_source.convert("RGBA").resize((118, 118), Image.Resampling.LANCZOS)
        mask = Image.new("L", avatar.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 117, 117), fill=255)
        image.alpha_composite(avatar, (65, 110), mask)
        draw.ellipse((63, 108, 185, 230), outline=color, width=4)
    except Exception:
        pass
    text = settings.get("message", "¡Bienvenido {mention}!")
    safe_name = member.display_name[:70]
    count = member.guild.member_count or 0
    replacements = {
        "{user}": safe_name,
        "{mention}": safe_name,
        "{user.mention}": safe_name,
        "user.{(Mecion)}": safe_name,
        "{member_count}": str(count),
        "{count}": str(count),
        "{server}": member.guild.name[:80],
    }
    for token, value in replacements.items():
        text = text.replace(token, value)
    text = stylize(text, settings.get("font", "smallcaps"))
    lines = [text[i:i + 47] for i in range(0, len(text), 47)][:3]
    draw.text((215, 125), "B I E N V E N I D O   A   L A   C O M U N I D A D", font=_font(17), fill=(220, 226, 238, 255))
    y = 160
    for line in lines:
        draw.text((215, y), line, font=_font(30 if len(line) < 32 else 24), fill=(255, 255, 255, 255), stroke_width=1, stroke_fill=(10, 10, 14, 180))
        y += 42
    draw.text((215, 300), f"{member.guild.name[:60]}  ·  MIEMBRO #{count}", font=_font(17), fill=color)
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


async def dispatch_welcome(member):
    settings = _load_settings().get(str(member.guild.id))
    if not settings:
        return
    channel = member.guild.get_channel(int(settings.get("channel_id", 0)))
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        if settings.get("background") == "url":
            background = await asyncio.to_thread(_public_image_bytes, settings.get("image_url", ""))
        else:
            user = await member.guild._state.http.get_user(member.id)
            profile_banner = user.get("banner")
            if profile_banner:
                ext = "gif" if profile_banner.startswith("a_") else "png"
                banner_url = f"https://cdn.discordapp.com/banners/{member.id}/{profile_banner}.{ext}?size=1024"
                background = await asyncio.to_thread(_public_image_bytes, banner_url)
            else:
                background = await asyncio.to_thread(_public_image_bytes, member.display_avatar.replace(size=512).url)
        card = await asyncio.to_thread(_make_card, member, settings, background)
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


def configure_welcome(interaction, font, background, image_url, show_count, frame, channel, ping, message):
    if interaction.guild is None:
        return False, "Este comando solo funciona dentro de un servidor."
    if not isinstance(interaction.user, discord.Member) or not (interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id):
        return False, "Solo un administrador o propietario puede configurar la bienvenida."
    if not is_premium_user(interaction.user.id):
        return False, "Esta función requiere que tu cuenta tenga Premium activo."
    if background == "url":
        if not image_url or not image_url.startswith("https://"):
            return False, "Elegiste URL: proporciona una URL HTTPS válida de imagen."
        try:
            await asyncio.to_thread(_public_image_bytes, image_url)
        except ValueError as exc:
            return False, str(exc)
    if len(message) > 500:
        return False, "El mensaje admite hasta 500 caracteres."
    settings = {
        "font": font, "background": background, "image_url": image_url if background == "url" else "",
        "show_count": show_count, "frame": frame, "channel_id": channel.id, "ping": ping,
        "message": message,
    }
    save_welcome(interaction.guild.id, settings)
    return True, "✅ Bienvenida Premium configurada. Se enviará al canal seleccionado cuando entre alguien."


def __all__():
    return None
