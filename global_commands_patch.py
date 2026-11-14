from pathlib import Path
import re


def patch_app_file(app_file: Path) -> None:
    """Register application commands globally instead of only in one guild.

    Clear old guild-scoped registrations so stale commands from the previous
    single-server setup do not linger in Discord.
    """
    source = app_file.read_text(encoding="utf-8")
    source = re.sub(
        r'(?m)^(@tree\.command\([^\n]*),\s*guild=GUILD(\)\s*)$',
        r'\1\2',
        source,
    )
    source = re.sub(
        r'(?m)^([ \t]*tree\.add_command\([^\n]*),\s*guild=GUILD(\)\s*)$',
        r'\1\2',
        source,
    )

    # Remove guild-only registration, then publish the same command tree globally.
    source = re.sub(
        r'(?m)^\s*commands = await tree\.sync\(guild=GUILD\)\n\s*print\(f"Comandos sincronizados: \{len\(commands\)\}"\)\n?',
        '        tree.clear_commands(guild=GUILD)\n'
        '        await tree.sync(guild=GUILD)\n'
        '        commands = await tree.sync()\n'
        '        print(f"Comandos globales sincronizados: {len(commands)}")\n',
        source,
    )
    if 'commands = await tree.sync()' not in source:
        raise RuntimeError("No encontré ni pude actualizar la sincronización de comandos en app.py.")

    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
