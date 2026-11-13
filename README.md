# Vantarmor Commands

Bot de Discord con web de cuenta, acceso OAuth2, comandos y funciones Premium.

## Variables de Railway

Obligatorias para iniciar el bot:
- `DISCORD_TOKEN`: token privado del bot.

Para login web de Discord:
- `DISCORD_CLIENT_ID`: ID de aplicación del bot.
- `DISCORD_CLIENT_SECRET`: secreto OAuth de esa aplicación; nunca lo publiques.
- `DISCORD_REDIRECT_URI`: URL pública exacta terminada en `/auth/callback`.
- `PUBLIC_BASE_URL`: dominio HTTPS público de Railway (opcional, para cookies seguras si no está `RAILWAY_PUBLIC_DOMAIN`).

Para administración de keys y datos:
- `PREMIUM_MANAGER_IDS`: IDs de Discord autorizados para usar `/premium-generar-key`, separados por comas.
- `PREMIUM_USER_IDS`: IDs con Premium manual permanente, separados por comas.
- `VANTARMOR_DATA_DIR`: ruta de datos persistente montada en Railway; monta un volumen en esa ruta para conservar keys, Premium y estadísticas entre despliegues.
- `BOT_INVITE_URL`: opcional; URL personalizada de invitación. Por defecto se genera con permiso de administrador.

Configura en el portal de Discord OAuth2 la misma URL `DISCORD_REDIRECT_URI` como Redirect URI y usa el scope `identify guilds`. La web arranca junto al bot en el puerto `PORT` de Railway.

## Web

La web ofrece Inicio, Estado, Funciones, Invita bot, Planes y Ajustes; verifica usuarios con Discord OAuth2, muestra perfil/avatar, admite cerrar sesión y permite reclamar keys de un solo uso. La sección de compra enlaza con https://discord.gg/YD7uY3AHz. Los datos de estadísticas son cuentas que iniciaron sesión y el valor `BOT_GUILD_COUNT`; configura este último desde una fuente real si deseas mostrar conteo de servidores.

El precio de $3 se presenta como referencia y la compra se gestiona por Discord; no hay procesamiento de pagos integrado. Los comandos premium se validan en el bot y Discord puede seguir mostrando comandos a administradores; la web no puede cambiar esa limitación.

## Copias Premium

`/seguridad-copia` guarda estructura de categorías/canales del servidor donde se ejecuta. La restauración solo recrea lo que falta y no elimina canales existentes. No conserva mensajes. Premium se vincula a cuenta Discord.
