"""Prefix moderation commands with durable warnings and reversible hard mutes."""
import asyncio
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord

DATA_DIR = Path(os.getenv("VANTARMOR_DATA_DIR", "."))
STORE = DATA_DIR / "moderation_records.json"
LOCK = threading.RLock()


def _read():
    try:
        value = json.loads(STORE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"warnings": {}, "hardmutes": {}}
    except (OSError, json.JSONDecodeError):
        return {"warnings": {}, "hardmutes": {}}


def _write(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = STORE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STORE)


def _duration(text):
    match = re.fullmatch(r"(\d+)(m|min|h|hr|d|day|days|dia|dias|w|week|weeks|sem|semanas)", text.casefold())
    if not match:
        return None
    n, unit = int(match.group(1)), match.group(2)
    factors = {
        "m": 60, "min": 60, "h": 3600, "hr": 3600,
        "d": 86400, "day": 86400, "days": 86400, "dia": 86400, "dias": 86400,
        "w": 604800, "week": 604800, "weeks": 604800, "sem": 604800, "semanas": 604800,
    }
    seconds = n * factors[unit]
    return seconds if 60 <= seconds <= 28 * 86400 else None


def _moderator(member, permission):
    return isinstance(member, discord.Member) and (
        member.id == member.guild.owner_id or getattr(member.guild_permissions, permission, False)
    )


def _target_and_args(message, parts):
    target = message.mentions[0] if message.mentions else None
    if target is None and message.reference and message.reference.message_id:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                resolved = None
        if resolved is not None:
            target = getattr(resolved, "author", None)
    remainder = message.content
    for mention in message.mentions:
        remainder = remainder.replace(mention.mention, "", 1)
    if message.reference:
        remainder = re.sub(r"^\s*\?\w+(?:\s+\S+)?", "", remainder, count=1)
    else:
        remainder = re.sub(r"^\s*\?\w+", "", remainder, count=1)
    return target, remainder.strip()


def _target_error(actor, target):
    if not isinstance(target, discord.Member):
        return "Menciona a un miembro del servidor (o responde a su mensaje)."
    if target.bot:
        return "No puedes aplicar esta acción a un bot."
    if target.id == actor.id or target.id == actor.guild.owner_id:
        return "No puedes aplicarte esta acción a ti mismo ni al propietario."
    if actor.id != actor.guild.owner_id and target.top_role >= actor.top_role:
        return "No puedes moderar a alguien con un rol igual o superior al tuyo."
    bot_member = actor.guild.me
    if bot_member is None or target.top_role >= bot_member.top_role:
        return "El rol del miembro está por encima o al mismo nivel que el rol del bot."
    return None


async def _muted_role(guild):
    role = discord.utils.get(guild.roles, name="Silenciado")
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return None, "Al bot le falta Administrar roles."
    if role is None:
        try:
            role = await guild.create_role(name="Silenciado", reason="Rol de moderación para ?hardmute")
        except (discord.Forbidden, discord.HTTPException) as error:
            return None, f"No pude crear el rol Silenciado: {error}"
    if role >= me.top_role:
        return None, "El rol Silenciado debe estar debajo del rol del bot."
    # Add explicit deny overwrites to text channels so the role actually mutes.
    for channel in guild.text_channels:
        overwrite = channel.overwrites_for(role)
        overwrite.send_messages = False
        overwrite.send_messages_in_threads = False
        overwrite.add_reactions = False
        try:
            await channel.set_permissions(role, overwrite=overwrite, reason="Configurar rol Silenciado")
        except (discord.Forbidden, discord.HTTPException):
            continue
    return role, None


async def _restore_hardmute(guild, user_id, record):
    member = guild.get_member(int(user_id))
    if member is None:
        return False
    muted_role = guild.get_role(int(record.get("muted_role_id", 0)))
    roles = [guild.get_role(int(role_id)) for role_id in record.get("role_ids", [])]
    roles = [role for role in roles if role is not None and role < guild.me.top_role]
    try:
        await member.edit(roles=roles, reason="Finalización de hardmute; restaurar roles originales")
        if muted_role and muted_role in member.roles:
            await member.remove_roles(muted_role, reason="Finalización de hardmute")
        return True
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"No se pudieron restaurar roles de hardmute para {user_id}: {error}")
        return False


async def _expiry_worker(client):
    while not client.is_closed():
        now = int(time.time())
        with LOCK:
            data = _read()
            records = data.get("hardmutes", {})
            expired = [
                (key, value) for key, value in records.items()
                if value.get("expires_at") and int(value["expires_at"]) <= now
            ]
        for key, record in expired:
            guild = client.get_guild(int(record.get("guild_id", 0)))
            if guild and await _restore_hardmute(guild, record.get("user_id"), record):
                with LOCK:
                    data = _read()
                    data.get("hardmutes", {}).pop(key, None)
                    _write(data)
        await asyncio.sleep(60)


def register_moderation(client):
    async def on_ready():
        task = getattr(client, "moderation_expiry_task", None)
        if task is None or task.done():
            client.moderation_expiry_task = asyncio.create_task(_expiry_worker(client))
    if not getattr(client, "moderation_listener_registered", False):
        client.add_listener(on_ready, "on_ready")
        client.moderation_listener_registered = True


async def handle_moderation_command(message):
    """Handle requested ?mute/warn commands. Return True if command was consumed."""
    if message.guild is None or message.author.bot:
        return False
    parts = message.content.strip().split(maxsplit=1)
    command = parts[0].casefold() if parts else ""
    if command not in {"?hardmute", "?mute", "?unmute", "?mutelist", "?warn", "?unwarn", "?warns", "?clearwarns"}:
        return False

    actor = message.author
    if not isinstance(actor, discord.Member):
        await message.reply("Este comando solo funciona en un servidor.", mention_author=False)
        return True

    if command == "?mutelist":
        if not _moderator(actor, "manage_roles"):
            await message.reply("Necesitas Administrar roles para ver la lista.", mention_author=False)
            return True
        with LOCK:
            records = _read().get("hardmutes", {})
        current = [
            f"<@{record['user_id']}> — {('hasta <t:' + str(record['expires_at']) + ':R>') if record.get('expires_at') else 'sin vencimiento'}"
            for record in records.values()
            if int(record.get("guild_id", 0)) == message.guild.id
        ]
        timed = [f"<@{member.id}> — timeout hasta <t:{int(member.timed_out_until.timestamp())}:R>" for member in message.guild.members if member.timed_out_until and member.timed_out_until > datetime.now(timezone.utc)]
        lines = current + timed
        await message.reply("**Miembros silenciados:**\n" + ("\n".join(lines[:50]) if lines else "Ninguno."), mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True

    if command == "?warns" and len(message.mentions) == 1:
        if not _moderator(actor, "manage_messages"):
            await message.reply("Necesitas Administrar mensajes para consultar advertencias.", mention_author=False)
            return True
        target = message.mentions[0]
        with LOCK:
            entries = _read().get("warnings", {}).get(f"{message.guild.id}:{target.id}", [])
        description = "\n".join(f"**#{i + 1}** · <t:{int(item['timestamp'])}:d> — {discord.utils.escape_markdown(item.get('reason', 'Sin razón'))} (por <@{item['moderator_id']}>)" for i, item in enumerate(entries[-20:]))
        await message.reply(f"**Advertencias de {target.mention}**\n{description or 'Sin advertencias.'}", mention_author=False, allowed_mentions=discord.AllowedMentions.none())
        return True

    target, remainder = await _target_and_args(message, parts)
    if command == "?warn":
        if not _moderator(actor, "manage_messages"):
            await message.reply("Necesitas Administrar mensajes para advertir a miembros.", mention_author=False)
            return True
        error = _target_error(actor, target)
        if error:
            await message.reply(error, mention_author=False)
            return True
        reason = remainder or "Sin razón indicada"
        key = f"{message.guild.id}:{target.id}"
        entry = {"moderator_id": actor.id, "reason": reason[:500], "timestamp": int(time.time())}
        try:
            with LOCK:
                data = _read()
                data.setdefault("warnings", {}).setdefault(key, []).append(entry)
                _write(data)
        except OSError:
            await message.reply("No pude guardar la advertencia. Comprueba el almacenamiento persistente.", mention_author=False)
            return True
        await message.reply(f"⚠️ {target.mention} recibió la advertencia **#{len(data['warnings'][key])}**. Razón: {reason[:500]}", mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True

    if command == "?unwarn":
        if not _moderator(actor, "manage_messages"):
            await message.reply("Necesitas Administrar mensajes para quitar advertencias.", mention_author=False)
            return True
        error = _target_error(actor, target)
        tokens = remainder.split(maxsplit=1)
        if error or len(tokens) != 1 or not tokens[0].isdigit():
            await message.reply(error or "Uso: `?unwarn @usuario número`.", mention_author=False)
            return True
        key = f"{message.guild.id}:{target.id}"
        with LOCK:
            data = _read()
            entries = data.setdefault("warnings", {}).get(key, [])
            index = int(tokens[0]) - 1
            if not 0 <= index < len(entries):
                await message.reply("No existe ese número de advertencia.", mention_author=False)
                return True
            removed = entries.pop(index)
            data["warnings"][key] = entries
            _write(data)
        await message.reply(f"✅ Se eliminó la advertencia #{index + 1} de {target.mention}: {removed.get('reason', 'Sin razón')}.", mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True

    if command == "?clearwarns":
        if not _moderator(actor, "manage_messages"):
            await message.reply("Necesitas Administrar mensajes para borrar advertencias.", mention_author=False)
            return True
        error = _target_error(actor, target)
        if error:
            await message.reply(error, mention_author=False)
            return True
        key = f"{message.guild.id}:{target.id}"
        with LOCK:
            data = _read()
            count = len(data.setdefault("warnings", {}).pop(key, []))
            _write(data)
        await message.reply(f"✅ Se borraron {count} advertencia(s) de {target.mention}.", mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True

    if command == "?mute":
        if not _moderator(actor, "moderate_members"):
            await message.reply("Necesitas Moderar miembros para silenciar con timeout.", mention_author=False)
            return True
        error = _target_error(actor, target)
        if error:
            await message.reply(error, mention_author=False)
            return True
        reason = remainder or "Silenciado por moderación"
        try:
            until = datetime.now(timezone.utc) + timedelta(days=28)
            await target.timeout(until, reason=f"?mute por {actor}: {reason[:400]}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            await message.reply(f"No pude silenciar al miembro: {exc}", mention_author=False)
            return True
        await message.reply(f"🔇 {target.mention} quedó silenciado por 28 días. Razón: {reason[:500]}", mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True

    if command == "?unmute":
        if not _moderator(actor, "moderate_members") and not _moderator(actor, "manage_roles"):
            await message.reply("Necesitas Moderar miembros o Administrar roles para quitar el silencio.", mention_author=False)
            return True
        error = _target_error(actor, target)
        if error:
            await message.reply(error, mention_author=False)
            return True
        try:
            await target.timeout(None, reason=f"?unmute por {actor}")
            hardmute_role = discord.utils.get(message.guild.roles, name="Silenciado")
            if hardmute_role and hardmute_role in target.roles and _moderator(actor, "manage_roles"):
                with LOCK:
                    data = _read()
                    record_key = f"{message.guild.id}:{target.id}"
                    record = data.get("hardmutes", {}).get(record_key)
                    if record:
                        await _restore_hardmute(message.guild, target.id, record)
                        data["hardmutes"].pop(record_key, None)
                        _write(data)
                    else:
                        await target.remove_roles(hardmute_role, reason=f"?unmute por {actor}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            await message.reply(f"No pude quitar el silencio: {exc}", mention_author=False)
            return True
        await message.reply(f"🔊 Se quitó el silencio a {target.mention}.", mention_author=False, allowed_mentions=discord.AllowedMentions.users(True))
        return True

    if command == "?hardmute":
        if not _moderator(actor, "manage_roles"):
            await message.reply("Necesitas Administrar roles para usar hardmute.", mention_author=False)
            return True
        error = _target_error(actor, target)
        if error:
            await message.reply(error, mention_author=False)
            return True
        tokens = remainder.split(maxsplit=1)
        duration = _duration(tokens[0]) if tokens else None
        if tokens and re.fullmatch(r"\d+(?:m|min|h|hr|d|day|days|dia|dias|w|week|weeks|sem|semanas)", tokens[0], re.IGNORECASE) and duration is None:
            await message.reply("Duración no válida. Usa, por ejemplo, `30m`, `2h`, `3d` o `1w` (máximo 28d).", mention_author=False)
            return True
        reason = tokens[1] if duration and len(tokens) > 1 else remainder if not duration else "Sin razón indicada"
        role, role_error = await _muted_role(message.guild)
        if role_error:
            await message.reply(role_error, mention_author=False)
            return True
        key = f"{message.guild.id}:{target.id}"
        with LOCK:
            data = _read()
            existing = data.setdefault("hardmutes", {}).get(key)
        if existing:
            await message.reply("Ese miembro ya tiene hardmute activo. Usa `?unmute` primero.", mention_author=False)
            return True
        original_roles = [item.id for item in target.roles if not item.is_default() and item != role]
        try:
            if role not in target.roles:
                await target.add_roles(role, reason=f"?hardmute por {actor}: {reason[:400]}")
            for item in list(target.roles):
                if not item.is_default() and item != role:
                    await target.remove_roles(item, reason=f"?hardmute por {actor}")
        except (discord.Forbidden, discord.HTTPException) as exc:
            # Best-effort restore if removing any role fails partway through.
            for role_id in original_roles:
                original = message.guild.get_role(role_id)
                if original and original not in target.roles and original < message.guild.me.top_role:
                    try:
                        await target.add_roles(original, reason="Rollback fallido de ?hardmute")
                    except (discord.Forbidden, discord.HTTPException):
                        pass
            await message.reply(f"No pude completar hardmute: {exc}", mention_author=False)
            return True
        record = {
            "guild_id": message.guild.id, "user_id": target.id,
            "moderator_id": actor.id, "role_ids": original_roles,
            "muted_role_id": role.id,
            "expires_at": int(time.time()) + duration if duration else None,
            "reason": reason[:500],
        }
        try:
            with LOCK:
                data = _read()
                data.setdefault("hardmutes", {})[key] = record
                _write(data)
        except OSError:
            try:
                await _restore_hardmute(message.guild, target.id, record)
            except Exception:
                pass
            await message.reply("No pude guardar el hardmute; restauré los roles si fue posible. Comprueba el volumen persistente.", mention_author=False)
            return True
        expiry = f" hasta <t:{record['expires_at']}:R>" if duration else " sin vencimiento"
        await message.reply(f"🔇 {target.mention} recibió hardmute{expiry}. Sus roles se restaurarán al vencer o con `?unmute`. Razón: {reason[:500]}", mention_author=False, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
        return True

    return True


__all__ = ["handle_moderation_command", "register_moderation"]
