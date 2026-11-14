"""Server-scoped bot profile settings exposed to the signed-in account page.

These update the bot's guild member profile only (guild nickname and guild
avatar), never the bot's global username/avatar.
"""
import base64
import ipaddress
import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, UnidentifiedImageError

DISCORD_API = "https://discord.com/api/v10"
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _discord_json(path, *, token, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        DISCORD_API + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Accept": "application/json",
            "User-Agent": "Vantarmor-Commands/1.0",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read(1024 * 1024)
        return json.loads(raw.decode("utf-8")) if raw else {}


def _download_avatar(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("La imagen debe ser una URL HTTPS pública.")
    if parsed.port not in (None, 443):
        raise ValueError("La imagen debe usar HTTPS en el puerto estándar.")
    host = parsed.hostname.rstrip(".")
    if host.casefold() == "localhost" or host.casefold().endswith(".local"):
        raise ValueError("La URL no puede apuntar a un host local.")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as error:
        raise ValueError("No se pudo resolver el host de la imagen.") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("La URL debe apuntar a un servidor público.")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            return None

    request = urllib.request.Request(url, headers={"User-Agent": "Vantarmor-Commands/1.0"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
            if not response.headers.get_content_type().startswith("image/"):
                raise ValueError("La URL debe apuntar directamente a un archivo de imagen.")
            image_data = response.read(MAX_AVATAR_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ValueError("No se pudo descargar la imagen; usa un enlace directo y público.") from error
    if not image_data or len(image_data) > MAX_AVATAR_BYTES:
        raise ValueError("La imagen debe pesar como máximo 5 MB.")
    try:
        with Image.open(io.BytesIO(image_data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                raise ValueError("Usa una imagen PNG, JPG, WEBP o GIF.")
            if image.width * image.height > 20_000_000:
                raise ValueError("La resolución de la imagen es demasiado grande.")
            image.verify()
            fmt = image.format.lower()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("El enlace no contiene una imagen válida.") from error
    mime = "jpeg" if fmt == "jpg" else fmt
    return f"data:image/{mime};base64,{base64.b64encode(image_data).decode('ascii')}"


def _manageable_guild_ids(handler, session):
    try:
        guilds = handler.server.discord_request("/users/@me/guilds", token=session["access_token"])
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        raise ValueError("No pude consultar tus servidores de Discord; inicia sesión otra vez.")
    result = {}
    for guild in guilds:
        permissions = int(guild.get("permissions", "0"))
        if guild.get("owner") or permissions & (0x8 | 0x20):
            result[str(guild["id"])] = guild.get("name", "Servidor")
    return result


def _require_bot_in_guild(guild_id):
    token = __import__("os").getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise ValueError("Falta configurar DISCORD_TOKEN en Railway.")
    try:
        _discord_json(f"/guilds/{guild_id}", token=token)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as error:
        raise ValueError("El bot no está en ese servidor o no puede acceder a él.") from error
    return token


def install_guild_profile_settings(handler_class):
    """Wrap the existing static-site handler with the server-profile API."""
    old_get = handler_class.do_GET
    old_post = handler_class.do_POST

    def do_get(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/settings/guilds":
            return old_get(self)
        session = self.get_session()
        if not session:
            return self.send_error_json("Inicia sesión con Discord.", 401)
        try:
            guilds = _manageable_guild_ids(self, session)
            token = __import__("os").getenv("DISCORD_TOKEN", "").strip()
            if not token:
                raise ValueError("Falta configurar DISCORD_TOKEN en Railway.")
            visible = []
            for guild_id, name in guilds.items():
                try:
                    _discord_json(f"/guilds/{guild_id}", token=token)
                except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
                    continue
                visible.append({"id": guild_id, "name": name})
            return self.send_json({"guilds": visible})
        except ValueError as error:
            return self.send_error_json(str(error), 502)

    def do_post(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/settings/guild-profile":
            return old_post(self)
        session = self.get_session()
        if not session:
            return self.send_error_json("Inicia sesión con Discord primero.", 401)
        if not self.require_csrf(session):
            return self.send_error_json("Verificación de seguridad fallida. Recarga e inténtalo otra vez.", 403)
        try:
            data = self.read_json_body()
            guild_id = str(data.get("guild_id", ""))
            nickname = str(data.get("nickname", "")).strip()
            avatar_url = str(data.get("avatar_url", "")).strip()
            if not guild_id.isdecimal():
                raise ValueError("Selecciona un servidor válido.")
            if len(nickname) > 32:
                raise ValueError("El apodo no puede superar 32 caracteres.")
            manageable = _manageable_guild_ids(self, session)
            if guild_id not in manageable:
                raise ValueError("Debes ser propietario o administrador del servidor seleccionado.")
            token = _require_bot_in_guild(guild_id)
            payload = {"nick": nickname or None}
            if avatar_url:
                payload["avatar"] = _download_avatar(avatar_url)
            else:
                payload["avatar"] = None
            _discord_json(f"/guilds/{guild_id}/members/@me", token=token, method="PATCH", payload=payload)
            return self.send_json({"ok": True, "message": f"Ajustes visuales actualizados para {manageable[guild_id]}."})
        except (ValueError, json.JSONDecodeError) as error:
            return self.send_error_json(str(error), 400)
        except urllib.error.HTTPError as error:
            if error.code == 403:
                return self.send_error_json("Discord rechazó el cambio. Comprueba que el bot esté en el servidor y tenga permisos para cambiar su apodo.", 403)
            return self.send_error_json("Discord no pudo actualizar el perfil del bot.", 502)
        except (urllib.error.URLError, OSError) as error:
            return self.send_error_json("No se pudo conectar con Discord.", 502)

    handler_class.do_GET = do_get
    handler_class.do_POST = do_post
    handler_class.server = __import__("web_server")


__all__ = ["install_guild_profile_settings"]
