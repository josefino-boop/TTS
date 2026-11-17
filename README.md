# TTS para Twitch

Bot en Python que lee los mensajes de Twitch con voces de Fish Audio. Cada usuario puede elegir su voz con `!voz` y la elección se guarda para la próxima sesión. Incluye un catálogo de 27 voces.

## Requisitos

- Windows y Python 3.13 de 64 bits.
- Una API key de Fish Audio.
- Una aplicación de Twitch con su Client ID.
- Conexión a internet y una salida de audio.

## Instalación

Desde la carpeta del proyecto, ejecutar en PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config/.env.example config/.env
```

Completar estos valores en `config/.env`:

```dotenv
FISH_API_KEY=
TWITCH_CLIENT_ID=
TWITCH_CHANNEL=
```

En `TWITCH_CHANNEL` va el nombre del canal, sin URL ni `#`.

La aplicación se registra en [Twitch Developers](https://dev.twitch.tv/console/apps). Debe tener esta URL de redirección OAuth:

```text
http://localhost:8765/callback
```

## Autorizar e iniciar

```powershell
.\.venv\Scripts\python.exe autorizar.py
.\.venv\Scripts\python.exe lector.py
```

El primer comando abre la autorización de Twitch y guarda el token en `.env`. Solicita los permisos `chat:read` y `chat:edit`. El segundo inicia el lector. Para cerrarlo, pulsar `Ctrl+C`.

Si el token caduca, ejecutar de nuevo `autorizar.py`.

## Comandos

| Comando | Función |
|---|---|
| `!voces` | Muestra el catálogo disponible. |
| `!voz kiriko` | Cambia la voz de quien escribe el comando. |
| `!voz Hu Tao` | También acepta el nombre completo. |

La voz inicial es Hatsune Miku. Las elecciones se guardan en `datos/preferencias.json`.

El lector dice el nombre del usuario antes del mensaje. Filtra comandos, enlaces, emojis y emotes identificados por Twitch. En chat compartido solo lee mensajes escritos originalmente en el canal configurado.

## Archivos

- `lector.py` contiene la conexión IRC, los comandos, los filtros y la reproducción.
- `autorizar.py` gestiona la autorización de Twitch.
- `config/voces.json` contiene los nombres y los ID de las voces.
- `config/bots.txt` contiene las cuentas que se ignoran.

Para agregar una voz, añadir su nombre, comando, serie e ID a `voces.json` y reiniciar. La lista de `!voces` está cerca del límite de un mensaje de Twitch, así que hay que comprobar su tamaño al ampliar el catálogo.

## Audio

Usa el modelo `s2.1-pro-free` de Fish Audio y reproduce por la salida predeterminada de Windows. Su disponibilidad depende del proveedor. Para emitir el sonido, configurar la captura de audio correspondiente en OBS.

Acepta mensajes de hasta 500 caracteres y los divide en fragmentos de 140. La cola admite 20 mensajes pendientes.

## Pendientes

Se han reportado errores de pronunciación, pausas y voces robóticas durante el uso. Falta reproducir esos fallos de forma consistente y probar la instalación en un equipo limpio. También queda por revisar la parada del hilo de audio. El programa no comprueba mediante transcripción lo que devuelve Fish.

No subir `config/.env` ni la carpeta `datos`. Cada instalación debe usar sus propias credenciales. Los ID del catálogo no conceden derechos sobre las voces o los personajes.
