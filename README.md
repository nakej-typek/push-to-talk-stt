# push-to-talk-stt

Hold-to-talk dictation that works in **every** window on Windows. Press `F8`, say
what you want, press `F8` again — the transcript is pasted straight into whatever has
focus. Terminal, IDE, browser, chat box, it does not care.

It runs in the background all day. I use it to write most of my prompts.

```
F8        start recording
F8        stop -> transcribe -> paste at the cursor
Ctrl+F8   throw the recording away
```

Single file, ~320 lines. Transcription is a Gemini call on the free tier.

---

## The details that make it usable

Most of the code is not "record audio and call an API" — that part is twenty lines.
The rest is what makes a global hotkey tool tolerable to actually live with:

**A global hotkey swallows the key everywhere.** `RegisterHotKey` is system-wide, so
cancel is `Ctrl+F8` rather than a bare `Esc`. It was `Esc` at first, which meant every
Escape anywhere on the machine — closing a dialog, leaving insert mode — silently
threw away a recording in progress. Modifiers are matched exactly, so plain `F8` and
`Ctrl+F8` coexist.

**Pasting has to leave the clipboard as it found it.** The transcript goes in via the
clipboard and `Ctrl+V`, so the previous clipboard contents are saved and restored
around the paste. Losing whatever you had copied every time you dictate is not an
acceptable trade.

**A forgotten microphone is a real failure mode.** A watchdog stops recording after
`MAX_SECONDS` so a mis-press cannot leave the mic live indefinitely and then send a
very long, very expensive recording.

**Free tiers fail intermittently.** `transcribe()` retries on 429/500/503 only — twice
on the primary model, then once on a fallback model — and re-raises anything else
immediately rather than burning retries on a real error.

**Short and empty recordings never reach the API.** Under 0.4 s is dropped locally,
and the prompt instructs the model to return an empty string when there is no speech,
which is then not pasted. A stray keypress costs nothing.

**The prompt is doing real work.** The speaker is Czech and mixes in English technical
terms, so the prompt pins that down explicitly: keep English words in English, do not
translate or transliterate them, and it lists the proper nouns that would otherwise
get mangled. Temperature 0. Verbatim output only — no preamble, no markdown, no
quotes — because the result is pasted directly, and any "Sure, here is the
transcript:" would land in the middle of your sentence.

---

## Running it

```bash
pip install numpy sounddevice pyperclip pyautogui pywin32 google-genai
export GEMINI_API_KEY=...        # or put the key in a .api_key file next to the script
python voice.py
```

To start it hidden at login, point Task Scheduler at `voice_hidden.vbs`, which runs
the script with no console window and appends stdout and stderr to `voice.log`.

Windows only — `RegisterHotKey` and the foreground-window paste are Win32 APIs.

---

## Notes

- Inline comments are in Czech; this was a personal tool first.
- Built with AI pair-programming (Claude Code).
