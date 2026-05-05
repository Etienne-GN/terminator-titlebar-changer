# terminator-titlebar-changer

A [Terminator](https://gnome-terminator.org/) plugin that colors a titlebar based on what is happening in a terminal pane — the same idea as [GNOME Console](https://gitlab.gnome.org/GNOME/console), which turns its header bar red for root sessions.

Two coloring targets are available, **independently toggleable** in the Preferences dialog (enable one, the other, or both):

| Target | What it colors | Split-pane aware? |
|---|---|---|
| **Titlebar** | The per-pane title strip at the top of each terminal split, including the small group menu on the left | Yes — each pane reacts independently |
| **Window** | The OS-level CSD header bar for the whole window | No — but any matching pane is enough to trigger it (configurable: see *Window follows focused pane*) |

In addition to regex rules, an optional **"Titlebar follows active profile"** mode falls back to the active terminal profile's `background_color` / `foreground_color` whenever no rule matches — useful in combination with [terminator-profile-changer](https://github.com/Etienne-GN/terminator-profile-changer) so the titlebar tracks the profile automatically. Rules always take priority over the profile color.

---

## How it works

Your shell sets the terminal window title via escape sequences (most distros do this by default in `~/.bashrc` or `~/.zshrc`). This plugin watches that title, matches it against your rules in order, and injects a GTK CSS override the moment a match is found. When no rule matches the colors revert to the theme default.

> **Window target requires GTK3 client-side decorations (CSD).**  
> This is the default on modern GNOME (X11 and Wayland). Has no visual effect under window managers that provide their own server-side decorations (SSD).  
> The **Titlebar** target works regardless.

---

## Installation

```bash
git clone git@github.com:Etienne-GN/terminator-titlebar-changer.git
cd terminator-titlebar-changer
bash install.sh
```

Then in Terminator:

1. **Preferences → Plugins** → tick **TitlebarChanger** → OK
2. Restart Terminator (or close and reopen the preferences dialog to reload plugins)

> **Upgrading from terminator-title-react?**  
> Your existing rules are automatically migrated on first load.

---

## Configuration

Right-click anywhere in a terminal → **Titlebar Changer → Preferences…**

At the top of the dialog you can:

- Toggle **Titlebar follows active profile** to fall back to the profile colors when no rule matches.
- Pick one or both **color targets**: per-pane *Titlebar* and/or OS *Window title bar*.
- When the *Window* target is on, choose whether it **follows the focused pane** (otherwise: any matching pane in the window wins).

Then manage your rules:

| Field | Description |
|---|---|
| **Name** | A friendly label (for your reference only) |
| **Regex Pattern** | Python `re` regex matched against the terminal window title |
| **BG color** | Background color |
| **FG color** | Optional foreground (text) color override |
| **Enabled** | Toggle a rule on/off without deleting it |

Rules are evaluated top-to-bottom; **the first match wins**.

---

## Example rules

### Root session (`sudo -i`, `sudo su`, `su -`)

Most shells update the window title to something like `root@hostname:~` when you become root.

| Name | Pattern | BG Color | FG Color |
|---|---|---|---|
| root | `root@` | `#cc0000` | `#ffffff` |

### SSH connections

| Name | Pattern | BG Color | FG Color |
|---|---|---|---|
| SSH | `@.*\..*:` | `#1a5276` | `#d6eaf8` |

Matches any title containing `@something.something:` — a common SSH prompt shape.

### Specific environments

| Name | Pattern | BG Color | FG Color |
|---|---|---|---|
| production | `prod` | `#7b241c` | `#fdfefe` |
| staging | `stag` | `#7d6608` | `#fef9e7` |
| Docker | `\(docker\)` | `#154360` | `#d6eaf8` |

### Combining with your shell prompt

```bash
# In ~/.bashrc — set title to  [env] user@host:path
PROMPT_COMMAND='echo -ne "\033]0;[${ENV:-dev}] \u@\h:\w\007"'
```

Then use patterns like `\[prod\]` or `\[staging\]`.

---

## Companion plugin

[terminator-profile-changer](https://github.com/Etienne-GN/terminator-profile-changer) — switches the full Terminator color *profile* (fonts, palette, background) based on the foreground process. The two plugins complement each other well.

---

## License

GPL v2
