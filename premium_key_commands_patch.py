from pathlib import Path
import re


def patch_app_file(app_file: Path):
    """Remove Premium key-management slash commands before the bot starts.

    premium_backup_patch.py currently injects legacy key commands. Strip those
    command definitions and their now-unused imports from the generated app so
    Discord's next guild sync removes them from the command list.
    """
    source = app_file.read_text(encoding="utf-8")
    source, removed_commands = re.subn(
        r'(?ms)^@tree\.command\(name="(?:premium-generar-key|premium-key-delete)"[^\n]*\)\n.*?(?=^@tree\.command|\Z)',
        "",
        source,
    )
    source = re.sub(
        r'(?m)^from premium_store import \(\n\s*delete_premium_key,\n\s*generate_premium_key,\n\s*is_premium_manager,\n\)\n',
        "",
        source,
    )
    if removed_commands:
        app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
