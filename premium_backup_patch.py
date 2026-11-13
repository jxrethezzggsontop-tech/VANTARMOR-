from pathlib import Path

IMPORTS = '''from premium_backup_system import (
    BackupRestoreView,
    is_premium_user,
    premium_backup_scheduler,
    save_server_snapshot,
)
from welcome_system import configure_welcome, disable_welcome
from welcome_tiers import configure_free_welcome, dispatch_welcome_tiered
'''

FREE_WELCOME_COMMAND = '''@tree.command(name="bienvenida", description="Configura la bienvenida gratuita del servidor", guild=GUILD)
@app_commands.default_permissions(administrator=True)
@app_commands.describe(canal="Canal donde se enviará la bienvenida", ping="Menciona al usuario al entrar", mostrar_numero="Muestra el número total de miembros", mensaje="Texto del mensaje de bienvenida")
async def bienvenida(interaction: discord.Interaction, canal: discord.TextChannel, ping: bool = True, mostrar_numero: bool = True, mensaje: str = "¡Bienvenido {mention}!"):
    if interaction.guild is None or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.administrator or interaction.user.id == interaction.guild.owner_id):
        await interaction.response.send_message("Solo un administrador o propietario puede configurar la bienvenida.", ephemeral=True)
        return
    _, result = await configure_free_welcome(interaction, canal, ping, mostrar_numero, mensaje)
    await interaction.response.send_message(result, ephemeral=True)


'''

PREMIUM_WELCOME_COMMAND = '''@tree.command(name="bienvenida-premium", description="Configura la bienvenida Premium con estilos y fondos avanzados", guild=GUILD)
@app_commands.choices(tipo_letra=[
    app_commands.Choice(name="Small caps: ᴀʙᴄ", value="smallcaps"),
    app_commands.Choice(name="Fraktur: 𝔞𝔟𝔠", value="fraktur"),
    app_commands.Choice(name="Fraktur negrita: 𝖆𝖇𝖈", value="boldfraktur"),
    app_commands.Choice(name="Doble: 𝕒𝕓𝕔", value="double"),
    app_commands.Choice(name="Negrita: 𝐚𝐛𝐜", value="bold"),
    app_commands.Choice(name="Itálica: 𝑎𝑏𝑐", value="italic"),
    app_commands.Choice(name="Script: 𝒶𝒷𝒸", value="script"),
    app_commands.Choice(name="Script negrita: 𝓪𝓫𝓬", value="boldscript"),
    app_commands.Choice(name="Fullwidth: ａｂｃ", value="fullwidth"),
    app_commands.Choice(name="Monoespaciada: 𝚊𝚋𝚌", value="mono"),
    app_commands.Choice(name="Sans negrita: 𝗮𝗯𝗰", value="sansbold"),
    app_commands.Choice(name="Tachada: a̶b̶c̶", value="strike"),
])
@app_commands.choices(fondo=[app_commands.Choice(name="Perfil del usuario", value="profile"), app_commands.Choice(name="URL de imagen", value="url"), app_commands.Choice(name="Fondo del servidor", value="server")])
@app_commands.choices(marco=[app_commands.Choice(name="Resplandor azul", value="glow"), app_commands.Choice(name="Dorado", value="gold"), app_commands.Choice(name="Violeta", value="violet"), app_commands.Choice(name="Menta", value="mint")])
@app_commands.describe(tipo_letra="Estilo de letra", fondo="Fondo del mensaje", mostrar_numero="Incluir número del miembro", marco="Diseño del marco", canal="Canal donde se enviará la bienvenida", ping="Menciona al usuario al entrar", mensaje="Texto del mensaje", imagen_url="URL HTTPS de la imagen si eliges fondo URL")
async def bienvenida_premium(interaction: discord.Interaction, tipo_letra: app_commands.Choice[str], fondo: app_commands.Choice[str], mostrar_numero: bool, marco: app_commands.Choice[str], canal: discord.TextChannel, ping: bool, mensaje: str, imagen_url: str = ""):
    guild = interaction.guild
    user = interaction.user
    if guild is None or not isinstance(user, discord.Member):
        await interaction.response.send_message("Este comando solo funciona dentro de un servidor.", ephemeral=True)
        return
    if not (user.guild_permissions.administrator or user.id == guild.owner_id):
        await interaction.response.send_message("Solo un administrador o propietario puede configurar la bienvenida Premium.", ephemeral=True)
        return
    if not is_premium_user(user.id):
        await interaction.response.send_message("Esta función requiere que tu cuenta tenga Premium activo.", ephemeral=True)
        return
    _, result = await configure_welcome(interaction, tipo_letra.value, fondo.value, imagen_url, mostrar_numero, marco.value, canal, ping, mensaje)
    await interaction.response.send_message(result, ephemeral=True)


'''

BACKUP_COMMAND = '''@tree.command(name="seguridad-copia", description="Guarda una copia de la estructura de este servidor", guild=GUILD)
@app_commands.default_permissions(administrator=True)
async def seguridad_copia(interaction: discord.Interaction):
    guild, member = interaction.guild, interaction.user
    if guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message("Este comando solo funciona en un servidor.", ephemeral=True)
        return
    if not is_premium_user(member.id):
        await interaction.response.send_message("Tu cuenta no tiene Premium activo.", ephemeral=True)
        return
    if not (member.id == guild.owner_id or member.guild_permissions.administrator):
        await interaction.response.send_message("Necesitas ser propietario o administrador del servidor.", ephemeral=True)
        return
    await save_server_snapshot(guild)
    await interaction.response.send_message(f"✅ Copia guardada únicamente para **{guild.name}**. La restauración recrea categorías y canales que falten y no elimina los existentes.", view=BackupRestoreView(guild.id), ephemeral=True)


'''


def patch_app_file(app_file: Path):
    source = app_file.read_text(encoding="utf-8")
    if "from welcome_tiers import configure_free_welcome" not in source:
        anchor = "from discord import app_commands\n"
        if anchor not in source:
            raise RuntimeError("No encontré el punto de importación en app.py.")
        source = source.replace(anchor, anchor + IMPORTS, 1)
    anchor = '@tree.command(name="ping", description="Comprueba si el bot responde", guild=GUILD)\n'
    for name, block in (("bienvenida", FREE_WELCOME_COMMAND), ("bienvenida-premium", PREMIUM_WELCOME_COMMAND), ("seguridad-copia", BACKUP_COMMAND)):
        if f'name="{name}"' not in source:
            if anchor not in source:
                raise RuntimeError(f"No encontré el lugar para registrar /{name}.")
            source = source.replace(anchor, block + anchor, 1)
    join_anchor = '    role = get_role(member.guild, "autorole")\n'
    welcome_dispatch = '    await dispatch_welcome_tiered(member)\n'
    if welcome_dispatch not in source:
        if join_anchor not in source:
            raise RuntimeError("No encontré on_member_join para conectar la bienvenida.")
        source = source.replace(join_anchor, join_anchor + welcome_dispatch, 1)
    ready_anchor = '    print(f"Conectado como {client.user}")\n'
    ready_code = '''    if not getattr(client, "premium_backup_views_registered", False):
        for server in client.guilds:
            client.add_view(BackupRestoreView(server.id))
        client.premium_backup_views_registered = True
    backup_task = getattr(client, "premium_backup_task", None)
    if backup_task is None or backup_task.done():
        client.premium_backup_task = asyncio.create_task(premium_backup_scheduler(client))
'''
    if "premium_backup_views_registered" not in source:
        if ready_anchor not in source:
            raise RuntimeError("No encontré el inicio de on_ready en app.py.")
        source = source.replace(ready_anchor, ready_anchor + ready_code, 1)
    app_file.write_text(source, encoding="utf-8")


__all__ = ["patch_app_file"]
