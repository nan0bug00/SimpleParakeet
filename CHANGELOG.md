# Changelog

All notable changes to SimpleParakeet are documented here.

## [1.2.0] — 2026-07-20

### Added
- **Linux x64 (CPU)** release zip via GitHub Actions: `SimpleParakeet-linux-x64.zip`
  - Host-native `RUN-ME.sh` / `launch.sh` (PyInstaller onedir API, mudler `parakeet-server`, BtbN LGPL ffmpeg)

### Changed
- `audio.py` resolves bare `bin/ffmpeg` as well as `ffmpeg.exe` (shared Windows/Linux API)
- **`RUN-ME.sh`** opens a terminal when double-clicked from a file manager (same idea as `RUN-ME.bat` on Windows), instead of running setup invisibly with no prompts

## [1.1.0] — 2026-07-19

Official Windows release zip via GitHub Actions: [SimpleParakeet-windows-x64.zip](https://github.com/nan0bug00/SimpleParakeet/releases/tag/v1.1.0).

### Changed
- API package is now **PyInstaller onedir** (`bin\SimpleParakeet\SimpleParakeet.exe` + `_internal\`) instead of a single fat exe — cleaner antivirus results (0/64 on VirusTotal for the release zip) and easier to maintain.
- Release builds are produced automatically by GitHub Actions on `v*` tags (and manual workflow runs).

### Fixed
- Install paths with **spaces** (e.g. `C:\Skyrim MGO\...`) no longer break the recognition engine / model path, which previously left the API up but transcriptions failing with **502**.

### Added
- **`launch.cmd`** for Wine / Proton / environments without PowerShell (Windows users can keep using `RUN-ME.bat`).

## [1.0.0] — 2026-07-17

Initial public release.

### Added
- Local **OpenAI Whisper–compatible** speech-to-text API for SkyrimNet External Whisper (`/v1/audio/transcriptions`).
- CPU inference via **parakeet.cpp** with bundled English **tdt_ctc-110m** f16 GGUF.
- Default ports **8210** (Whisper API) and **8211** (internal engine) — avoids clashing with common SkyrimNet ports.
- First-run setup via **`RUN-ME.bat`** / `launch.ps1` (ports configurable; re-run setup with `pwsh -File launch.ps1 -Setup`).
- Bundled portable **ffmpeg** for non-WAV audio decode.
- License / attribution notices under `licenses\` (shim MIT, parakeet.cpp MIT, GGUF CC-BY-4.0, FFmpeg LGPL when included).

[1.2.0]: https://github.com/nan0bug00/SimpleParakeet/releases
[1.1.0]: https://github.com/nan0bug00/SimpleParakeet/releases/tag/v1.1.0
