from pathlib import Path

MARKER = "# VANTARMOR_MESSAGE_REACTIONS_V2"
EVENT_MARKER = "@client.event\nasync def on_message(message):\n"


def patch_app_file(app_file: Path) -> None:
    """Set all reaction-command embeds and their button updates to blue."""
    source = app_file.read_text(encoding="utf-8")
    start = source.find(MARKER)
    if start < 0:
        raise RuntimeError("No encontré el bloque de reacciones generado en app.py.")
    end = source.find(EVENT_MARKER, start)
    if end < 0:
        raise RuntimeError("No encontré on_message después del bloque de reacciones.")

    block = source[start:end]
    block = block.replace("discord.Color.green()", "discord.Color.blurple()")
    block = block.replace("discord.Color.pink()", "discord.Color.blurple()")
    block = block.replace("discord.Color.orange()", "discord.Color.blurple()")
    source = source[:start] + block + source[end:]
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
