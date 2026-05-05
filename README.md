# terminator-title-react

A [Terminator](https://gnome-terminator.org/) plugin that colors the **OS window title bar** based on what is happening in the focused terminal — the same idea as [GNOME Console](https://gitlab.gnome.org/GNOME/console), which turns its header bar red for root sessions.

Terminator's own per-pane titlebar is left completely untouched.

![example: red title bar for root session](https://raw.githubusercontent.com/Etienne-GN/terminator-title-react/main/docs/screenshot.png)

---

## How it works

Your shell sets the terminal window title via escape sequences (most distros do this by default in `~/.bashrc` or `~/.zshrc`). This plugin watches that title, matches it against your rules in order, and injects a GTK CSS override for the window's CSD decoration the moment a match is found. When no rule matches the title bar reverts to the theme default.

> **Requires GTK3 client-side decorations (CSD).**  
> This is the default on modern GNOME (X11 and Wayland). Has no visual effect under window managers that provide their own server-side decorations (SSD).

---

## Installation

```bash
git clone git@github.com:Etienne-GN/terminator-title-react.git
cd terminator-title-react
bash install.sh
```

Then in Terminator:

1. **Preferences → Plugins** → tick **TitleReact** → OK
2. Restart Terminator (or close and reopen the preferences dialog to reload plugins)

---

## Configuration

Right-click anywhere in a terminal → **Title React → Preferences…**

Each rule has:

| Field | Description |
|---|---|
| **Name** | A friendly label (for your reference only) |
| **Regex Pattern** | Python `re` regex matched against the terminal window title |
| **Title bar color** | Background color for the OS window title bar |
| **Title text color** | Optional foreground (text + buttons) color override |
| **Enabled** | Toggle a rule on/off without deleting it |

Rules are evaluated top-to-bottom; **the first match wins**.

---

## Example rules

### Root session (`sudo -i`, `sudo su`, `su -`)

Most shells update the window title to something like `root@hostname:~` when you become root.

| Name | Pattern | BG Color | FG Color |
|---|---|---|---|
| root | `root@` | `#cc0000` | `#ffffff` |

> **Why not `\broot@`?**  
> `\b` is a *word-boundary* anchor — it prevents matching `notroot@host`.  
> In practice shell titles look like `root@host:path`, so a plain `root@` is enough.  
> Use `\b` if you want to be extra safe against unusual hostnames or custom prompts.

### SSH connections

```
user@remote-host:~
```

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

If your `PS1` / `PROMPT_COMMAND` already embeds context markers in the title you can match on those directly:

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
