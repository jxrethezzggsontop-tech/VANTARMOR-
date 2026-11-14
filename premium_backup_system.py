import asyncio
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

import discord
from premium_store import is_premium_user as _central_is_premium_user

DATA_DIR = Path(os.getenv("VANTARMOR_DATA_DIR", "."))
PREMIUM_USERS_FILE = DATA_DIR / "premium_users.json"
PREMIUM_KEYS_FILE = DATA_DIR / "premium_keys.json"
BACKUP_FILE = DATA_DIR / "premium_backups.json"
BACKUP_INTERVAL = 5 * 60 * 60
_STORAGE_LOCK = threading.RLock()


def _read_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value if isinstance(value, type(default)) else default


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
        return True
    except OSError as error:
        print(f"No se pudo guardar {path.name}: {error}")
        return False


def premium_user_ids():
    users = _read_json(PREMIUM_USERS_FILE, {})
    now = int(time.time())
    ids = set()
    for user_id, value in users.items():
        if value is True:
            ids.add(str(user_id))
        elif isinstance(value, int) and not isinstance(value, bool) and value > now:
            ids.add(str(user_id))
        elif isinstance(value, dict):
            expiry = value.get("expires_at")
            if expiry is None:
                ids.add(str(user_id))
            else:
                try:
                    if int(expiry) > now:
                        ids.add(str(user_id))
                except (TypeError, ValueError):
                    continue
    ids.update(item.strip() for item in os.getenv("PREMIUM_USER_IDS", "").split(",") if item.strip().isdecimal())
    return ids


def is_premium_user(user_id):
    # Use exactly the same persistent entitlement store as website key redemption
    # and account status. The previous implementation read a second, stale JSON.
    return _central_is_premium_user(user_id)


def set_premium_user(user_id, enabled=True):
    from premium_store import set_premium_user as set_central_premium_user
    return set_central_premium_user(user_id, enabled)


def _key_digest(key):
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def generate_premium_key(days, created_by):
    if not 1 <= int(days) <= 3650:
        raise ValueError("La duración debe ser de 1 a 3650 días.")
    key = "VANT-" + secrets.token_urlsafe(24)
    digest = _key_digest(key)
    with _STORAGE_LOCK:
        keys = _read_json(PREMIUM_KEYS_FILE, {})
        keys[digest] = {"days": int(days), "created_at": int(time.time()), "created_by": str(created_by)}
        if not _write_json(PREMIUM_KEYS_FILE, keys):
            raise OSError("No se pudo guardar la key; no la compartas ni la uses.")
    return key


def redeem_premium_key(key, user_id):
    from premium_store import redeem_premium_key as redeem_central_premium_key
    return redeem_central_premium_key(key, user_id)


def is_premium_manager(user_id):
    configured_ids = {
        value.strip()
        for value in os.getenv("PREMIUM_MANAGER_IDS", "").split(",")
        if value.strip().isdecimal()
    }
    return str(user_id) in configured_ids


def _serialize_overwrites(overwrites):
    result = []
    for target, overwrite in overwrites.items():
        target_type = "role" if isinstance(target, discord.Role) else "member"
        allow, deny = overwrite.pair()
        result.append({"type": target_type, "id": target.id, "allow": allow.value, "deny": deny.value})
    return result


def _restore_overwrites(guild, entries):
    result = {}
    for entry in entries or []:
        target_id = int(entry["id"])
        target = guild.get_role(target_id) if entry.get("type") == "role" else guild.get_member(target_id)
        if target is None and entry.get("type") == "role" and target_id == guild.id:
            target = guild.default_role
        if target is None:
            continue
        allow = discord.Permissions(int(entry.get("allow", 0)))
        deny = discord.Permissions(int(entry.get("deny", 0)))
        result[target] = discord.PermissionOverwrite.from_pair(allow, deny)
    return result


def _channel_snapshot(channel):
    data = {
        "name": channel.name,
        "position": channel.position,
        "overwrites": _serialize_overwrites(channel.overwrites),
        "category": channel.category.name if channel.category else None,
    }
    if isinstance(channel, discord.TextChannel):
        data.update(type="text", topic=channel.topic, nsfw=channel.nsfw, slowmode_delay=channel.slowmode_delay)
    elif isinstance(channel, discord.VoiceChannel):
        data.update(type="voice", bitrate=channel.bitrate, user_limit=channel.user_limit)
    else:
        return None
    return data


async def save_server_snapshot(guild):
    snapshot = {
        "guild_id": guild.id,
        "guild_name": guild.name,
        "created_at": int(time.time()),
        "categories": [
            {"name": category.name, "position": category.position, "overwrites": _serialize_overwrites(category.overwrites)}
            for category in guild.categories
        ],
        "channels": [],
    }
    for channel in guild.channels:
        data = _channel_snapshot(channel)
        if data is not None:
            snapshot["channels"].append(data)
    with _STORAGE_LOCK:
        backups = _read_json(BACKUP_FILE, {})
        backups[str(guild.id)] = snapshot
        _write_json(BACKUP_FILE, backups)
    return snapshot


def load_server_snapshot(guild_id):
    return _read_json(BACKUP_FILE, {}).get(str(guild_id))


async def restore_server_snapshot(guild, snapshot=None):
    snapshot = snapshot or load_server_snapshot(guild.id)
    if not snapshot:
        return False, "No hay una copia guardada para este servidor."
    bot_member = guild.me
    if bot_member is None or not bot_member.guild_permissions.manage_channels:
        return False, "Al bot le falta el permiso Administrar canales."
    categories = {category.name: category for category in guild.categories}
    for item in snapshot.get("categories", []):
        if item["name"] in categories:
            continue
        try:
            categories[item["name"]] = await guild.create_category(
                item["name"], overwrites=_restore_overwrites(guild, item.get("overwrites")),
                reason="Restauración de copia de seguridad premium",
            )
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"No se pudo recrear la categoría {item['name']}: {error}")
    created = 0
    for item in snapshot.get("channels", []):
        category_name = item.get("category")
        category = categories.get(category_name) if category_name else None
        if category_name and category is None:
            continue
        existing = next((
            channel for channel in guild.channels
            if channel.name == item["name"]
            and (channel.category.name if channel.category else None) == category_name
            and ((item["type"] == "text" and isinstance(channel, discord.TextChannel))
                 or (item["type"] == "voice" and isinstance(channel, discord.VoiceChannel)))
        ), None)
        if existing is not None:
            continue
        try:
            overwrites = _restore_overwrites(guild, item.get("overwrites"))
            if item["type"] == "text":
                await guild.create_text_channel(
                    item["name"], category=category, topic=item.get("topic"),
                    nsfw=bool(item.get("nsfw", False)), slowmode_delay=int(item.get("slowmode_delay", 0)),
                    overwrites=overwrites, reason="Restauración de copia de seguridad premium",
                )
            elif item["type"] == "voice":
                await guild.create_voice_channel(
                    item["name"], category=category, bitrate=item.get("bitrate"),
                    user_limit=int(item.get("user_limit", 0)), overwrites=overwrites,
                    reason="Restauración de copia de seguridad premium",
                )
            created += 1
        except (discord.Forbidden, discord.HTTPException, TypeError, ValueError) as error:
            print(f"No se pudo recrear el canal {item['name']}: {error}")
    return True, f"Restauración completada. Se crearon {created} canal(es); no se borró ningún canal existente."


class BackupRestoreView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = int(guild_id)
        button = discord.ui.Button(label="Restaurar copia", style=discord.ButtonStyle.primary, custom_id=f"premium_backup:restore:{self.guild_id}")
        button.callback = self.restore_button
        self.add_item(button)

    async def restore_button(self, interaction):
        guild = interaction.client.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message("No pude encontrar el servidor.", ephemeral=interaction.guild is not None)
            return
        member = guild.get_member(interaction.user.id)
        if member is None:
            try:
                member = await guild.fetch_member(interaction.user.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None or not (member.id == guild.owner_id or member.guild_permissions.administrator):
            await interaction.response.send_message("Debes ser propietario o administrador de ese servidor.", ephemeral=interaction.guild is not None)
            return
        if not is_premium_user(member.id):
            await interaction.response.send_message("Tu cuenta no tiene Premium activo.", ephemeral=interaction.guild is not None)
            return
        await interaction.response.defer(ephemeral=interaction.guild is not None)
        success, message = await restore_server_snapshot(guild)
        await interaction.followup.send(("✅ " if success else "⚠️ ") + message, ephemeral=interaction.guild is not None)


async def _premium_admin_members(guild):
    for user_id in premium_user_ids():
        try:
            member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            continue
        if member.id == guild.owner_id or member.guild_permissions.administrator:
            yield member


async def _backup_and_notify(client):
    for guild in client.guilds:
        recipients = [member async for member in _premium_admin_members(guild)]
        if not recipients:
            continue
        await save_server_snapshot(guild)
        for member in recipients:
            try:
                await member.send(
                    f"**{guild.name}**\nCopia de seguridad guardada. Cuando quieras, pulsa el botón de abajo para restaurar la estructura del servidor.",
                    view=BackupRestoreView(guild.id),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException) as error:
                print(f"No pude enviar el DM de copia a {member.id}: {error}")


async def premium_backup_scheduler(client):
    while not client.is_closed():
        try:
            await _backup_and_notify(client)
        except Exception as error:
            print(f"Error al crear copias premium: {type(error).__name__}: {error}")
        await asyncio.sleep(BACKUP_INTERVAL)
