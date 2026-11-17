import asyncio
import io
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import httpx
import numpy as np
import sounddevice as sd
import soundfile as sf
from dotenv import dotenv_values
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent

VOICES = json.loads((ROOT / 'config' / 'voces.json').read_text(encoding='utf-8-sig'))['voces']
BY_NAME = {v['comando']: v for v in VOICES}
ALIASES = {'hu tao': 'hutao', 'scaramouche': 'scara', 'neuve': 'neuvillette', 'hatsune miku': 'miku', 'kasane teto': 'teto', 'miku nakano': 'mikunakano', 'nino nakano': 'nino'}
STATE = ROOT / 'datos' / 'preferencias.json'
BOTS_FILE = ROOT / 'config' / 'bots.txt'
MAX_FRAGMENT = 140
_volume = 1.0
_stop_audio = threading.Event()


def set_volume(percent):
    global _volume
    _volume = max(0.0, min(1.0, float(percent) / 100.0))


def stop_audio():
    _stop_audio.set()


def normalize(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s.lower().strip()) if not unicodedata.combining(c))


def select_voice(name):
    name = normalize(name)
    if name in ('wanderer', 'trotamundos'):
        name = 'scara'
    if name == 'yummi':
        name = 'yuumi'
    if name in ('dr house', 'dr. house'):
        name = 'house'
    direct = BY_NAME.get(ALIASES.get(name, name))
    return direct or next((v for v in VOICES if normalize(v['nombre']) == name), None)


def read_preferences():
    try:
        data = json.loads(STATE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_preferences(data):
    STATE.parent.mkdir(exist_ok=True)
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(STATE)


def load_credentials():
    return {key: (value or '').strip() for key, value in dotenv_values(ROOT / 'config' / '.env', encoding='utf-8-sig').items()}


def load_bots():
    try:
        return {line.strip().lower().lstrip('@') for line in BOTS_FILE.read_text(encoding='utf-8-sig').splitlines() if line.strip() and not line.lstrip().startswith('#')}
    except OSError:
        return set()


def is_bot(user, line, bots):
    user = user.lower()
    tags = line.split(' ', 1)[0] if line.startswith('@') else ''
    badges = next((x[7:] for x in tags.lstrip('@').split(';') if x.startswith('badges=')), '')
    return user in bots or user.endswith('bot') or any(b.split('/')[0] == 'bot' for b in badges.split(','))


def is_shared_chat_copy(line):
    if not line.startswith('@'):
        return False
    tags = dict(tag.split('=', 1) for tag in line[1:].split(' ', 1)[0].split(';') if '=' in tag)
    source_room = tags.get('source-room-id')
    return bool(source_room and source_room != tags.get('room-id'))


def parse_message(line):
    match = re.match(r'^(?:@[^ ]+ )?:([a-zA-Z0-9_]+)![^ ]+ PRIVMSG #([a-zA-Z0-9_]+) :(.*)$', line)
    return match.groups() if match else None


def remove_twitch_emotes(line, message):
    if not line.startswith('@'):
        return message
    tags = line.split(' ', 1)[0][1:]
    emotes = next((tag.partition('=')[2] for tag in tags.split(';') if tag.startswith('emotes=')), '')
    ranges = []
    for emote in emotes.split('/'):
        _, sep, positions = emote.partition(':')
        if not sep:
            continue
        for position in positions.split(','):
            match = re.fullmatch(r'(\d+)-(\d+)', position)
            if match:
                start, end = map(int, match.groups())
                if 0 <= start <= end < len(message):
                    ranges.append((start, end + 1))
    for start, end in sorted(set(ranges), reverse=True):
        message = message[:start] + ' ' + message[end:]
    return ' '.join(message.split())


def clean_spoken_message(message):
    message = re.sub(r'<\|[^>]*\|>|\[[^\]]*\]', ' ', message)
    # Quitar emojis, modificadores de piel, banderas, uniones y selectores.
    message = re.sub(r'[0-9#*]\ufe0f?\u20e3', ' ', message)
    message = ''.join(' ' if (
        unicodedata.category(c) in ('So', 'Sk', 'Cs')
        or c in '\ufe0f\ufe0e\u200d\u20e3'
        or 0xE0020 <= ord(c) <= 0xE007F
    ) else c for c in message)

    def laughter(word):
        if re.fullmatch(r'[ㅋㅎ]{2,}', word):
            return ' '
        folded = normalize(word)
        if re.fullmatch(r'(?:x+d+|d+x+|lol+|lo+l|lmao+|lmfao+|rofl+|roflmao+|lul+|kekw+|omegalul+|lawl+)', folded):
            return ' '
        if re.fullmatch(r'(?:([ghjkw][aeiou])\1+)', folded):
            return ' '
        if re.fullmatch(r'(?:ks|sk|kj|jk|js|sj){2,}[ajskdlñ]*', folded):
            return ' '
        if re.fullmatch(r'(?:k{3,}|w{3,}|笑+|草+|[ㅋㅎ]{2,}|[哈呵嘿嘻]{2,})', folded):
            return ' '
        # Risas y golpes de teclado mezclados; no elimina palabras que solo
        # contienen "ja", como trabajar, caja o naranja.
        if re.fullmatch(r'(?:ja|je|ji|jo|ju|ha|he|hi|ho|hu){2,}', folded):
            return ' '
        if len(folded) >= 5 and re.fullmatch(r'[ajskdlñ]+', folded):
            if folded.count('j') >= 2 or re.search(r'(?:as[dflk]|[sd]jk)', folded):
                return ' '
        return word

    # 555/55555 es risa en tailandés. Solo secuencias completas de cincos.
    message = re.sub(r'(?<!\w)5{3,}(?!\w)', ' ', message)
    # Variantes con números intercalados: j4j4j4, jajaja123, xD123.
    def mixed_laughter(match):
        token = match.group()
        letters = re.sub(r'\d', '', token)
        leet = token.lower().translate(str.maketrans({'4': 'a', '3': 'e', '1': 'i', '0': 'o'}))
        if re.fullmatch(r'([jh][aeiou])\1+(?:[jh]|[sdkl]{1,4})?\d*', leet):
            return 'jajaja'
        if re.match(r'^(?:ja|je|ji|jo|ju)', normalize(token)) and laughter(letters) == ' ':
            return 'jajaja'
        if letters and laughter(letters) == ' ':
            return ' '
        return token

    message = re.sub(r'\w+', mixed_laughter, message, flags=re.UNICODE)
    # Convertir alargamientos de chat en pronunciaciones normales.
    message = re.sub(r'([aeiouáéíóúü])\1{2,}', r'\1', message, flags=re.IGNORECASE)
    message = re.sub(r'([!?.,])\1+', r'\1', message)
    return ' '.join(message.split())


def voice_lines():
    groups = {}
    for voice in VOICES:
        groups.setdefault(voice['serie'], []).append(voice['nombre'])
    categories = [series + ': ' + ', '.join(names) for series, names in groups.items()]
    return ['🎙 ' + ' │ '.join(categories) + ' → !voz nombre']


def split_for_speech(text, limit=MAX_FRAGMENT):
    """Keep whole words where possible, preferring sentence boundaries."""
    text = ' '.join(text.split())
    fragments = []
    while len(text) > limit:
        window = text[:limit + 1]
        sentence_breaks = [m.end() for m in re.finditer(r'[.!?…;:](?=\s)', window)]
        split = sentence_breaks[-1] if sentence_breaks and sentence_breaks[-1] >= limit // 3 else window.rfind(' ', 0, limit + 1)
        if split <= 0:
            split = limit
        fragments.append(text[:split].strip())
        text = text[split:].strip()
    if text:
        fragments.append(text)
    return fragments


def adjust_voice_volume(audio, voice):
    if not len(audio):
        return audio
    if not np.isfinite(audio).all():
        raise ValueError('Audio inválido')
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    if peak < 0.0001 or rms < 0.0001:
        return audio
    # Nivel común medido, sin amplificar silencios ni recortar los picos.
    gain = min(4.0, 10 ** (-18 / 20) / rms, 0.95 / peak)
    return audio * gain


def fish_request(text, voice):
    # Usar el estilo del modelo de referencia y los valores normales de Fish.
    return {'text': text, 'reference_id': voice['id'], 'format': 'wav', 'sample_rate': 44100,
            'language': 'es'}


async def synthesize_fragment(client, creds, fragment, voice):
    for attempt in range(2):
        try:
            response = await client.post('https://api.fish.audio/v1/tts',
                headers={'Authorization': 'Bearer ' + creds['FISH_API_KEY'], 'model': 's2.1-pro-free'},
                json=fish_request(fragment, voice))
            if response.status_code != 200:
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                    print(f"Fish respondió HTTP {response.status_code}; se reintenta este fragmento.", flush=True)
                    await asyncio.sleep(2)
                    continue
                raise ValueError(f'Fish HTTP {response.status_code}')
            audio, rate = sf.read(io.BytesIO(response.content), dtype='float32')
            if not len(audio) or not np.isfinite(audio).all() or np.max(np.abs(audio)) < 0.0001:
                raise ValueError('Fish devolvió audio vacío o silencioso')
            return adjust_voice_volume(audio, voice), rate
        except (httpx.TransportError, ValueError, RuntimeError, OSError) as exc:
            # Los fallos permanentes de HTTP no se reintentan.
            if isinstance(exc, ValueError) and str(exc).startswith('Fish HTTP '):
                raise
            if attempt == 0:
                print('Fish no entregó audio válido a tiempo; se reintenta este fragmento.', flush=True)
                await asyncio.sleep(2)
                continue
            raise ValueError('Fish no entregó audio válido después del reintento') from exc


async def worker(queue, creds):
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        while True:
            text, voice = await queue.get()
            pending = None
            try:
                fragments = split_for_speech(text)
                if fragments:
                    pending = asyncio.create_task(synthesize_fragment(client, creds, fragments[0], voice))
                for index in range(len(fragments)):
                    audio, rate = await pending
                    pending = None
                    if index + 1 < len(fragments):
                        pending = asyncio.create_task(synthesize_fragment(client, creds, fragments[index + 1], voice))
                    await asyncio.to_thread(play_audio, audio, rate)
            except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
                detail = str(exc) if isinstance(exc, ValueError) else 'error de reproducción o conexión'
                print(f"No se completó el mensaje con {voice['nombre']}: {detail}. Continúa el siguiente mensaje.", flush=True)
            finally:
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                queue.task_done()


def play_audio(audio, rate):
    _stop_audio.clear()
    underruns = 0
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    # Escritura bloqueante desde el hilo de reproducción: PortAudio mantiene
    # el búfer nativo sin callbacks de Python sujetos al GIL durante el audio.
    block_size = 2048
    with sd.OutputStream(samplerate=rate, channels=channels, dtype='float32',
                         blocksize=block_size, latency=0.2) as stream:
        for position in range(0, len(audio), block_size):
            if _stop_audio.is_set():
                stream.abort()
                break
            chunk = audio[position:position + block_size]
            if chunk.ndim == 1:
                chunk = chunk.reshape(-1, 1)
            block = np.ascontiguousarray(chunk * _volume, dtype=np.float32)
            if stream.write(block):
                underruns += 1
    if underruns:
        print(f'Audio: {underruns} cortes de búfer en la salida de Windows. El archivo de Fish puede estar correcto; revisa carga y procesamiento de audio.', flush=True)


async def listen(creds, queue):
    channel = creds['TWITCH_CHANNEL'].lstrip('#').lower()
    login = creds['TWITCH_BOT_LOGIN'].lower()
    token = creds['TWITCH_TOKEN'].removeprefix('oauth:')
    if not re.fullmatch(r'[a-z0-9_]+', channel) or not re.fullmatch(r'[a-z0-9_]+', login) or not token.isalnum():
        raise ValueError('Credenciales de Twitch inválidas; revisa la autorización.')
    prefs = read_preferences()
    bots = load_bots()
    cooldown = {}
    delay = 2
    while True:
        try:
            async with connect('wss://irc-ws.chat.twitch.tv:443', open_timeout=15, ping_interval=20) as ws:
                await ws.send('PASS oauth:' + token)
                await ws.send('NICK ' + login)
                await ws.send('CAP REQ :twitch.tv/tags twitch.tv/commands')
                async for frame in ws:
                    for line in str(frame).split('\r\n'):
                        if line.startswith('PING '):
                            await ws.send('PONG ' + line[5:])
                            continue
                        if ' 001 ' in line:
                            await ws.send('JOIN #' + channel)
                            print('Conectado al chat de #' + channel + '. Hatsune Miku es la voz inicial.', flush=True)
                            delay = 2
                            continue
                        if ' NOTICE ' in line and ('authentication failed' in line.lower() or 'improperly formatted auth' in line.lower()):
                            raise ValueError('Twitch rechazó la autorización. Vuelve a autorizar.')
                        if ' NOTICE ' in line:
                            print('Aviso de Twitch: ' + line.rsplit(' :', 1)[-1][:250], flush=True)
                            continue
                        if ' RECONNECT' in line:
                            raise ConnectionError()
                        parsed = parse_message(line)
                        if not parsed:
                            continue
                        user, target, message = parsed
                        user = user.lower()
                        if target.lower() != channel or is_shared_chat_copy(line):
                            continue
                        message = message.strip()
                        command, _, argument = message.partition(' ')
                        command = command.lower()
                        own_command = user == login and command in ('!voces', '!voz')
                        if not own_command and (user == login or is_bot(user, line, bots)):
                            continue
                        now = time.monotonic()
                        if command == '!voces':
                            if now - cooldown.get(('list', 'global'), -60) >= 30:
                                cooldown[('list', 'global')] = now
                                for item in voice_lines():
                                    await ws.send(f'PRIVMSG #{channel} :\x01ACTION {item}\x01')
                                print(f'{user} solicitó la lista de voces.', flush=True)
                            else:
                                print(f'{user}: espera 30 segundos entre solicitudes de !voces.', flush=True)
                            continue
                        if command == '!voz':
                            if now - cooldown.get(('voice', user), -60) < 5:
                                continue
                            cooldown[('voice', user)] = now
                            voice = select_voice(argument)
                            if voice:
                                prefs[user] = voice['comando']
                                save_preferences(prefs)
                                print(f"{user} eligió {voice['nombre']}.", flush=True)
                                await ws.send(f"PRIVMSG #{channel} :\x01ACTION 🎙 @{user} cambió su voz a {voice['nombre']} ({voice['serie']}). ¡Elección guardada!\x01")
                            else:
                                print(f"{user}: voz desconocida; consulta !voces.", flush=True)
                                await ws.send(f'PRIVMSG #{channel} :@{user}, no encontré esa voz. Escribe !voces para ver la lista.')
                            continue
                        if not message or message.startswith(('!', '/', '.')):
                            continue
                        message = remove_twitch_emotes(line, parsed[2])
                        message = clean_spoken_message(message)
                        message = re.sub(r'https?://\S+', '', message).strip()[:500]
                        if not message:
                            continue
                        voice = BY_NAME.get(prefs.get(user), BY_NAME['miku'])
                        try:
                            queue.put_nowait((f'{user} dice: {message}', voice))
                        except asyncio.QueueFull:
                            print('Cola llena: se omitió un mensaje.', flush=True)
        except ValueError:
            raise
        except Exception as exc:
            print(f'Twitch desconectado ({type(exc).__name__}); reintentando en {delay} segundos.', flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


async def main():
    creds = load_credentials()
    missing = [x for x in ('TWITCH_CLIENT_ID', 'TWITCH_CHANNEL', 'TWITCH_BOT_LOGIN', 'TWITCH_TOKEN', 'FISH_API_KEY') if not creds.get(x)]
    if missing:
        raise ValueError('Falta configuración: ' + ', '.join(missing))
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        r = await client.get('https://id.twitch.tv/oauth2/validate', headers={'Authorization': 'OAuth ' + creds['TWITCH_TOKEN'].removeprefix('oauth:')})
    if r.status_code != 200:
        raise ValueError('Autorización de Twitch vencida. Ejecuta python autorizar.py.')
    token_info = r.json()
    if token_info.get('client_id') != creds['TWITCH_CLIENT_ID'] or token_info.get('login', '').lower() != creds['TWITCH_BOT_LOGIN'].lower() or not {'chat:read', 'chat:edit'}.issubset(set(token_info.get('scopes', []))):
        raise ValueError('Se necesita autorización propia de Twitch con lectura y escritura. Ejecuta python autorizar.py.')
    queue = asyncio.Queue(maxsize=20)
    task = asyncio.create_task(worker(queue, creds))
    try:
        await listen(creds, queue)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nLector detenido.')
    except (ValueError, OSError, httpx.HTTPError) as exc:
        print('No se pudo iniciar:', str(exc) if isinstance(exc, ValueError) else type(exc).__name__)



