# SimpleParakeet

A Simple, Local, Fast OpenAI Whisper-compatible speech-to-text inference solution for Skyrimnet,
using [parakeet.cpp](https://github.com/mudler/parakeet.cpp) on CPU.

| Port | Role |
|------|------|
| **8210** | Whisper API (SkyrimNet points here) |
| **8211** | Internal recognition engine |

## Quick start

1. Unzip.
2. Double-click **`RUN-ME.bat`**.
3. On first launch, confirm or change ports.
4. When ready, paste the printed endpoint into SkyrimNet, for example:  
   `http://127.0.0.1:8210/v1/audio/transcriptions`
   - **Model:** `whisper-1`
   - **API key:** any non-empty value
5. Leave the window open while playing. Press Enter in that window to stop.

Change ports later: `pwsh -File launch.ps1 -Setup`

The model file is included under `models\` (CC BY 4.0; see `licenses\`).

## Licenses

See `licenses\`: shim MIT, parakeet.cpp MIT, GGUF CC-BY-4.0
([mudler/parakeet-cpp-gguf](https://huggingface.co/mudler/parakeet-cpp-gguf)),
FFmpeg LGPL when `bin\ffmpeg.exe` is included.
