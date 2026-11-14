from pathlib import Path
import re


def patch_app_file(app_file: Path) -> None:
    """Register application commands globally instead of only in one guild.

    Also clear the old guild-scoped registrations left behind by the previous
    startup configuration before syncing the global command tree.
    """
    source = app_file.read_text(encoding="utf-8")

    # Convert command decorators and group registrations to global commands.
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

    # Clear the legacy guild-specific command set, then publish the complete
    # tree globally so it is available in every server where the bot is added.
    old_sync = '''        commands = await tree.sync(guild=GUILD)
        print(f"Comandos sincronizados: {len(commands)}")'''
    new_sync = '''        tree.clear_commands(guild=GUILD)
        await tree.sync(guild=GUILD)
        commands = await tree.sync()
        print(f"Comandos globales sincronizados: {len(commands)}")'''
    if old_sync in source:
        source = source.replace(old_sync, new_sync, 1)
    elif 'commands = await tree.sync()' not in source:
        raise RuntimeError("No encontré la sincronización de comandos de app.py.")

    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
