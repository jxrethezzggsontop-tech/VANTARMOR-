import hashlib
import json
import os
import secrets
import threading
import time
from pathlib import Path

DATA_DIR = Path(os.getenv("VANTARMOR_DATA_DIR", "."))
PREMIUM_USERS_FILE = DATA_DIR / "premium_users.json"
PREMIUM_KEYS_FILE = DATA_DIR / "premium_keys.json"
PREMIUM_REVOKED_FILE = DATA_DIR / "premium_revoked.json"
WEB_STATS_FILE = DATA_DIR / "web_stats.json"
_lock = threading.RLock()


def _read(path, fallback):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, type(fallback)) else fallback
    except (OSError, json.JSONDecodeError):
        return fallback


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _key_hash(key):
    return hashlib.sha256(key.strip().upper().encode("utf-8")).hexdigest()


def is_premium_manager(user_id):
    managers = {item.strip() for item in os.getenv("PREMIUM_MANAGER_IDS", "").split(",") if item.strip().isdecimal()}
    return str(user_id) in managers


def _revoked_users():
    return {str(value) for value in _read(PREMIUM_REVOKED_FILE, [])}


def premium_expiry(user_id):
    uid = str(user_id)
    if uid in _revoked_users():
        return 0
    users = _read(PREMIUM_USERS_FILE, {})
    entry = users.get(uid)
    now = int(time.time())
    if entry is True:
        return None
    if isinstance(entry, int) and not isinstance(entry, bool):
        return entry if entry > now else 0
    if isinstance(entry, dict):
        expiry = entry.get("expires_at")
        if expiry is None:
            return None
        try:
            expiry = int(expiry)
            return expiry if expiry > now else 0
        except (TypeError, ValueError):
            return 0
    env_ids = {item.strip() for item in os.getenv("PREMIUM_USER_IDS", "").split(",") if item.strip()}
    return None if uid in env_ids else 0


def is_premium_user(user_id):
    expiry = premium_expiry(user_id)
    return expiry is None or expiry > int(time.time())


def set_premium_user(user_id, enabled=True, *, expires_at=None, source="web_admin"):
    uid = str(user_id)
    with _lock:
        users = _read(PREMIUM_USERS_FILE, {})
        revoked = _revoked_users()
        if enabled:
            users[uid] = {"expires_at": None if expires_at is None else int(expires_at), "source": source}
            revoked.discard(uid)
        else:
            users.pop(uid, None)
            revoked.add(uid)
        _write(PREMIUM_USERS_FILE, users)
        _write(PREMIUM_REVOKED_FILE, sorted(revoked))
        return users.get(uid)


def _registered_ids():
    stats = _read(WEB_STATS_FILE, {"users": []})
    return {str(value) for value in stats.get("users", [])}


def grant_registered_user(user_id, *, days=None):
    uid = str(user_id)
    if not uid.isdecimal():
        raise ValueError("El ID de usuario no es válido.")
    if uid not in _registered_ids():
        raise ValueError("Ese usuario aún no ha iniciado sesión en la web.")
    if days is not None and not 1 <= int(days) <= 3650:
        raise ValueError("La duración debe estar entre 1 y 3650 días.")
    expiry = None if days is None else int(time.time()) + int(days) * 86400
    set_premium_user(uid, True, expires_at=expiry, source="web_admin")
    return {"user_id": uid, "expires_at": expiry}


def revoke_user_premium(user_id):
    uid = str(user_id)
    if not uid.isdecimal():
        raise ValueError("El ID de usuario no es válido.")
    if uid not in _registered_ids():
        raise ValueError("Ese usuario aún no ha iniciado sesión en la web.")
    set_premium_user(uid, False)
    return True


def registered_web_users():
    stats = _read(WEB_STATS_FILE, {"users": []})
    profiles = stats.get("profiles", {}) if isinstance(stats.get("profiles", {}), dict) else {}
    users = sorted({str(value) for value in stats.get("users", []) if str(value).isdecimal()})
    return [{"id": uid, "name": profiles.get(uid, {}).get("name", ""), "username": profiles.get(uid, {}).get("username", ""), "premium": is_premium_user(uid), "expires_at": premium_expiry(uid)} for uid in users]


def generate_premium_key(days, creator_id):
    days = int(days)
    if not 1 <= days <= 3650:
        raise ValueError("La duración debe estar entre 1 y 3650 días.")
    key = "VANT-" + secrets.token_urlsafe(24)
    with _lock:
        keys = _read(PREMIUM_KEYS_FILE, {})
        keys[_key_hash(key)] = {"days": days, "created_at": int(time.time()), "created_by": str(creator_id), "redeemed_by": None, "redeemed_at": None}
        _write(PREMIUM_KEYS_FILE, keys)
    return key


def redeem_premium_key(key, user_id):
    if not isinstance(key, str) or not key.strip():
        return False
    digest = _key_hash(key)
    with _lock:
        keys = _read(PREMIUM_KEYS_FILE, {})
        record = keys.get(digest)
        if not isinstance(record, dict) or record.get("redeemed_by") or record.get("redeemed_at"):
            return False
        users = _read(PREMIUM_USERS_FILE, {})
        uid = str(user_id)
        if is_premium_user(uid):
            return False
        now = int(time.time())
        users[uid] = {"expires_at": now + int(record.get("days", 0)) * 86400, "source": "key", "key_hash": digest}
        record["redeemed_by"] = uid
        record["redeemed_at"] = now
        keys[digest] = record
        _write(PREMIUM_USERS_FILE, users)
        return _write(PREMIUM_KEYS_FILE, keys) is None


def delete_premium_key(key):
    if not isinstance(key, str) or not key.strip():
        return False
    digest = _key_hash(key)
    with _lock:
        keys = _read(PREMIUM_KEYS_FILE, {})
        record = keys.get(digest)
        if not isinstance(record, dict):
            return False
        users = _read(PREMIUM_USERS_FILE, {})
        uid = record.get("redeemed_by")
        if uid is not None:
            entitlement = users.get(str(uid))
            if isinstance(entitlement, dict) and entitlement.get("key_hash") == digest:
                users.pop(str(uid), None)
                _write(PREMIUM_USERS_FILE, users)
        keys.pop(digest, None)
        _write(PREMIUM_KEYS_FILE, keys)
    return True


def register_web_user(user_id, profile=None):
    with _lock:
        stats = _read(WEB_STATS_FILE, {"users": []})
        users = {str(value) for value in stats.get("users", [])}
        uid = str(user_id)
        users.add(uid)
        stats["users"] = sorted(users)
        stats.setdefault("profiles", {})
        if isinstance(profile, dict):
            stats["profiles"][uid] = {
                "name": str(profile.get("global_name") or profile.get("username") or "")[:100],
                "username": str(profile.get("username") or "")[:100],
            }
        _write(WEB_STATS_FILE, stats)
        return len(users)


def public_stats():
    stats = _read(WEB_STATS_FILE, {"users": []})
    try:
        servers = int(os.getenv("BOT_GUILD_COUNT", "0") or 0)
    except ValueError:
        servers = 0
    return {"website_users": len({str(value) for value in stats.get("users", [])}), "servers": servers}
