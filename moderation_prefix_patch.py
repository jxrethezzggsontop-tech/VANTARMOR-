from pathlib import Path

IMPORT_LINE = "from moderation_prefix_commands import handle_moderation_command, register_moderation\n"
REGISTER_LINE = "register_moderation(client)\n"
DISPATCH = "    if await handle_moderation_command(message):\n        return\n"


def patch_app_file(app_file: Path) -> None:
    source = app_file.read_text(encoding="utf-8")
    import_anchor = "from discord import app_commands\n"
    if IMPORT_LINE not in source:
        if import_anchor not in source:
            raise RuntimeError("No encontré el punto de importación de app_commands.")
        source = source.replace(import_anchor, import_anchor + IMPORT_LINE, 1)
    client_anchor = "client = discord.Client(intents=intents)\n"
    if REGISTER_LINE not in source:
        if client_anchor not in source:
            raise RuntimeError("No encontré la creación del cliente Discord.")
        source = source.replace(client_anchor, client_anchor + REGISTER_LINE, 1)
    content_anchor = "    content = message.content.strip()\n"
    if DISPATCH not in source:
        if content_anchor not in source:
            raise RuntimeError("No encontré el inicio del manejador on_message.")
        source = source.replace(content_anchor, content_anchor + DISPATCH, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
