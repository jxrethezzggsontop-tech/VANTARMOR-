"""Premium defensive protections: join bursts, audit alerts, lockdown and CAPTCHA.

Anti-nuke is intentionally alert-and-lock only: the bot never auto-bans or
strips permissions from an administrator based on audit-log heuristics.
"""
import asyncio
import json
import os
import random
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands

from premium_store import is_premium_user

DATA_DIR = Path(os.getenv("VANTARMOR_DATA_DIR", "."))
STORE = DATA_DIR / "premium_security.json"
LOCK = threading.RLock()
JOIN_TIMES = defaultdict(deque)
NUKE_EVENTS = defaultdict(deque)


def _load():
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STORE)


def _guild_config(guild_id):
    with LOCK:
        return _load().get(str(guild_id), {})


def _update_guild(guild_id, update):
    with LOCK:
        data = _load()
        state = data.setdefault(str(guild_id), {})
        update(state)
        _save(data)
        return state


def _premium_admin(interaction):
    guild, member = interaction.guild, interaction.user
    return (
        guild is not None
        and isinstance(member, discord.Member)
        and (member.id == guild.owner_id or member.guild_permissions.administrator)
        and is_premium_user(member.id)
    )


async def _require_premium_admin(interaction):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Este comando solo funciona dentro de un servidor.", ephemeral=True)
        return False
    if not (interaction.user.id == interaction.guild.owner_id or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("Solo el propietario o un administrador puede configurar esta protección.", ephemeral=True)
        return False
    if not is_premium_user(interaction.user.id):
        await interaction.response.send_message("Esta protección requiere Premium activo en tu cuenta.", ephemeral=True)
        return False
    return True


def _get_audit_channel(guild, state=None):
    state = state or _guild_config(guild.id)
    channel_id = state.get("log_channel_id")
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    if isinstance(channel, discord.TextChannel):
        return channel
    configured = state.get("audit_log_channel_id")
    channel = guild.get_channel(int(configured)) if configured else None
    return channel if isinstance(channel, discord.TextChannel) else None


async def _security_log(guild, title, detail, *, color=discord.Color.blurple()):
    channel = _get_audit_channel(guild)
    if channel is None:
        return
    embed = discord.Embed(title=title, description=detail[:3500], color=color, timestamp=datetime.now(timezone.utc))
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"No se pudo enviar alerta de seguridad a {guild.id}: {error}")


async def _set_lockdown(guild, enabled, *, reason):
    state = _guild_config(guild.id)
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_channels:
        return False, "Al bot le falta el permiso Administrar canales."
    if enabled:
        if state.get("lockdown", {}).get("active"):
            return True, "El modo pánico ya está activo."
        originals = {}
        errors = 0
        for channel in guild.text_channels:
            if channel.is_news() if hasattr(channel, "is_news") else False:
                pass
            overwrite = channel.overwrites_for(guild.default_role)
            originals[str(channel.id)] = overwrite.send_messages
            overwrite.send_messages = False
            try:
                await channel.set_permissions(guild.default_role, overwrite=overwrite, reason=reason)
            except (discord.Forbidden, discord.HTTPException):
                errors += 1
        def mark(current):
            current["lockdown"] = {"active": True, "original_send_messages": originals, "started_at": int(time.time())}
        _update_guild(guild.id, mark)
        return True, f"Modo pánico activado en {len(originals) - errors} canal(es)." + (f" No se pudieron bloquear {errors}." if errors else "")

    lockdown = state.get("lockdown", {})
    if not lockdown.get("active"):
        return True, "El modo pánico ya está apagado."
    errors = 0
    for channel_id, previous in lockdown.get("original_send_messages", {}).items():
        channel = guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            continue
        overwrite = channel.overwrites_for(guild.default_role)
        overwrite.send_messages = previous
        try:
            await channel.set_permissions(
                guild.default_role,
                overwrite=overwrite if not overwrite.is_empty() else None,
                reason=reason,
            )
        except (discord.Forbidden, discord.HTTPException):
            errors += 1
    def clear(current):
        current["lockdown"] = {"active": False, "original_send_messages": {}}
    _update_guild(guild.id, clear)
    return True, "Modo pánico desactivado; permisos guardados restaurados." + (f" No se pudieron restaurar {errors} canal(es)." if errors else "")


async def _trigger_lockdown(guild, reason):
    success, message = await _set_lockdown(guild, True, reason=reason)
    await _security_log(guild, "🚨 Alerta de seguridad", f"{reason}\n{message}", color=discord.Color.red())


async def _check_audit_burst(guild, action, target_id, title):
    state = _guild_config(guild.id)
    rules = state.get("anti_nuke", {})
    if not rules.get("enabled"):
        return
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.view_audit_log:
        await _security_log(guild, "⚠️ Anti-Nuke sin auditoría", "Al bot le falta Ver registro de auditoría; no puede identificar quién hizo el cambio.", color=discord.Color.orange())
        return
    try:
        now = datetime.now(timezone.utc)
        async for entry in guild.audit_logs(limit=8, action=action, after=now - timedelta(seconds=15)):
            if getattr(entry.target, "id", None) != target_id:
                continue
            executor = entry.user
            if executor is None or executor.bot:
                return
            key = (guild.id, executor.id)
            recent = NUKE_EVENTS[key]
            stamp = time.monotonic()
            window = int(rules.get("window_seconds", 10))
            while recent and stamp - recent[0] > window:
                recent.popleft()
            recent.append(stamp)
            threshold = int(rules.get("threshold", 3))
            if len(recent) >= threshold:
                recent.clear()
                await _trigger_lockdown(
                    guild,
                    f"Anti-Nuke detectó {title} repetidos por {executor} (`{executor.id}`). No se expulsó ni se quitaron permisos automáticamente; revisa el registro de auditoría.",
                )
            return
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"No se pudo consultar audit log de {guild.id}: {error}")


async def on_channel_delete(channel):
    if channel.guild is not None:
        await _check_audit_burst(channel.guild, discord.AuditLogAction.channel_delete, channel.id, "eliminación de canales")


async def on_role_delete(role):
    await _check_audit_burst(role.guild, discord.AuditLogAction.role_delete, role.id, "eliminación de roles")


async def on_member_ban(guild, user):
    await _check_audit_burst(guild, discord.AuditLogAction.ban, user.id, "baneos")


async def on_member_join(member):
    guild = member.guild
    state = _guild_config(guild.id)
    if member.bot:
        allowed = {str(value) for value in state.get("allowed_bots", [])}
        if str(member.id) not in allowed:
            bot_member = guild.me
            if bot_member and bot_member.guild_permissions.kick_members:
                try:
                    await guild.kick(member, reason="Premium Anti-Bot: el bot no está en la lista autorizada")
                    await _security_log(guild, "🤖 Bot no autorizado expulsado", f"Se expulsó a `{member}` (`{member.id}`), porque no estaba autorizado.", color=discord.Color.orange())
                except (discord.Forbidden, discord.HTTPException) as error:
                    await _security_log(guild, "⚠️ Bot no autorizado", f"No se pudo expulsar a `{member}` (`{member.id}`). Revisa la jerarquía/permisos: {error}", color=discord.Color.orange())
            else:
                await _security_log(guild, "⚠️ Bot no autorizado", f"Entró `{member}` (`{member.id}`), pero al bot le falta Expulsar miembros.", color=discord.Color.orange())
        return

    minimum_days = int(state.get("min_account_age_days", 0))
    if minimum_days and (datetime.now(timezone.utc) - member.created_at).total_seconds() < minimum_days * 86400:
        quarantine_id = state.get("quarantine_role_id")
        quarantine = guild.get_role(int(quarantine_id)) if quarantine_id else None
        if quarantine is not None and guild.me and guild.me.guild_permissions.manage_roles and quarantine < guild.me.top_role:
            try:
                await member.add_roles(quarantine, reason=f"Cuenta creada hace menos de {minimum_days} días; revisión manual")
                await _security_log(guild, "🕵️ Cuenta nueva retenida", f"{member.mention} (`{member.id}`) tiene una cuenta de menos de {minimum_days} días y recibió el rol de revisión.", color=discord.Color.orange())
            except (discord.Forbidden, discord.HTTPException) as error:
                await _security_log(guild, "⚠️ Filtro de cuentas", f"No se pudo aplicar el rol de revisión a `{member.id}`: {error}", color=discord.Color.orange())
        else:
            await _security_log(guild, "🕵️ Cuenta nueva detectada", f"{member.mention} (`{member.id}`) tiene menos de {minimum_days} días. Configura un rol de revisión para retenerla.", color=discord.Color.orange())

    raid = state.get("anti_raid", {})
    if raid.get("enabled"):
        now = time.monotonic()
        recent = JOIN_TIMES[guild.id]
        window = int(raid.get("window_seconds", 10))
        while recent and now - recent[0] > window:
            recent.popleft()
        recent.append(now)
        if len(recent) >= int(raid.get("threshold", 6)):
            recent.clear()
            await _trigger_lockdown(guild, f"Anti-Raid detectó una ráfaga de entradas (umbral {raid.get('threshold', 6)} en {window} s).")


async def on_invite_create(invite):
    state = _guild_config(invite.guild.id)
    if state.get("anti_raid", {}).get("enabled"):
        await _security_log(invite.guild, "🔗 Invitación nueva durante Anti-Raid", f"Se creó una invitación en {invite.channel.mention if invite.channel else 'un canal desconocido'}. Revisa si es legítima.", color=discord.Color.orange())


class CaptchaModal(discord.ui.Modal):
    def __init__(self, guild_id, role_id, first, second, operator):
        super().__init__(title="Verificación del servidor")
        self.guild_id = guild_id
        self.role_id = role_id
        self.expected = first + second if operator == "+" else first - second
        self.answer = discord.ui.TextInput(
            label=f"Resuelve: {first} {operator} {second} = ?",
            placeholder="Escribe el resultado",
            min_length=1,
            max_length=4,
            required=True,
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction):
        if not str(self.answer.value).strip().lstrip("-").isdigit() or int(self.answer.value) != self.expected:
            await interaction.response.send_message("Respuesta incorrecta. Pulsa Verificar para intentarlo otra vez.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None or guild.id != self.guild_id or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("La verificación solo funciona en el servidor donde se abrió.", ephemeral=True)
            return
        role = guild.get_role(self.role_id)
        bot_member = guild.me
        if role is None or bot_member is None or not bot_member.guild_permissions.manage_roles or role >= bot_member.top_role:
            await interaction.response.send_message("No pude asignar el rol verificado. Revisa el rol y los permisos del bot.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("Ya tienes la verificación completada.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Captcha Premium completado")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Discord no permitió asignar el rol verificado.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Verificación completada. ¡Bienvenido!", ephemeral=True)


class CaptchaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Verificar", style=discord.ButtonStyle.success, custom_id="premium_security:captcha")
    async def verify(self, interaction, button):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Este botón solo funciona en un servidor.", ephemeral=True)
            return
        panel = _load().get("captcha_panels", {}).get(str(interaction.message.id))
        if not panel or str(panel.get("guild_id")) != str(guild.id):
            await interaction.response.send_message("Este panel ya no está configurado.", ephemeral=True)
            return
        first, second = random.randint(2, 9), random.randint(1, 9)
        operator = random.choice(("+", "-"))
        await interaction.response.send_modal(CaptchaModal(guild.id, int(panel["verified_role_id"]), first, second, operator))


def register_security_commands(tree, client):
    """Register Premium security controls and listeners on the Discord client."""
    if not getattr(client, "premium_security_listeners_registered", False):
        client.add_listener(on_member_join, "on_member_join")
        client.add_listener(on_channel_delete, "on_guild_channel_delete")
        client.add_listener(on_role_delete, "on_guild_role_delete")
        client.add_listener(on_member_ban, "on_member_ban")
        client.add_listener(on_invite_create, "on_invite_create")
        client.add_view(CaptchaView())
        client.premium_security_listeners_registered = True

    @tree.command(name="anti-raid", description="Configura Anti-Raid Premium para ráfagas de entradas")
    @app_commands.describe(activar="Activar o desactivar Anti-Raid", umbral="Entradas necesarias para activar el modo pánico", ventana="Ventana de detección en segundos")
    async def anti_raid(interaction: discord.Interaction, activar: bool, umbral: app_commands.Range[int, 3, 25] = 6, ventana: app_commands.Range[int, 5, 60] = 10):
        if not await _require_premium_admin(interaction):
            return
        _update_guild(interaction.guild.id, lambda state: state.update(anti_raid={"enabled": activar, "threshold": int(umbral), "window_seconds": int(ventana)}))
        await interaction.response.send_message(f"✅ Anti-Raid {'activado' if activar else 'desactivado'}: {umbral} entradas en {ventana} segundos. Si se alcanza el umbral, se activa el modo pánico.", ephemeral=True)

    @tree.command(name="anti-nuke", description="Detecta borrados/ban masivos y activa el modo pánico")
    @app_commands.describe(activar="Activar o desactivar Anti-Nuke", umbral="Acciones del mismo usuario antes de activar el modo pánico", ventana="Ventana de detección en segundos")
    async def anti_nuke(interaction: discord.Interaction, activar: bool, umbral: app_commands.Range[int, 2, 10] = 3, ventana: app_commands.Range[int, 5, 60] = 10):
        if not await _require_premium_admin(interaction):
            return
        _update_guild(interaction.guild.id, lambda state: state.update(anti_nuke={"enabled": activar, "threshold": int(umbral), "window_seconds": int(ventana)}))
        note = "El bot bloqueará canales y avisará; no expulsará ni quitará permisos automáticamente a administradores." if activar else ""
        await interaction.response.send_message(f"✅ Anti-Nuke {'activado' if activar else 'desactivado'}: {umbral} acciones en {ventana} segundos. {note} Para identificar autores, da al bot Ver registro de auditoría.", ephemeral=True)

    @tree.command(name="anti-bot", description="Autoriza o revoca bots permitidos en el servidor")
    @app_commands.choices(accion=[app_commands.Choice(name="Autorizar", value="allow"), app_commands.Choice(name="Revocar", value="revoke")])
    @app_commands.describe(accion="Acción sobre la lista autorizada", bot="Cuenta bot que se autoriza o revoca")
    async def anti_bot(interaction: discord.Interaction, accion: app_commands.Choice[str], bot: discord.User):
        if not await _require_premium_admin(interaction):
            return
        if not bot.bot:
            await interaction.response.send_message("Selecciona una cuenta bot.", ephemeral=True)
            return
        def change(state):
            allowed = {str(value) for value in state.get("allowed_bots", [])}
            if accion.value == "allow":
                allowed.add(str(bot.id))
            else:
                allowed.discard(str(bot.id))
            state["allowed_bots"] = sorted(allowed)
        _update_guild(interaction.guild.id, change)
        await interaction.response.send_message(f"✅ Bot {bot.mention} {'autorizado' if accion.value == 'allow' else 'revocado'}. Los bots no autorizados que intenten entrar serán expulsados si el bot tiene permiso.", ephemeral=True)

    @tree.command(name="filtro-cuentas", description="Retiene cuentas nuevas con un rol para revisión manual")
    @app_commands.describe(dias="Antigüedad mínima en días (0 desactiva)", rol_revision="Rol de cuarentena configurado para ocultar canales privados")
    async def account_age_filter(interaction: discord.Interaction, dias: app_commands.Range[int, 0, 365], rol_revision: Optional[discord.Role] = None):
        if not await _require_premium_admin(interaction):
            return
        _update_guild(interaction.guild.id, lambda state: state.update(min_account_age_days=int(dias), quarantine_role_id=rol_revision.id if rol_revision else None))
        extra = " Configura los permisos del rol para que las cuentas retenidas solo vean el canal de revisión." if dias and rol_revision else " El filtro solo genera alertas hasta que elijas un rol de revisión." if dias else ""
        await interaction.response.send_message(f"✅ Filtro de cuentas configurado: mínimo {dias} día(s).{extra}", ephemeral=True)

    @tree.command(name="lockdown", description="Activa o desactiva el modo pánico Premium")
    @app_commands.describe(activar="True bloquea el envío de mensajes para @everyone; False restaura permisos previos")
    async def lockdown(interaction: discord.Interaction, activar: bool):
        if not await _require_premium_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        success, result = await _set_lockdown(interaction.guild, activar, reason=f"Modo pánico solicitado por {interaction.user}")
        if success:
            await _security_log(interaction.guild, "🔒 Modo pánico", f"{result}\nAcción solicitada por {interaction.user}.", color=discord.Color.red() if activar else discord.Color.green())
        await interaction.followup.send(("✅ " if success else "⚠️ ") + result, ephemeral=True)

    @tree.command(name="security-log", description="Configura el canal de alertas de seguridad Premium")
    @app_commands.describe(canal="Canal privado de registros y alertas")
    async def security_log(interaction: discord.Interaction, canal: discord.TextChannel):
        if not await _require_premium_admin(interaction):
            return
        perms = canal.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message("Al bot le faltan permisos para enviar embeds en ese canal.", ephemeral=True)
            return
        _update_guild(interaction.guild.id, lambda state: state.update(log_channel_id=canal.id))
        await interaction.response.send_message(f"✅ Alertas de seguridad en {canal.mention}.", ephemeral=True)

    @tree.command(name="captcha-panel", description="Publica un panel de verificación con captcha Premium")
    @app_commands.describe(canal="Canal público de verificación", rol_verificado="Rol que se asignará al superar el captcha")
    async def captcha_panel(interaction: discord.Interaction, canal: discord.TextChannel, rol_verificado: discord.Role):
        if not await _require_premium_admin(interaction):
            return
        guild = interaction.guild
        bot_member = guild.me
        if bot_member is None or not bot_member.guild_permissions.manage_roles or rol_verificado >= bot_member.top_role:
            await interaction.response.send_message("El bot necesita Administrar roles y su rol debe estar por encima del rol verificado.", ephemeral=True)
            return
        embed = discord.Embed(
            title="🛡️ Verificación del servidor",
            description="Pulsa **Verificar** y resuelve la operación sencilla para recibir el rol de acceso. Configura @everyone para ver únicamente este canal hasta verificar.",
            color=discord.Color.blurple(),
        )
        try:
            message = await canal.send(embed=embed, view=CaptchaView(), allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException) as error:
            await interaction.response.send_message(f"No pude publicar el panel: {error}", ephemeral=True)
            return
        def save_panel(state):
            panels = state.setdefault("captcha_panels", {})
            panels[str(message.id)] = {"guild_id": guild.id, "verified_role_id": rol_verificado.id, "channel_id": canal.id}
        _update_guild(guild.id, save_panel)
        await interaction.response.send_message(f"✅ Panel de captcha enviado a {canal.mention}.", ephemeral=True)

    @tree.command(name="security-status", description="Muestra el estado de las protecciones Premium")
    async def security_status(interaction: discord.Interaction):
        if not await _require_premium_admin(interaction):
            return
        state = _guild_config(interaction.guild.id)
        raid = state.get("anti_raid", {})
        nuke = state.get("anti_nuke", {})
        lockdown_state = state.get("lockdown", {}).get("active", False)
        embed = discord.Embed(title="🛡️ Seguridad Premium", color=discord.Color.blurple())
        embed.add_field(name="Anti-Raid", value=f"{'Activo' if raid.get('enabled') else 'Inactivo'} · {raid.get('threshold', 6)} entradas / {raid.get('window_seconds', 10)} s", inline=False)
        embed.add_field(name="Anti-Nuke", value=f"{'Activo' if nuke.get('enabled') else 'Inactivo'} · {nuke.get('threshold', 3)} acciones / {nuke.get('window_seconds', 10)} s", inline=False)
        embed.add_field(name="Bots autorizados", value=str(len(state.get("allowed_bots", []))), inline=True)
        embed.add_field(name="Antigüedad mínima", value=f"{state.get('min_account_age_days', 0)} días", inline=True)
        embed.add_field(name="Modo pánico", value="Activo" if lockdown_state else "Inactivo", inline=True)
        embed.add_field(name="Captcha", value=f"{len(state.get('captcha_panels', {}))} panel(es)", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    return (anti_raid, anti_nuke, anti_bot, account_age_filter, lockdown, security_log, captcha_panel, security_status)


__all__ = ["register_security_commands"]
