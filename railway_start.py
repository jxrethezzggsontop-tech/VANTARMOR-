import runpy
from pathlib import Path

from message_reactions_patch import patch_app as patch_message_features
from premium_backup_patch import patch_app_file as patch_premium_features
from premium_key_commands_patch import patch_app_file as remove_premium_key_commands
from global_commands_patch import patch_app_file as patch_global_commands
from ticket_image_patch import patch_app_file as patch_ticket_image
from blue_reaction_embeds_patch import patch_app_file as patch_blue_reaction_embeds
from web_server import start_website

ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"
WELCOME_FILE = ROOT / "welcome_system.py"


def fix_welcome_async_declaration():
    """Repair the async welcome configurator before app.py imports it."""
    source = WELCOME_FILE.read_text(encoding="utf-8")
    broken = "\ndef configure_welcome("
    fixed = "\nasync def configure_welcome("
    if broken in source and fixed not in source:
        WELCOME_FILE.write_text(source.replace(broken, fixed, 1), encoding="utf-8")
        print("Corregida la declaración async de configure_welcome.")


def main():
    if not APP_FILE.is_file():
        raise FileNotFoundError(f"No encontré el archivo del bot: {APP_FILE}")
    fix_welcome_async_declaration()
    patch_message_features(APP_FILE)
    patch_premium_features(APP_FILE)
    remove_premium_key_commands(APP_FILE)
    patch_ticket_image(APP_FILE)
    patch_blue_reaction_embeds(APP_FILE)
    patch_global_commands(APP_FILE)
    start_website()
    print("Iniciando Vantarmor Commands...")
    runpy.run_path(str(APP_FILE), run_name="__main__")


if __name__ == "__main__":
    main()
