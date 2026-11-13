import base64
import json
import os
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from premium_store import (
    delete_premium_key,
    generate_premium_key,
    is_premium_manager,
    is_premium_user,
    public_stats,
    redeem_premium_key,
    register_web_user,
    registered_web_users,
    revoke_user_premium,
    grant_registered_user,
)

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "website"
DISCORD_API = "https://discord.com/api/v10"
SESSIONS = {}
LOCK = threading.RLock()


def oauth_config():
    return {"client_id": os.getenv("DISCORD_CLIENT_ID", "").strip(), "client_secret": os.getenv("DISCORD_CLIENT_SECRET", "").strip(), "redirect_uri": os.getenv("DISCORD_REDIRECT_URI", "").strip()}


def discord_request(path, *, token=None, form=None, basic=None):
    headers = {"Accept": "application/json", "User-Agent": "Vantarmor-Commands/1.0"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if basic:
        headers["Authorization"] = f"Basic {basic}"
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(form).encode("utf-8")
    request = Request(DISCORD_API + path, data=body, headers=headers)
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' https://cdn.discordapp.com data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=400):
        self.send_json({"error": message}, status)

    def redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def get_cookie(self, name):
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
            item = jar.get(name)
            return item.value if item else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def cookie_header(name, value, max_age):
        secure = "; Secure" if os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("PUBLIC_BASE_URL", "").startswith("https://") else ""
        return f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def get_session(self):
        sid = self.get_cookie("vantarmor_session")
        with LOCK:
            session = SESSIONS.get(sid) if sid else None
            if session and session["expires"] > time.time():
                return session
            if sid:
                SESSIONS.pop(sid, None)
        return None

    def require_admin(self, session):
        return bool(session and is_premium_manager(session["user"].get("id", "")))

    def require_csrf(self, session):
        return bool(session and secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]))

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096:
            raise ValueError("Tamaño de solicitud no válido.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Solicitud no válida.")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/auth/discord":
            cfg = oauth_config()
            if not all(cfg.values()):
                return self.send_error_json("Configura DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET y DISCORD_REDIRECT_URI en Railway.", 503)
            state = secrets.token_urlsafe(32)
            query = urlencode({"client_id": cfg["client_id"], "response_type": "code", "redirect_uri": cfg["redirect_uri"], "scope": "identify guilds", "state": state})
            self.send_response(302)
            self.send_header("Location", "https://discord.com/oauth2/authorize?" + query)
            self.send_header("Set-Cookie", self.cookie_header("vantarmor_oauth_state", state, 600))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        if path == "/auth/callback":
            cfg = oauth_config()
            query = parse_qs(urlparse(self.path).query)
            state = query.get("state", [""])[0]
            if not state or not secrets.compare_digest(state, self.get_cookie("vantarmor_oauth_state") or ""):
                return self.send_error_json("Falló la verificación de inicio de sesión. Inténtalo otra vez.", 400)
            code = query.get("code", [""])[0]
            if not code:
                return self.send_error_json("Discord no autorizó el acceso.", 400)
            try:
                credentials = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
                tokens = discord_request("/oauth2/token", form={"grant_type": "authorization_code", "code": code, "redirect_uri": cfg["redirect_uri"]}, basic=credentials)
                access_token = tokens["access_token"]
                user = discord_request("/users/@me", token=access_token)
            except (HTTPError, URLError, KeyError, ValueError, OSError) as exc:
                print(f"Discord OAuth falló: {type(exc).__name__}")
                return self.send_error_json("No se pudo completar el inicio de sesión. Revisa las variables OAuth y la URL de retorno.", 502)
            sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            register_web_user(user["id"], user)
            with LOCK:
                SESSIONS[sid] = {"user": user, "access_token": access_token, "csrf": csrf, "expires": time.time() + min(int(tokens.get("expires_in", 3600)), 86400)}
            self.send_response(302)
            self.send_header("Location", "/?login=ok")
            self.send_header("Set-Cookie", self.cookie_header("vantarmor_session", sid, 86400))
            self.send_header("Set-Cookie", self.cookie_header("vantarmor_oauth_state", "", 0))
            self.end_headers()
            return
        if path == "/auth/logout":
            sid = self.get_cookie("vantarmor_session")
            with LOCK:
                SESSIONS.pop(sid, None)
            self.redirect("/")
            self.send_header("Set-Cookie", self.cookie_header("vantarmor_session", "", 0))
            return
        if path == "/api/me":
            session = self.get_session()
            if not session:
                return self.send_json({"authenticated": False}, 401)
            user = session["user"]
            avatar_hash = user.get("avatar")
            avatar = f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar_hash}.png?size=256" if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{int(user['id']) % 6}.png"
            return self.send_json({"authenticated": True, "is_admin": self.require_admin(session), "csrf": session["csrf"], "user": {"id": user["id"], "name": user.get("global_name") or user.get("username"), "username": user.get("username"), "avatar": avatar}, "premium": is_premium_user(user["id"])})
        if path == "/api/stats":
            return self.send_json(public_stats())
        if path == "/api/admin/users":
            session = self.get_session()
            if not session:
                return self.send_error_json("Inicia sesión con Discord.", 401)
            if not self.require_admin(session):
                return self.send_error_json("No tienes permiso para administrar Premium.", 403)
            return self.send_json({"users": registered_web_users()})
        if path == "/api/guilds":
            session = self.get_session()
            if not session:
                return self.send_json({"error": "inicia_sesion"}, 401)
            try:
                guilds = discord_request("/users/@me/guilds", token=session["access_token"])
                manageable = [g for g in guilds if g.get("owner") or int(g.get("permissions", "0")) & 0x8]
                return self.send_json({"guilds": [{"id": g["id"], "name": g["name"]} for g in manageable]})
            except (HTTPError, URLError, ValueError, OSError):
                return self.send_json({"guilds": []})
        if path == "/config.json":
            cfg = oauth_config()
            return self.send_json({"auth_enabled": bool(all(cfg.values())), "bot_client_id": cfg["client_id"], "invite_url": os.getenv("BOT_INVITE_URL", "")})
        if path in ("/admin", "/admin.html"):
            session = self.get_session()
            if not session:
                return self.redirect("/auth/discord")
            if not self.require_admin(session):
                return self.send_error(403, "No autorizado para administrar Premium")
            self.path = "/admin.html"
            return super().do_GET()
        if path in ("/", "/index.html") or path.startswith("/assets/"):
            return super().do_GET()
        return self.send_error(404, "Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        session = self.get_session()
        if not session:
            return self.send_error_json("Inicia sesión con Discord primero.", 401)
        if path == "/api/redeem":
            if not self.require_csrf(session):
                return self.send_error_json("Verificación de seguridad fallida. Recarga e inténtalo otra vez.", 403)
            try:
                data = self.read_json_body()
                key = str(data.get("key", "")).strip()
            except (ValueError, json.JSONDecodeError):
                return self.send_error_json("Solicitud no válida.", 400)
            if not key or len(key) > 160:
                return self.send_error_json("Introduce una key válida.", 400)
            user_id = session["user"]["id"]
            if is_premium_user(user_id):
                return self.send_json({"ok": False, "message": "Tu cuenta ya tiene Premium activo."}, 409)
            try:
                success = redeem_premium_key(key, user_id)
            except OSError as exc:
                print(f"No se pudo guardar Premium: {type(exc).__name__}")
                return self.send_error_json("No se pudo guardar el plan. Inténtalo más tarde.", 500)
            if not success:
                return self.send_json({"ok": False, "message": "La key no existe, ya fue usada o no es válida."}, 400)
            return self.send_json({"ok": True, "message": "¡Premium activado en tu cuenta!"})
        if path not in ("/api/admin/grant", "/api/admin/revoke", "/api/admin/keys/generate", "/api/admin/keys/revoke"):
            return self.send_error_json("No encontrado.", 404)
        if not self.require_admin(session):
            return self.send_error_json("No tienes permiso para administrar Premium.", 403)
        if not self.require_csrf(session):
            return self.send_error_json("Verificación de seguridad fallida.", 403)
        try:
            data = self.read_json_body()
            if path == "/api/admin/keys/generate":
                days = int(data.get("days", 0))
                key = generate_premium_key(days, session["user"]["id"])
                return self.send_json({"ok": True, "key": key, "days": days})
            if path == "/api/admin/keys/revoke":
                key = str(data.get("key", "")).strip()
                if not delete_premium_key(key):
                    return self.send_error_json("La key no existe o no es válida.", 400)
                return self.send_json({"ok": True, "message": "Key eliminada; si estaba canjeada, se revocó el Premium que concedió."})
            user_id = str(data.get("user_id", ""))
            if path.endswith("/grant"):
                permanent = bool(data.get("permanent", False))
                days = None if permanent else int(data.get("days", 0))
                grant_registered_user(user_id, days=days)
                return self.send_json({"ok": True, "message": "Premium concedido correctamente."})
            revoke_user_premium(user_id)
            return self.send_json({"ok": True, "message": "Premium revocado."})
        except (ValueError, TypeError) as exc:
            return self.send_error_json(str(exc), 400)
        except OSError as exc:
            print(f"No se pudo guardar Premium: {type(exc).__name__}")
            return self.send_error_json("No se pudo guardar el cambio. Inténtalo de nuevo.", 500)


def start_website():
    if not (WEB_DIR / "index.html").is_file():
        print("No existe website/index.html; omito el servidor web.")
        return None
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="vantarmor-web", daemon=True).start()
    print(f"Web de Vantarmor escuchando en el puerto {port}")
    return server
