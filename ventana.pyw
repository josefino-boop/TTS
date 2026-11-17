import asyncio
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

import sounddevice as sd
import lector


class LogStream:
    def __init__(self, target):
        self.target = target
        self.buffer = ''
    def write(self, value):
        self.buffer += str(value)
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip():
                self.target.put(('log', line))
        return len(value)
    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.messages = queue.Queue()
        self.thread = None
        self.loop = None
        self.task = None
        self.closing = False
        sys.stdout = LogStream(self.messages)
        sys.stderr = LogStream(self.messages)
        root.title('TTS Chat - Twitch')
        root.geometry('540x465')
        root.minsize(460, 320)
        frame = ttk.Frame(root, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='TTS del chat', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Twitch · Fish Audio gratuito · Voz inicial: Hatsune Miku').pack(anchor='w', pady=(0, 12))
        self.state = tk.StringVar(value='Desconectado')
        ttk.Label(frame, textvariable=self.state, font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=12)
        self.start_btn = ttk.Button(buttons, text='Conectar lector', command=self.start)
        self.start_btn.pack(side='left', padx=(0, 8))
        self.stop_btn = ttk.Button(buttons, text='Detener', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left')
        volume_row = ttk.Frame(frame)
        volume_row.pack(fill='x', pady=(0, 10))
        ttk.Label(volume_row, text='Volumen').pack(side='left', padx=(0, 8))
        self.volume_text = tk.StringVar(value='100 %')
        self.volume_scale = ttk.Scale(volume_row, from_=0, to=100, command=self.change_volume)
        self.volume_scale.set(100)
        self.volume_scale.pack(side='left', fill='x', expand=True)
        ttk.Label(volume_row, textvariable=self.volume_text, width=6, anchor='e').pack(side='left')
        ttk.Label(frame, text='Actividad').pack(anchor='w')
        self.log = tk.Text(frame, height=9, wrap='word', state='disabled', font=('Segoe UI', 9))
        self.log.pack(fill='both', expand=True, pady=(4, 8))
        ttk.Label(frame, text='En OBS: captura el audio de esta ventana.').pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def change_volume(self, value):
        percent = round(float(value))
        lector.set_volume(percent)
        self.volume_text.set(f'{percent} %')

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.state.set('Conectando…')
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        self.task = loop.create_task(lector.main())
        try:
            loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            msg = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            self.messages.put(('log', 'No se pudo iniciar: ' + msg))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self.loop = None
            self.task = None
            self.messages.put(('stopped', ''))

    def stop(self):
        self.state.set('Deteniendo…')
        self.stop_btn.config(state='disabled')
        try:
            lector.stop_audio()
        except Exception:
            pass
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)

    def poll(self):
        try:
            while True:
                kind, text = self.messages.get_nowait()
                if kind == 'log':
                    self.log.config(state='normal')
                    self.log.insert('end', text + '\n')
                    self.log.see('end')
                    self.log.config(state='disabled')
                    if text.startswith('Conectado al chat'):
                        self.state.set('Conectado')
                    elif text.startswith('Twitch desconectado'):
                        self.state.set('Reconectando…')
                elif kind == 'stopped':
                    self.state.set('Desconectado')
                    self.start_btn.config(state='normal')
                    self.stop_btn.config(state='disabled')
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.thread and self.thread.is_alive():
            self.closing = True
            self.stop()
        else:
            self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()

