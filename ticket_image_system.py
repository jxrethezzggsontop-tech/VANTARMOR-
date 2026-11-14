import asyncio
import base64
import io
import ipaddress
import json
import mimetypes
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from PIL import Image, UnidentifiedImageError

from premium_backup_system import is_premium_user

STORE = Path("ticket_image_panels.json")
MAX_IMAGE_BYTES = 5 * 1024 * 1024
BLUE = discord.Color.blurple()


def _read_store():
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_store(data):
    temporary = STORE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(STORE)


def _get_panel(message_id):
    return _read_store().get(str(message_id))


def _save_panel(message_id, state):
    data = _read_store()
    data[str(message_id)] = state
    _write_store(data)


def _is_panel_admin(member):
    return isinstance(member, discord.Member) and (
        member.id == member.guild.owner_id or member.guild_permissions.administrator
    )


def _validate_image_bytes(raw):
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("La imagen debe pesar como máximo 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
            if image.format not in {"PNG", "JPEG", "WEBP", "GIF", "BMP"}:
                raise ValueError("Formato de imagen no compatible. Usa PNG, JPG, WEBP o GIF.")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("El archivo no parece una imagen válida.") from error
    return True


def _safe_public_https_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("La URL debe ser HTTPS y no puede incluir credenciales.")
    if parsed.port not in (None, 443):
        raise ValueError("La URL debe usar HTTPS en el puerto estándar.")
    host = parsed.hostname.rstrip(".")
    if host.casefold() == "localhost" or host.casefold().endswith(".local"):
        raise ValueError("La URL no puede apuntar a un host local.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise ValueError("No se pudo resolver el host de la URL.") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("La URL debe apuntar a un servidor público.")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _download_public_image(url):
    url = _safe_public_https_url(url)
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": "Vantarmor-TicketImage/1.0"})
    try:
        with opener.open(request, timeout=8) as response:
            content_type = response.headers.get_content_type()
            if not content_type.startswith("image/"):
                raise ValueError("La URL no apunta directamente a una imagen.")
            raw = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ValueError("No se pudo descargar la imagen; usa un enlace directo y público.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ValueError("No se pudo descargar la imagen; comprueba el enlace.") from error
    _validate_image_bytes(raw)
    return raw


def _as_gif(raw):
    _validate_image_bytes(raw)
    output = io.BytesIO()
    with Image.open(io.BytesIO(raw)) as image:
        frames = []
        durations = []
        frame_count = min(getattr(image, "n_frames", 1), 60)
        for index in range(frame_count):
            image.seek(index)
            frame = image.convert("RGBA")
            background = Image.new("RGBA", frame.size, (255, 255, 255, 255))
            background.alpha_composite(frame)
            frames.append(background.convert("P", palette=Image.Palette.ADAPTIVE))
            durations.append(image.info.get("duration", 100))
        if not frames:
            raise ValueError("No se pudo leer la imagen.")
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            optimize=True,
        )
    gif_data = output.getvalue()
    if len(gif_data) > MAX_IMAGE_BYTES:
        raise ValueError("El GIF generado supera el límite de 5 MB.")
    return gif_data


def _render_panel(state):
    guild_name = state.get("guild_name", "este servidor")
    description = (
        f"**Sistema de tickets · {guild_name}**\n"
        "Pulsa **Crear ticket** para abrir un canal privado con el equipo de soporte.\n\n"
        f"Imagen animada: **{'Activada' if state.get('gif_enabled') else 'Desactivada'}**\n"
        f"Sistema: **{'Encendido' if state.get('enabled') else 'Apagado'}**"
    )
    embed = discord.Embed(title="🎟️ Centro de soporte", description=description, color=BLUE)
    image_file = None
    if state.get("image_data"):
        raw = base64.b64decode(state["image_data"])
        if state.get("gif_enabled"):
            raw = _as_gif(raw)
            filename = "ticket-image.gif"
        else:
            filename = state.get("image_filename") or "ticket-image.png"
            if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                filename = "ticket-image.png"
        image_file = discord.File(io.BytesIO(raw), filename=filename)
        embed.set_image(url=f"attachment://{filename}")
    elif state.get("image_url"):
        image_url = state["image_url"]
        if state.get("gif_enabled"):
            raw = _as_gif(_download_public_image(image_url))
            image_file = discord.File(io.BytesIO(raw), filename="ticket-image.gif")
            embed.set_image(url="attachment://ticket-image.gif")
        else:
            embed.set_image(url=image_url)
    return embed, image_file


class TicketImageCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        button = discord.ui.Button(
            label="🔒 Cerrar ticket", style=discord.ButtonStyle.danger,
            custom_id="ticket_image:close",
        )
        button.callback = self.close_ticket
        self.add_item(button)

    async def close_ticket(self, interaction):
        channel = interaction.channel
        guild = interaction.guild
        if guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Este botón solo funciona dentro de un ticket.", ephemeral=True)
            return
        topic = channel.topic or ""
        owner_part = next((part for part in topic.split(";") if part.startswith("ticket_image_owner:")), None)
        role_part = next((part for part in topic.split(";") if part.startswith("ticket_image_role:")), None)
        owner_id = int(owner_part.split(":", 1)[1]) if owner_part else None
        role_id = int(role_part.split(":", 1)[1]) if role_part else None
        member = interaction.user
        authorized = _is_panel_admin(member) or member.id == owner_id
        if role_id and isinstance(member, discord.Member):
            authorized = authorized or any(role.id == role_id for role in member.roles)
        if not authorized:
            await interaction.response.send_message("Solo quien abrió el ticket, un administrador o el equipo de soporte puede cerrarlo.", ephemeral=True)
            return
        await interaction.response.send_message("Cerrando el ticket…", ephemeral=True)
        try:
            await channel.delete(reason=f"Ticket cerrado por {member}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.followup.send("No pude cerrar el canal. Revisa que el bot tenga Administrar canales.", ephemeral=True)


class TicketImagePanelView(discord.ui.View):
    def __init__(self, *, enabled=False, gif_enabled=False, persistent=False):
        super().__init__(timeout=None if persistent else 86400)
        image_button = discord.ui.Button(
            label="🎞️ Dejar imagen normal" if gif_enabled else "🎞️ Volver imagen GIF",
            style=discord.ButtonStyle.secondary,
            custom_id="ticket_image:toggle_gif",
        )
        image_button.callback = self.toggle_gif
        self.add_item(image_button)

        toggle_button = discord.ui.Button(
            label="🔴 Apagar" if enabled else "🟢 Encender",
            style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
            custom_id="ticket_image:toggle_enabled",
        )
        toggle_button.callback = self.toggle_enabled
        self.add_item(toggle_button)

        # Register this component persistently even when hidden on a disabled panel.
        if enabled or persistent:
            create_button = discord.ui.Button(
                label="🎫 Crear ticket", style=discord.ButtonStyle.primary,
                custom_id="ticket_image:create_ticket",
            )
            create_button.callback = self.create_ticket
            self.add_item(create_button)

    async def _panel_state(self, interaction):
        state = _get_panel(interaction.message.id) if interaction.message else None
        if state is None:
            await interaction.response.send_message("No encontré la configuración de este panel. Vuelve a ejecutar `/ticket_image`.", ephemeral=True)
            return None
        return state

    async def _authorized_admin(self, interaction):
        if not _is_panel_admin(interaction.user):
            await interaction.response.send_message("Solo el propietario o un administrador puede cambiar este panel.", ephemeral=True)
            return False
        if not is_premium_user(interaction.user.id):
            await interaction.response.send_message("Esta función requiere Premium activo.", ephemeral=True)
            return False
        return True

    async def toggle_gif(self, interaction):
        if not await self._authorized_admin(interaction):
            return
        state = await self._panel_state(interaction)
        if state is None:
            return
        state["gif_enabled"] = not state.get("gif_enabled", False)
        try:
            embed, image_file = await asyncio.to_thread(_render_panel, state)
        except (ValueError, OSError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        _save_panel(interaction.message.id, state)
        view = TicketImagePanelView(enabled=state.get("enabled", False), gif_enabled=state["gif_enabled"])
        if image_file:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[image_file])
        else:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[])

    async def toggle_enabled(self, interaction):
        if not await self._authorized_admin(interaction):
            return
        state = await self._panel_state(interaction)
        if state is None:
            return
        state["enabled"] = not state.get("enabled", False)
        try:
            embed, image_file = await asyncio.to_thread(_render_panel, state)
        except (ValueError, OSError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        _save_panel(interaction.message.id, state)
        view = TicketImagePanelView(enabled=state["enabled"], gif_enabled=state.get("gif_enabled", False))
        if image_file:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[image_file])
        else:
            await interaction.response.edit_message(embed=embed, view=view, attachments=[])

    async def create_ticket(self, interaction):
        state = await self._panel_state(interaction)
        if state is None:
            return
        if not state.get("enabled"):
            await interaction.response.send_message("El sistema de tickets está apagado.", ephemeral=True)
            return
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Este botón solo funciona dentro del servidor.", ephemeral=True)
            return
        category = guild.get_channel(int(state.get("category_id", 0)))
        support_role = guild.get_role(int(state.get("role_id", 0)))
        if not isinstance(category, discord.CategoryChannel) or support_role is None:
            await interaction.response.send_message("La categoría o el rol de soporte configurado ya no existe.", ephemeral=True)
            return
        for existing in category.text_channels:
            if existing.topic and f"ticket_image_owner:{member.id}" in existing.topic:
                await interaction.response.send_message(f"Ya tienes un ticket abierto: {existing.mention}", ephemeral=True)
                return
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_channels:
            await interaction.response.send_message("Al bot le falta el permiso Administrar canales.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            support_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True),
        }
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{member.name}"[:90], category=category, overwrites=overwrites,
                topic=f"ticket_image_owner:{member.id};ticket_image_role:{support_role.id}",
                reason=f"Ticket de soporte abierto por {member}",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.followup.send(f"No pude crear el ticket: {error}", ephemeral=True)
            return
        welcome = discord.Embed(
            title="🎟️ Ticket de soporte",
            description=f"{member.mention} {support_role.mention}, cuéntanos cómo podemos ayudarte.",
            color=BLUE,
        )
        await channel.send(
            embed=welcome,
            view=TicketImageCloseView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),
        )
        await interaction.followup.send(f"✅ Ticket creado: {channel.mention}", ephemeral=True)


def register_ticket_image_commands(tree, client):
    """Install the Premium-only ticket image configuration command and views."""
    if not getattr(client, "ticket_image_views_registered", False):
        client.add_view(TicketImagePanelView(persistent=True))
        client.add_view(TicketImageCloseView())
        client.ticket_image_views_registered = True

    @tree.command(name="ticket_image", description="Configura un panel de tickets Premium")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        canal="Canal donde se publicará el panel",
        categoria="Categoría donde se crearán los tickets privados",
        rol_soporte="Rol que atenderá los tickets",
        foto="Imagen que aparecerá en el panel (opcional si proporcionas URL)",
        url="URL HTTPS directa de una imagen (opcional si subes una foto)",
    )
    async def ticket_image(
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        categoria: discord.CategoryChannel,
        rol_soporte: discord.Role,
        foto: Optional[discord.Attachment] = None,
        url: Optional[str] = None,
    ):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("Este comando solo funciona dentro de un servidor.", ephemeral=True)
            return
        if not _is_panel_admin(member):
            await interaction.response.send_message("Solo el propietario o un administrador puede configurar tickets.", ephemeral=True)
            return
        if not is_premium_user(member.id):
            await interaction.response.send_message("`/ticket_image` requiere que tu cuenta tenga Premium activo.", ephemeral=True)
            return
        if foto is not None and url is not None:
            await interaction.response.send_message("Sube una foto o indica una URL, no ambas.", ephemeral=True)
            return
        state = {
            "guild_id": guild.id,
            "guild_name": guild.name,
            "category_id": categoria.id,
            "role_id": rol_soporte.id,
            "enabled": False,
            "gif_enabled": False,
            "image_data": None,
            "image_filename": None,
            "image_url": None,
            "created_by": member.id,
            "created_at": int(time.time()),
        }
        try:
            if foto is not None:
                if foto.size > MAX_IMAGE_BYTES:
                    raise ValueError("La imagen debe pesar como máximo 5 MB.")
                raw = await foto.read()
                _validate_image_bytes(raw)
                state["image_data"] = base64.b64encode(raw).decode("ascii")
                state["image_filename"] = Path(foto.filename).name
            elif url is not None:
                state["image_url"] = _safe_public_https_url(url.strip())
        except (ValueError, OSError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        try:
            embed, image_file = await asyncio.to_thread(_render_panel, state)
        except (ValueError, OSError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.send_messages or not bot_member.guild_permissions.embed_links:
            await interaction.response.send_message("Al bot le faltan permisos para enviar mensajes y embeds en ese canal.", ephemeral=True)
            return
        view = TicketImagePanelView(enabled=False, gif_enabled=False)
        try:
            if image_file:
                panel_message = await canal.send(embed=embed, view=view, file=image_file)
            else:
                panel_message = await canal.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.response.send_message(f"No pude publicar el panel: {error}", ephemeral=True)
            return
        state["panel_channel_id"] = canal.id
        _save_panel(panel_message.id, state)
        await interaction.response.send_message(f"✅ Panel de tickets Premium publicado en {canal.mention}.", ephemeral=True)

    return ticket_image
