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
- `PREMIUM_MANAGER_IDS`: IDs de Discord autorizados para administrar Premium, separados por comas.
- `PREMIUM_USER_IDS`: IDs con Premium manual permanente, separados por comas.
- `VANTARMOR_DATA_DIR`: ruta de datos persistente montada en Railway; monta un volumen en esa ruta para conservar Premium, ajustes de seguridad, tickets y estadísticas entre despliegues.
- `BOT_INVITE_URL`: opcional; URL personalizada de invitación.

Configura en el portal de Discord OAuth2 la misma URL `DISCORD_REDIRECT_URI` como Redirect URI y usa el scope `identify guilds`. La web arranca junto al bot en el puerto `PORT` de Railway.

## Seguridad Premium

Todos los comandos de seguridad requieren Premium activo y que el usuario sea propietario o administrador del servidor:
- `/anti-raid activar umbral ventana`: detecta ráfagas de miembros y activa el modo pánico.
- `/anti-nuke activar umbral ventana`: vigila borrados de canales/roles y baneos en audit log; al alcanzar umbral bloquea el envío para `@everyone` y notifica. No banea ni quita permisos a administradores automáticamente.
- `/anti-bot accion bot`: lista autorizada; los bots no autorizados nuevos se expulsan si el bot tiene `Kick Members`.
- `/filtro-cuentas dias rol_revision`: asigna un rol de revisión a cuentas más recientes que el umbral; el administrador debe configurar ese rol con permisos restringidos.
- `/lockdown activar`: congela el envío de `@everyone` en canales de texto y guarda sus permisos anteriores; `/lockdown activar:false` los restaura.
- `/captcha-panel canal rol_verificado`: publica un botón con un reto aritmético modal. Configura los permisos de `@everyone` para limitar el acceso hasta verificar.
- `/security-log canal` y `/security-status` permiten configurar alertas y consultar el estado.

El bot necesita permisos acordes a las funciones usadas, incluyendo Ver registro de auditoría, Administrar canales/roles y Expulsar miembros. Revisa cuidadosamente la jerarquía de roles. El modo pánico cambia permisos de envío en canales de texto existentes, no pausa invitaciones ni cambia automáticamente el nivel de verificación de Discord.

## Copias Premium

`/seguridad-copia` guarda estructura de categorías/canales del servidor donde se ejecuta. La restauración recrea categorías y canales que falten y no elimina los existentes. No conserva mensajes. Premium se valida mediante el mismo registro persistente que usa la web.
