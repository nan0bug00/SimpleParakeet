#!/usr/bin/env bash
# SimpleParakeet entrypoint (Linux).
# Double-click in a file manager, or run from a terminal: ./RUN-ME.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH="$ROOT/launch.sh"

chmod +x "$LAUNCH" 2>/dev/null || true

# File managers often run .sh with no terminal. Setup and status need a TTY,
# so re-launch inside a terminal emulator (Windows double-click equivalent).
needs_terminal() {
  [[ -n "${SIMPLEPARAKEET_IN_TERMINAL:-}" ]] && return 1
  [[ -t 0 && -t 1 ]] && return 1
  return 0
}

quote_args() {
  local a out=""
  for a in "$@"; do
    out+=" $(printf '%q' "$a")"
  done
  printf '%s' "$out"
}

# Inner command: run launcher, then pause so the window stays readable on errors.
inner_command() {
  printf 'cd %q && SIMPLEPARAKEET_IN_TERMINAL=1 bash %q%s; ec=$?; echo; read -r -p "Press Enter to close..."; exit $ec' \
    "$ROOT" "$LAUNCH" "$(quote_args "$@")"
}

try_open_terminal() {
  local cmd
  cmd="$(inner_command "$@")"

  # 1) Desktop / distro preferred terminal
  if command -v xdg-terminal-exec >/dev/null 2>&1; then
    xdg-terminal-exec -- bash -lc "$cmd" &
    return 0
  fi
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T SimpleParakeet -e bash -lc "$cmd" &
    return 0
  fi

  # 2) Modern terminals people install on purpose
  if command -v kitty >/dev/null 2>&1; then
    kitty --title SimpleParakeet bash -lc "$cmd" &
    return 0
  fi
  if command -v alacritty >/dev/null 2>&1; then
    alacritty -t SimpleParakeet -e bash -lc "$cmd" &
    return 0
  fi
  if command -v foot >/dev/null 2>&1; then
    foot -T SimpleParakeet bash -lc "$cmd" &
    return 0
  fi
  if command -v wezterm >/dev/null 2>&1; then
    wezterm start -- bash -lc "$cmd" &
    return 0
  fi

  # 3) Desktop-environment stock terminals
  if command -v kgx >/dev/null 2>&1; then
    kgx --title SimpleParakeet -e bash -lc "$cmd" &
    return 0
  fi
  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title=SimpleParakeet -- bash -lc "$cmd" &
    return 0
  fi
  if command -v konsole >/dev/null 2>&1; then
    konsole --title SimpleParakeet -e bash -lc "$cmd" &
    return 0
  fi
  if command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title=SimpleParakeet -e "bash -lc $(printf '%q' "$cmd")" &
    return 0
  fi
  if command -v mate-terminal >/dev/null 2>&1; then
    mate-terminal --title=SimpleParakeet -e "bash -lc $(printf '%q' "$cmd")" &
    return 0
  fi
  if command -v tilix >/dev/null 2>&1; then
    tilix -t SimpleParakeet -e "bash -lc $(printf '%q' "$cmd")" &
    return 0
  fi

  # 4) Last resort
  if command -v xterm >/dev/null 2>&1; then
    xterm -T SimpleParakeet -e bash -lc "$cmd" &
    return 0
  fi

  return 1
}

show_no_terminal_help() {
  # No TTY here — anything written to stderr is invisible on double-click.
  # Use a GUI dialog if the desktop provides one.
  local msg
  msg="SimpleParakeet could not find a terminal emulator to open.

Install a terminal (Konsole, GNOME Terminal, xfce4-terminal, …), then double-click RUN-ME.sh again.

Or open any terminal yourself, cd into this folder, and run ./RUN-ME.sh

Folder:
$ROOT"

  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title=SimpleParakeet --width=440 --text="$msg" 2>/dev/null && return
  fi
  if command -v kdialog >/dev/null 2>&1; then
    kdialog --error "$msg" 2>/dev/null && return
  fi
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical SimpleParakeet "$msg" 2>/dev/null && return
  fi
  # Last resort: open the README in the default viewer so something visible appears
  if command -v xdg-open >/dev/null 2>&1 && [[ -f "$ROOT/README.md" ]]; then
    xdg-open "$ROOT/README.md" 2>/dev/null || true
  fi
}

if needs_terminal; then
  if try_open_terminal "$@"; then
    exit 0
  fi
  show_no_terminal_help
  exit 1
fi

exec bash "$LAUNCH" "$@"
