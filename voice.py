"""
Claudoslav Voice — press-to-talk STT přes Gemini API.

F8      = start nahrávání / stop + přepis + paste do aktivního okna
Ctrl+F8 = zahodit nahrávku bez přepisu
Běží pořád na pozadí, funguje v jakémkoliv terminálu/okně.

API klíč: proměnná prostředí GEMINI_API_KEY (nebo soubor .api_key vedle scriptu).
"""

import io
import os
import sys
import time
import wave
import threading

import numpy as np
import sounddevice as sd
import win32con
import win32gui
import pyperclip
import pyautogui
from google import genai
from google.genai import types

# ── Config ──────────────────────────────────────────────────────────────
HOTKEY_ID_TOGGLE = 1
HOTKEY_ID_CANCEL = 2
MODEL = "gemini-3.1-flash-lite"
FALLBACK_MODEL = "gemini-3-flash-preview"  # když je hlavní model přetížený
SAMPLE_RATE = 16000
MAX_SECONDS = 300  # pojistka proti zapomenutému běžícímu mikrofonu

PROMPT = """Přepiš tuto nahrávku doslovně.

Mluvčí je Čech a míchá češtinu s anglickými technickými výrazy — anglická
slova nech anglicky, nepřekládej je a nepřepisuj foneticky.
Časté názvy: Claude, Claude Code, Claudoslav, Gemini, Python, commit, prompt.

Vrať POUZE přepsaný text — žádný úvod, komentář, uvozovky ani markdown.
Když v nahrávce není žádná řeč, vrať prázdný řetězec."""
# ────────────────────────────────────────────────────────────────────────


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


_print = print


def print(*args, **kwargs):
    """Timestamped + flushed — jinak se do logu nic nedostane až do konce."""
    _print(time.strftime("[%Y-%m-%d %H:%M:%S]"), *args, **kwargs)
    sys.stdout.flush()


def load_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key.strip()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".api_key")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    print("Chybí GEMINI_API_KEY (env proměnná nebo soubor .api_key).")
    sys.exit(1)


client = genai.Client(api_key=load_api_key())

recording = False
audio_chunks: list[np.ndarray] = []
cancelled = False
_lock = threading.Lock()
_last_toggle = 0.0


def to_wav(audio: np.ndarray) -> bytes:
    """float32 [-1,1] -> 16bit PCM WAV v paměti."""
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _call(model: str, wav_bytes: bytes) -> str:
    resp = client.models.generate_content(
        model=model,
        contents=[
            PROMPT,
            types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    return (resp.text or "").strip()


def transcribe(wav_bytes: bytes) -> str:
    """Přepis s retry — free tier občas vrací 503/429."""
    for model in (MODEL, MODEL, FALLBACK_MODEL):
        try:
            return _call(model, wav_bytes)
        except Exception as e:
            code = getattr(e, "code", None)
            if code not in (429, 500, 503):
                raise
            last = e
            time.sleep(1.5)
    raise last


def paste(text: str):
    """Vloží text do aktivního okna a vrátí původní clipboard."""
    try:
        old = pyperclip.paste()
    except Exception:
        old = ""
    pyperclip.copy(text)
    time.sleep(0.05)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    try:
        pyperclip.copy(old)
    except Exception:
        pass


def audio_callback(indata, frames, time_info, status):
    if recording:
        audio_chunks.append(indata.copy())


def worker():
    """Po stopnutí: složí audio, pošle do Gemini, pastne výsledek."""
    if cancelled:
        print("[ZRUŠENO]")
        return
    if not audio_chunks:
        print("[PRÁZDNÉ] nic se nenahrálo")
        return

    audio = np.concatenate(audio_chunks, axis=0).flatten().astype(np.float32)
    secs = len(audio) / SAMPLE_RATE
    if secs < 0.4:
        print("[KRÁTKÉ] přeskočeno")
        return

    print(f"[PŘEPIS] {secs:.1f}s -> Gemini…")
    t0 = time.time()
    try:
        text = transcribe(to_wav(audio))
    except Exception as e:
        print(f"[CHYBA] {e}")
        return

    if not text:
        print("[TICHO] žádná řeč")
        return
    paste(text + " ")
    print(f"[OK {time.time() - t0:.1f}s] {text}")


def auto_stop_guard():
    """Pojistka: po MAX_SECONDS nahrávání samo skončí."""
    started = time.time()
    while recording:
        if time.time() - started > MAX_SECONDS:
            print(f"[LIMIT] {MAX_SECONDS}s — stopuju")
            on_toggle()
            return
        time.sleep(0.5)


def on_toggle():
    global recording, audio_chunks, cancelled, _last_toggle
    now = time.time()
    if now - _last_toggle < 0.4:
        return
    _last_toggle = now
    with _lock:
        if not recording:
            audio_chunks = []
            cancelled = False
            recording = True
            threading.Thread(target=paste, args=("speaking: ",), daemon=True).start()
            print("[REC] mluv… (F8 = konec, Ctrl+F8 = zrušit)")
            threading.Thread(target=auto_stop_guard, daemon=True).start()
        else:
            recording = False
            threading.Thread(target=worker, daemon=True).start()


def on_cancel():
    global recording, cancelled
    if recording:
        cancelled = True
        recording = False
        print("[ZRUŠENO] nahrávka zahozena")


stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        callback=audio_callback)
stream.start()

# RegisterHotKey místo knihovny `keyboard` — ta stavěla na SetWindowsHookEx
# (WH_KEYBOARD_LL), který Windows tiše a natrvalo odregistruje, pokud callback
# na chvíli zpomalí (LowLevelHooksTimeout, default 300ms). RegisterHotKey
# posílá WM_HOTKEY do fronty zpráv vlákna a tenhle problém nemá — proces tedy
# už nepotřebuje periodický self-restart, který dřív způsoboval ~1min výpadky
# každých 15 minut (viz git historie / memory před 2026-07-26).
# Cancel je Ctrl+F8, ne holý ESC — RegisterHotKey klávesu polyká globálně, takže
# ESC nedorazil do ostatních oken a každý Escape mimo (terminál, IDE, dialog)
# omylem zahodil rozdělanou nahrávku. Modifikátory se matchují přesně, takže
# holý F8 a Ctrl+F8 vedle sebe nekolidují.
win32gui.RegisterHotKey(None, HOTKEY_ID_TOGGLE, win32con.MOD_NOREPEAT, win32con.VK_F8)
win32gui.RegisterHotKey(None, HOTKEY_ID_CANCEL,
                        win32con.MOD_CONTROL | win32con.MOD_NOREPEAT, win32con.VK_F8)

print("Claudoslav Voice (%s) běží. [F8] = mluv, [Ctrl+F8] = zahodit.\n" % MODEL)

try:
    while True:
        ret, msg = win32gui.GetMessage(None, 0, 0)
        if ret == 0:
            break
        _, message, wparam, _, _, _ = msg
        if message == win32con.WM_HOTKEY:
            if wparam == HOTKEY_ID_TOGGLE:
                on_toggle()
            elif wparam == HOTKEY_ID_CANCEL:
                on_cancel()
except KeyboardInterrupt:
    pass
finally:
    win32gui.UnregisterHotKey(None, HOTKEY_ID_TOGGLE)
    win32gui.UnregisterHotKey(None, HOTKEY_ID_CANCEL)
stream.stop()
stream.close()
print("\nBye!")
