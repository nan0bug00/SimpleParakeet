# SimpleParakeet

A simple, local OpenAI Whisper-compatible speech-to-text service for
SkyrimNet, powered by NVIDIA Parakeet models through Sherpa ONNX on CPU.

| Port | Role |
|---|---|
| **8210** | Whisper API (point SkyrimNet here) |

## Model choice

First-run setup asks which model to use **before downloading either model**.
Only the selected, SHA-256-verified archive is downloaded.

| Choice | Best for | Local Skyrim-fixture HTTP result* |
|---|---|---:|
| **English — Fast (110M), recommended** | Most English-speaking users | 107.7 ms p95, 114.7 ms max |
| **Multilingual (0.6B), slower** | Supported non-English speech | 338.9 ms p95, 362.8 ms max |

\* Measurements were taken on the remediation reference machine and are not a
universal hardware guarantee. The multilingual model is substantially slower;
choose it when multilingual recognition matters more than response time.

The selected model is loaded once and reused for every utterance. CPU thread
count is configured with `onnx_threads` in `config.json`.

## Quick start — Windows

1. Unzip `SimpleParakeet-windows-x64.zip`.
2. Double-click **`RUN-ME.bat`**.
3. Choose the 110M English or 0.6B multilingual model, then confirm the host
   and port. The model download begins only after this choice.
4. Configure SkyrimNet with:
   - endpoint: `http://127.0.0.1:8210/v1/audio/transcriptions`
   - model: `whisper-1`
   - API key: any non-empty value
5. Leave the window open while playing. Press Enter to stop.

Run `pwsh -File launch.ps1 -Setup` to change setup choices later.

## Quick start — Linux

For SkyrimNet under Proton/Wine, run SimpleParakeet natively on Linux and point
the game at `127.0.0.1`; do not install the Windows archive inside the Wine
prefix.

1. Unzip `SimpleParakeet-linux-x64.zip`.
2. Double-click **`RUN-ME.sh`**, or run
   `chmod +x RUN-ME.sh && ./RUN-ME.sh` in a terminal.
3. Choose the model before download and confirm the host and port.
4. Use the same SkyrimNet endpoint, model, and API-key values shown above.
5. Leave the terminal open. Press Enter to stop.

Run `./launch.sh --setup` to change setup choices later. Localhost traffic does
not require UFW/firewalld changes for Proton-to-host communication.

## Transcription behavior

The client owns microphone capture, push-to-talk, and open-mic/VAD behavior.
Submit each finalized utterance to the standard Whisper endpoint.
SimpleParakeet performs one offline decode per upload; it does not repeatedly
decode a growing audio buffer or return partial transcripts.

The HTTP endpoints and SkyrimNet-compatible response schema remain unchanged.

## Skyrim lexicon

`lexicon.json` contains canonical Skyrim names, locations, factions, and terms.
The correction layer receives only raw transcript text; it never receives or
branches on the ASR model identity.

At startup, the program derives compact word-boundary and pronunciation forms
from every canonical entry. Users normally add only canonical terms:

```json
{
  "entries": [
    "Whiterun",
    {"canonical": "Paarthurnax", "category": "character"},
    {"canonical": "Greybeards", "category": "faction"}
  ]
}
```

Only canonical spellings are supported. The program derives recognition forms
from those entries automatically; users do not maintain lists of ASR mistakes.
Categories are optional organizational metadata; uncategorized terms are fully
supported.

Correction is surgical: only an accepted entity span changes, canonical
spelling is emitted, and all other bytes and punctuation remain untouched.
Exact split/join forms are treated as canonical matches, so `White Run` always
becomes `Whiterun` in this Skyrim-focused service.

## Licenses

See `LICENSE` and `licenses/` for SimpleParakeet, Sherpa ONNX, FFmpeg, and
Parakeet model licensing information.
