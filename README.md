# SimpleParakeet

A Simple, Local, Fast OpenAI Whisper-compatible speech-to-text inference solution for SkyrimNet,
using [parakeet.cpp](https://github.com/mudler/parakeet.cpp) on CPU.

| Port | Role |
|------|------|
| **8210** | Whisper API (SkyrimNet points here) |
| **8211** | Internal recognition engine |

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

1. Unpack: `tar -xzf SimpleParakeet-linux-x64.tar.gz && cd SimpleParakeet`
2. Open a terminal in that folder and run: `chmod +x RUN-ME.sh && ./RUN-ME.sh`
3. On first launch, confirm or change ports (keep **`127.0.0.1`** unless you know you need otherwise).
4. Paste the printed endpoint into SkyrimNet External Whisper (same model/key as above).
5. Leave the terminal open. Press Enter to stop.

Change ports later: `./launch.sh --setup`

Localhost (`127.0.0.1`) does not require UFW/firewalld changes for Proton→host traffic.

The model file is included under `models/` (CC BY 4.0; see `licenses/`).

## Licenses

See `licenses/`: shim MIT, parakeet.cpp MIT, GGUF CC-BY-4.0
([mudler/parakeet-cpp-gguf](https://huggingface.co/mudler/parakeet-cpp-gguf)),
FFmpeg LGPL when `bin/ffmpeg` / `bin/ffmpeg.exe` is included.
