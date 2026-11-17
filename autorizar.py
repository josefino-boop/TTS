"""OAuth directo de Twitch: callback loopback; no secreto de cliente."""
import hmac
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode

import httpx
from dotenv import set_key

from pathlib import Path
from dotenv import dotenv_values
ROOT = Path(__file__).resolve().parent
def require(values, names):
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise ValueError('Falta configuración: ' + ', '.join(missing))
class ServiceError(RuntimeError): pass

REDIRECT = "http://localhost:8765/callback"
ORIGIN = "http://localhost:8765"


def validate_token(creds):
    require(creds, ("TWITCH_CLIENT_ID", "TWITCH_TOKEN"))
    token = creds["TWITCH_TOKEN"].removeprefix("oauth:")
    with httpx.Client(trust_env=False, timeout=15) as client:
        response = client.get("https://id.twitch.tv/oauth2/validate",
                              headers={"Authorization": "OAuth " + token})
    if response.status_code != 200:
        raise ServiceError("Twitch: autorización inválida o vencida. Ejecuta python autorizar.py.")
    data = response.json()
    if data.get("client_id") != creds["TWITCH_CLIENT_ID"]:
        raise ServiceError("El token no pertenece a esta aplicación. Ejecuta python autorizar.py.")
    if not data.get("login") or not {"chat:read", "chat:edit"}.issubset(set(data.get("scopes", []))):
        raise ServiceError("La autorización necesita una cuenta de usuario y los permisos chat:read y chat:edit.")
    if creds.get("TWITCH_BOT_LOGIN") and data["login"].lower() != creds["TWITCH_BOT_LOGIN"].lower():
        raise ServiceError("El usuario del token no coincide con TWITCH_BOT_LOGIN. Vuelve a conectar Twitch.")
    return data


def authorize(creds, open_browser=True, wait_seconds=300, cancel_event=None):
    require(creds, ("TWITCH_CLIENT_ID",))
    state = secrets.token_urlsafe(32)
    done = threading.Event()
    outcome = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Nunca registrar URL, fragmentos o cuerpo con credenciales.

        def reply(self, status, body, content_type="text/plain; charset=utf-8"):
            body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != "localhost:8765" or self.path.split("?", 1)[0] != "/callback":
                self.reply(404, "Ruta no disponible.")
                return
            self.reply(200, '''<!doctype html><html lang="es"><meta charset="utf-8">
<title>Conectar lector de chat con Twitch</title><h2 id="estado">Comprobando autorización…</h2>
<script>
const fields = new URLSearchParams(location.hash.slice(1));
const denied = new URLSearchParams(location.search).get('error');
history.replaceState(null, '', '/callback');
const status = document.getElementById('estado');
if (denied || fields.get('error')) {
  status.textContent = 'Autorización cancelada. Puedes cerrar esta pestaña y la consola.';
} else if (!fields.get('access_token')) {
  status.textContent = 'No se recibió autorización. Ejecuta python autorizar.py.';
} else {
  fetch('/guardar', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:fields.get('access_token'), state:fields.get('state')})})
  .then(async r => {status.textContent = await r.text();})
  .catch(() => {status.textContent = 'No se pudo contactar con el programa local.';});
}
</script></html>''', "text/html; charset=utf-8")

        def do_POST(self):
            if (self.path != "/guardar" or self.headers.get("Host") != "localhost:8765"
                    or self.headers.get("Origin") != ORIGIN):
                self.reply(403, "Solicitud rechazada.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError()
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload.get("state"), str) or not hmac.compare_digest(payload["state"], state):
                    self.reply(403, "La autorización no coincide. Vuelve a iniciarla desde el programa.")
                    return
                token = payload.get("token")
                if not isinstance(token, str) or not token.isalnum():
                    raise ValueError()
                data = validate_token({"TWITCH_CLIENT_ID": creds["TWITCH_CLIENT_ID"], "TWITCH_TOKEN": token})
                # Solo persistir una autorización válida, no el identificador ni secretos ajenos.
                with save_lock:
                    if done.is_set():
                        self.reply(409, "La conexión ya se completó.")
                        return
                    env = ROOT / "config/.env"
                    set_key(str(env), "TWITCH_TOKEN", "oauth:" + token)
                    set_key(str(env), "TWITCH_BOT_LOGIN", data["login"])
                    if not creds.get("TWITCH_CHANNEL"):
                        set_key(str(env), "TWITCH_CHANNEL", data["login"])
                    outcome["login"] = data["login"]
                    done.set()
                self.reply(200, "Twitch conectado. El token se guardó en tu PC. Puedes cerrar esta pestaña.")
            except Exception:
                self.reply(400, "No se pudo guardar la conexión. Revisa internet y el Client ID e inténtalo de nuevo.")

    save_lock = threading.Lock()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    except OSError as exc:
        raise ServiceError("El puerto local 8765 está ocupado. Cierra otra conexión de Twitch y reintenta.") from exc
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "https://id.twitch.tv/oauth2/authorize?" + urlencode({
        "client_id": creds["TWITCH_CLIENT_ID"], "redirect_uri": REDIRECT,
        "response_type": "token", "scope": "chat:read chat:edit", "state": state, "force_verify": "true"})
    try:
        print("Autoriza en Twitch la lectura y escritura del chat. No necesitas copiar ningún token.")
        print("La URL registrada en la consola de Twitch debe ser exactamente: " + REDIRECT)
        if open_browser:
            webbrowser.open(url)
        print("Si no se abrió el navegador, abre esta dirección oficial:\n" + url)
        deadline = time.monotonic() + wait_seconds
        while not done.wait(0.25):
            if cancel_event is not None and cancel_event.is_set():
                raise ServiceError("Autorización cancelada.")
            if time.monotonic() >= deadline:
                raise ServiceError("Se agotó el tiempo para conectar Twitch. Ejecuta otra vez python autorizar.py.")
        print("Twitch conectado como " + outcome["login"] + ". Token guardado localmente, sin mostrarlo.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


async def hourly_validation(creds):
    import asyncio
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(validate_token, creds)
        except httpx.TransportError:
            # Una caída transitoria de red no equivale a revocación; reintentar pronto.
            await asyncio.sleep(30)
            await asyncio.to_thread(validate_token, creds)


if __name__ == '__main__':
    source = dotenv_values(ROOT / 'config' / '.env', encoding='utf-8-sig')
    try:
        authorize(source)
    except Exception as exc:
        print('No se pudo autorizar Twitch:', str(exc) if isinstance(exc, (ValueError, ServiceError)) else type(exc).__name__)



