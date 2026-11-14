from pathlib import Path

IMPORT_LINE = "from premium_security_system import register_security_commands\n"
REGISTER_LINE = "register_security_commands(tree, client)\n"


def patch_app_file(app_file: Path) -> None:
    source = app_file.read_text(encoding="utf-8")
    import_anchor = "from discord import app_commands\n"
    if IMPORT_LINE not in source:
        if import_anchor not in source:
            raise RuntimeError("No encontré el punto de importación de app_commands en app.py.")
        source = source.replace(import_anchor, import_anchor + IMPORT_LINE, 1)
    tree_anchor = "tree = app_commands.CommandTree(client)\n"
    if REGISTER_LINE not in source:
        if tree_anchor not in source:
            raise RuntimeError("No encontré la creación del árbol de comandos en app.py.")
        source = source.replace(tree_anchor, tree_anchor + REGISTER_LINE, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
