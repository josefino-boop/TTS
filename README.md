# Twitch TTS · Fish Audio

Lector de Twitch para Windows con interfaz Tkinter, selección de voz por usuario, preferencias persistentes y volumen ajustable. Incluye 27 voces. Solo procesa mensajes originados en el canal configurado durante chat compartido.

## Requisitos

Python 3.13 de 64 bits con Tcl/Tk, salida de audio y acceso a internet. Credenciales propias de Fish Audio y una aplicación de Twitch con OAuth de usuario.

## Instalación

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config/.env.example config/.env
```

Completar `FISH_API_KEY`, `TWITCH_CLIENT_ID` y `TWITCH_CHANNEL` en `config/.env`. El canal se indica sin URL ni `#`. Registrar `http://localhost:8765/callback` como redirección OAuth en la aplicación de Twitch.

```powershell
.\.venv\Scripts\python.exe autorizar.py
.\.venv\Scripts\python.exe ventana.pyw
```

La autorización solicita `chat:read` y `chat:edit` y guarda el token localmente. Reautorizar cuando caduque. La entrada de consola es `lector.py`.

## Uso

- `!voces` muestra el catálogo.
- `!voz nombre` selecciona una voz para ese usuario y guarda su elección.
- La voz inicial es Hatsune Miku. Las preferencias se crean en `datos/preferencias.json`.
- Editar `config/voces.json` para cambiar el catálogo y `config/bots.txt` para ignorar cuentas. Reiniciar tras editar.

## Implementación

- `lector.py` recibe IRC por WebSocket, filtra mensajes, gestiona la cola y genera/reproduce audio.
- `ventana.pyw` controla conexión y volumen desde Tkinter.
- `autorizar.py` implementa OAuth mediante callback HTTP temporal en loopback.

Usa exclusivamente `s2.1-pro-free`, sujeto a disponibilidad y condiciones de Fish Audio. Envía el texto a Fish y reproduce WAV a 44,1 kHz mediante sounddevice. Admite mensajes de hasta 500 caracteres, divididos en fragmentos de 140. La cola admite 20 mensajes. La salida es el dispositivo predeterminado de Windows y puede capturarse desde OBS.

## Estado

Se verificaron sintaxis, catálogo, configuración local y filtros con datos simulados. Quedan pendientes la instalación en un equipo limpio y la validación completa en directo. Se han reportado pronunciaciones incorrectas, pausas y robotización. No hay verificación por transcripción del audio. Revisar también la cancelación del hilo de reproducción y la parada inmediata al conectar. El token se valida al iniciar.

Mantener `.env`, tokens y datos de usuarios fuera del repositorio. Los ID públicos del catálogo no conceden derechos sobre voces o personajes.
