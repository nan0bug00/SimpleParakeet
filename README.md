# SimpleParakeet

A Simple, Local, Fast OpenAI Whisper-compatible speech-to-text inference solution for SkyrimNet,
using NVIDIA Parakeet TDT 0.6B v3 through Sherpa ONNX on CPU.

| Port | Role |
|------|------|
| **8210** | Whisper API (SkyrimNet points here) |

## Quick start (Windows)

1. Unzip `SimpleParakeet-windows-x64.zip`.
2. Double-click **`RUN-ME.bat`**.
3. On first launch, confirm or change ports.
4. When ready, paste the printed endpoint into SkyrimNet, for example:  
   `http://127.0.0.1:8210/v1/audio/transcriptions`
   - **Model:** `whisper-1`
   - **API key:** any non-empty value
5. Leave the window open while playing. Press Enter in that window to stop.

Change ports later: `pwsh -File launch.ps1 -Setup`

## Quick start (Linux)

Intended for host-native use with SkyrimNet under Proton/Wine: run SimpleParakeet on Linux, point the game at `127.0.0.1` — **do not** install the Windows zip into your Wine prefix.

1. Unzip `SimpleParakeet-linux-x64.zip`.
2. Double-click **`RUN-ME.sh`** (opens a terminal). Or from a terminal: `chmod +x RUN-ME.sh && ./RUN-ME.sh`
3. On first launch, confirm or change ports (keep **`127.0.0.1`** unless you know you need otherwise).
4. Paste the printed endpoint into SkyrimNet External Whisper (same model/key as above).
5. Leave the terminal open. Press Enter to stop.

Change ports later: `./launch.sh --setup`

Localhost (`127.0.0.1`) does not require UFW/firewalld changes for Proton→host traffic.

On first Windows launch, the pinned `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8`
model is downloaded from the official Sherpa ONNX release, verified against its
SHA-256 checksum, then installed atomically. It is a multilingual INT8 ONNX
model, loaded once at startup and reused for every submitted utterance.
Configure its CPU thread count with `onnx_threads` in `config.json`; the
default uses half of logical cores, capped at four.

The client continues to own microphone capture. Both client-side PTT and
client-side open-mic/VAD work without API changes: submit each finalized
utterance to the standard Whisper endpoint. SimpleParakeet performs one
offline decode per upload; it intentionally does not repeatedly decode a
growing audio buffer and does not provide partial transcripts.

## Skyrim lexicon

Copy `lexicon.example.json` to `lexicon.json` to enable optional, conservative
Skyrim name correction. Terms and aliases are case-insensitive when matched,
while their configured canonical spelling is emitted. A correction must clear
both a confidence threshold and a best-vs-second-best margin; uncertain text is
left untouched. Tune these advanced safeguards with `lexicon_threshold` and
`lexicon_margin` in `config.json`.

## Licenses

See `licenses/` for the shim and FFmpeg notices. Distribution must include the
Sherpa ONNX and Parakeet model notices alongside the model release.
