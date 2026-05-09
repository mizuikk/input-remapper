# Local Notes

This file documents the local-only functionality and workflow used on this
machine. It is not intended for upstream submission.

## Branches

- `main`
  - Keep this aligned with `origin/main`.
- `fix/forwarded-mouse-dpi`
  - Upstream-facing branch. Keep this clean.
- `local/main`
  - Long-lived local branch for custom features.
- `local/windowd-kwin-rules`
  - Original branch used to develop the local window-based preset switching.

Recommended workflow:

```sh
git switch main
git pull --ff-only origin main

git switch local/main
git merge main
```

For new local work:

```sh
git switch -c local/<feature-name> local/main
```

## Local Feature

This checkout includes a local-only feature for:

- KDE Plasma 6
- KWin Wayland
- Per-window automatic preset switching

It adds:

- `input-remapper-windowd`
  - User-session daemon
- KWin script
  - Sends focused-window information to `windowd`
- `window_rules.json`
  - Maps windows to device presets

## Important Files

Repository files:

- `inputremapper/windowd/`
- `inputremapper/bin/input_remapper_windowd.py`
- `bin/input-remapper-windowd`
- `data/kwin/inputremapper-windowd/`
- `data/examples/window_rules.example.json`
- `install/data_files.py`

User/system files on this machine:

- `~/.config/input-remapper-2/window_rules.json`
- `~/.config/systemd/user/input-remapper-windowd.service`
- `/usr/share/kwin/scripts/inputremapper-windowd/`
- `/usr/bin/input-remapper-windowd`

## Current Rule

Current local rule file:

- [window_rules.json](/home/mnm/.config/input-remapper-2/window_rules.json:1)

Current behavior:

- Device: `Logitech G Pro `
- Preset: `Hold-R`
- Active only when the focused Black Desert window matches:
  - `window_class_equals = steam_app_3511522033`
  - `title_starts_with = BLACK DESERT`

## Installed Services

System service:

```sh
systemctl status input-remapper.service
```

User service:

```sh
systemctl --user status input-remapper-windowd.service
```

Session D-Bus service name:

```text
inputremapper.WindowDaemon
```

## KWin Script

The KWin script must have a valid plugin id:

```json
"Id": "inputremapper-windowd"
```

Without this, KWin may list the script incorrectly and never deliver window
events.

The enabled state is stored in:

- `~/.config/kwinrc`

Expected key:

```ini
[Plugins]
inputremapper-windowdEnabled=true
```

If behavior looks wrong after changes, log out and back in.

## Installation

System-wide install from this repository:

```sh
sudo python3 -m install --root /
sudo systemctl daemon-reload
sudo systemctl enable --now input-remapper.service
```

User daemon:

```sh
systemctl --user daemon-reload
systemctl --user enable --now input-remapper-windowd.service
```

## Usage Rules

- Do not manually start the target preset when testing window-based switching.
  - A manually started preset is global and will affect all windows.
- Leave the preset stopped.
  - `windowd` should start it only when the window rule matches.

Correct test pattern:

1. Ensure the preset is not manually injecting.
2. Focus a normal window and verify the preset is inactive.
3. Focus the target window and verify the preset becomes active.
4. Focus a different window and verify it stops again.

## Troubleshooting

Check user daemon logs:

```sh
journalctl --user -u input-remapper-windowd.service -f
```

Check system daemon logs:

```sh
journalctl -u input-remapper.service -f
```

Check that the session D-Bus service is present:

```sh
busctl --user list | rg 'inputremapper\.WindowDaemon'
```

Manual event injection for debugging:

```sh
busctl --user call inputremapper.WindowDaemon \
  /inputremapper/WindowDaemon \
  inputremapper.WindowDaemon NotifyWindow s \
  '{"windowClass":"steam_app_3511522033","title":"BLACK DESERT - 520828","pid":26874,"internalId":"manual-test"}'
```

If this manual event starts the preset, then:

- `windowd` is working
- rule matching is working
- the problem is in KWin script loading or event delivery

## Known Local Changes

- `install/data_files.py` was adjusted so `data/*` only copies regular files.
  - This avoids crashing when `data/kwin/` exists as a directory.
- KWin script metadata includes `KPlugin.Id`.
  - This was required for proper KWin script recognition on this machine.

## Upstream Policy

This local feature is intentionally not prepared for upstream submission.

Keep upstream work separate:

- upstream-targeted fixes on dedicated branches
- local features on `local/main` and its child branches
