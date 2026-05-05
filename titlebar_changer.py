# Titlebar Changer - Terminator plugin
# Watches each terminal's window title and reacts to regex matches by coloring
# either the per-pane Terminator titlebar or the OS-level window title bar.
#
# Configure via right-click menu:  Titlebar Changer → Preferences…
#
# Each rule has:
#   Name     – a friendly label for the rule
#   Pattern  – a Python regex matched against the terminal window title
#   BG Color – background color  (e.g. #cc0000)
#   FG Color – optional text / button color override
#   Enabled  – toggle on/off without deleting
#
# Two color targets (chosen globally in Preferences):
#   Titlebar  – colors the per-pane strip at the top of each terminal split;
#               each pane reacts independently → works with split layouts
#   Window    – colors the OS-level CSD header bar for the whole window;
#               any pane matching a rule is enough to trigger the color change;
#               requires GTK3 client-side decorations (default on modern GNOME)
#
# First matching rule wins.  When no rule matches the original colors are restored.

import re

from gi.repository import Gtk, Gdk, GObject

import terminatorlib.plugin as plugin
from terminatorlib.config import Config
from terminatorlib.terminator import Terminator
from terminatorlib.translation import _
from terminatorlib.util import dbg, err

AVAILABLE = ['TitlebarChanger']

(COL_ENABLED, COL_NAME, COL_PATTERN, COL_BG, COL_FG) = range(5)

TARGET_TITLEBAR = 'titlebar'
TARGET_WINDOW   = 'window'

# ─── colour helpers ──────────────────────────────────────────────────────────

def _rgba_to_hex(rgba):
    return '#%02x%02x%02x' % (
        int(rgba.red   * 255),
        int(rgba.green * 255),
        int(rgba.blue  * 255),
    )


def _hex_to_rgba(hex_str):
    rgba = Gdk.RGBA()
    return rgba if (hex_str and rgba.parse(hex_str)) else None


def _darken(hex_str, factor=0.75):
    rgba = _hex_to_rgba(hex_str)
    if rgba is None:
        return hex_str
    return '#%02x%02x%02x' % (
        int(rgba.red   * 255 * factor),
        int(rgba.green * 255 * factor),
        int(rgba.blue  * 255 * factor),
    )


# ─── plugin ──────────────────────────────────────────────────────────────────

class TitlebarChanger(plugin.MenuItem):
    """Color the per-pane titlebar or the OS window title bar based on regex rules."""

    capabilities = ['terminal_menu']

    _class_serial = 0  # incremented per widget to create a unique CSS class

    rules             = None  # list of rule dicts
    target            = None  # TARGET_TITLEBAR or TARGET_WINDOW
    watched           = None  # set of Terminal objects
    handler_ids       = None  # Terminal → [(obj, signal_id), …]
    terminal_override = None  # Terminal → (bg_hex, fg_hex) | None
    window_class      = None  # GtkWindow → str  (unique CSS class)
    window_provider   = None  # GtkWindow → Gtk.CssProvider
    tb_class          = None  # Terminal → str  (unique CSS class for titlebar)
    tb_provider       = None  # Terminal → Gtk.CssProvider

    def __init__(self):
        plugin.MenuItem.__init__(self)
        self.rules             = []
        self.target            = TARGET_WINDOW
        self.watched           = set()
        self.handler_ids       = {}
        self.terminal_override = {}
        self.window_class      = {}
        self.window_provider   = {}
        self.tb_class          = {}
        self.tb_provider       = {}
        self._load_config()
        self._update_watched()

    def unload(self):
        for terminal in list(self.watched):
            self._unwatch_terminal(terminal)
        self._clear_all_window_css()
        self._clear_all_titlebar_css()

    # ── config ───────────────────────────────────────────────────────────────

    def _load_config(self):
        cfg = Config()
        sections = cfg.plugin_get_config(self.__class__.__name__)
        # Migration: fall back to old plugin name if no config found yet
        if not isinstance(sections, dict) or not sections:
            old = cfg.plugin_get_config('TitleReact')
            if isinstance(old, dict):
                sections = old
        self.target = TARGET_WINDOW
        if isinstance(sections, dict):
            t = sections.get('target', TARGET_WINDOW)
            self.target = TARGET_TITLEBAR if t == TARGET_TITLEBAR else TARGET_WINDOW
        self.rules = []
        if not isinstance(sections, dict):
            return
        ordered = []
        for _key, item in sections.items():
            if not isinstance(item, dict):
                continue
            try:
                pos = int(item.get('position', len(ordered)))
            except (TypeError, ValueError):
                pos = len(ordered)
            ordered.append((pos, item))
        ordered.sort(key=lambda x: x[0])
        for _pos, item in ordered:
            self.rules.append({
                'name':     item.get('name', ''),
                'pattern':  item.get('pattern', ''),
                'bg_color': item.get('bg_color', ''),
                'fg_color': item.get('fg_color', ''),
                'enabled':  bool(item.get('enabled', True)),
            })
        dbg('TitlebarChanger: loaded %d rule(s), target=%s' % (len(self.rules), self.target))

    def _save_config(self):
        cfg = Config()
        cfg.plugin_del_config(self.__class__.__name__)
        cfg.plugin_set(self.__class__.__name__, 'target', self.target)
        for i, rule in enumerate(self.rules):
            cfg.plugin_set(self.__class__.__name__,
                           'rule_%d' % i,
                           {'name':     rule['name'],
                            'pattern':  rule['pattern'],
                            'bg_color': rule['bg_color'],
                            'fg_color': rule['fg_color'],
                            'enabled':  rule['enabled'],
                            'position': i})
        cfg.save()

    # ── watching terminals ────────────────────────────────────────────────────

    def _update_watched(self):
        for terminal in Terminator().terminals:
            if terminal not in self.watched:
                self._watch_terminal(terminal)

    def _watch_terminal(self, terminal):
        hids = []
        hid = terminal.connect('title-change', self._on_title_change)
        hids.append((terminal, hid))
        hid = terminal.connect('focus-in', self._on_focus_in)
        hids.append((terminal, hid))
        hid = terminal.connect('focus-out', self._on_focus_out, None)
        hids.append((terminal, hid))
        self.handler_ids[terminal] = hids
        self.watched.add(terminal)
        self.terminal_override[terminal] = None

        self._check_and_set(terminal, terminal.get_window_title() or '')
        self._dispatch_update(terminal)
        dbg('TitlebarChanger: watching terminal %s' % terminal)

    def _unwatch_terminal(self, terminal):
        for obj, hid in self.handler_ids.pop(terminal, []):
            try:
                obj.disconnect(hid)
            except Exception:
                pass
        self.terminal_override.pop(terminal, None)
        self.watched.discard(terminal)

    # ── signal handlers ───────────────────────────────────────────────────────

    def _on_title_change(self, terminal, title):
        old = self.terminal_override.get(terminal)
        self._check_and_set(terminal, title or '')
        new = self.terminal_override.get(terminal)
        if new != old:
            self._dispatch_update(terminal)
        return False

    def _on_focus_in(self, terminal, *_args):
        if self.target == TARGET_WINDOW:
            window = terminal.get_toplevel()
            if isinstance(window, Gtk.Window):
                self._update_window(window)
        return False

    def _on_focus_out(self, _terminal, _event, _data):
        GObject.idle_add(self._update_watched)
        return False

    # ── rule matching ─────────────────────────────────────────────────────────

    def _check_and_set(self, terminal, title):
        match = None
        for rule in self.rules:
            if not rule.get('enabled', True):
                continue
            pattern = (rule.get('pattern') or '').strip()
            if not pattern:
                continue
            try:
                if re.search(pattern, title):
                    match = (rule['bg_color'], rule['fg_color'])
                    break
            except re.error as exc:
                err('TitlebarChanger: bad regex %r – %s' % (pattern, exc))
        self.terminal_override[terminal] = match

    # ── dispatch ──────────────────────────────────────────────────────────────

    def _dispatch_update(self, terminal):
        """Route the update to the right target (titlebar or window)."""
        if self.target == TARGET_TITLEBAR:
            self._apply_titlebar_css(terminal, self.terminal_override.get(terminal))
        else:
            window = terminal.get_toplevel()
            if isinstance(window, Gtk.Window):
                self._update_window(window)

    # ── window-level CSS (TARGET_WINDOW) ──────────────────────────────────────

    def _get_window_override(self, window):
        """Return the first matching override for any terminal in *window*."""
        for terminal in self.watched:
            if terminal.get_toplevel() is window:
                override = self.terminal_override.get(terminal)
                if override is not None:
                    return override
        return None

    def _update_window(self, window):
        self._apply_window_css(window, self._get_window_override(window))

    def _ensure_window_class(self, window):
        if window not in self.window_class:
            TitlebarChanger._class_serial += 1
            cls = 'titlebar-changer-win-%d' % TitlebarChanger._class_serial
            window.get_style_context().add_class(cls)
            self.window_class[window] = cls
        return self.window_class[window]

    def _ensure_window_provider(self, window):
        if window not in self.window_provider:
            provider = Gtk.CssProvider()
            screen = window.get_screen() or Gdk.Screen.get_default()
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            self.window_provider[window] = provider
        return self.window_provider[window]

    def _apply_window_css(self, window, override):
        cls      = self._ensure_window_class(window)
        provider = self._ensure_window_provider(window)

        if override:
            bg_hex, fg_hex = override
            parts = []
            if bg_hex:
                dark = _darken(bg_hex)
                parts.append(
                    'window.%(cls)s .titlebar,'
                    'window.%(cls)s headerbar {'
                    '  background-color: %(bg)s;'
                    '  background-image: none;'
                    '}' % {'cls': cls, 'bg': bg_hex})
                parts.append(
                    'window.%(cls)s:backdrop .titlebar,'
                    'window.%(cls)s:backdrop headerbar {'
                    '  background-color: %(dark)s;'
                    '  background-image: none;'
                    '}' % {'cls': cls, 'dark': dark})
            if fg_hex:
                parts.append(
                    'window.%(cls)s .titlebar *,'
                    'window.%(cls)s headerbar * {'
                    '  color: %(fg)s;'
                    '}' % {'cls': cls, 'fg': fg_hex})
                parts.append(
                    'window.%(cls)s:backdrop .titlebar *,'
                    'window.%(cls)s:backdrop headerbar * {'
                    '  color: mix(%(fg)s, #888888, 0.3);'
                    '}' % {'cls': cls, 'fg': fg_hex})
            css = '\n'.join(parts)
        else:
            css = ''

        try:
            provider.load_from_data(css.encode())
        except Exception as exc:
            err('TitlebarChanger: window CSS load failed: %s' % exc)

    def _clear_all_window_css(self):
        for provider in self.window_provider.values():
            try:
                provider.load_from_data(b'')
            except Exception:
                pass

    # ── per-pane titlebar CSS (TARGET_TITLEBAR) ───────────────────────────────

    def _apply_titlebar_css(self, terminal, override):
        titlebar_widget = getattr(terminal, 'titlebar', None)
        if titlebar_widget is None:
            return

        if terminal not in self.tb_class:
            TitlebarChanger._class_serial += 1
            cls = 'titlebar-changer-tb-%d' % TitlebarChanger._class_serial
            titlebar_widget.get_style_context().add_class(cls)
            self.tb_class[terminal] = cls
        cls = self.tb_class[terminal]

        if terminal not in self.tb_provider:
            provider = Gtk.CssProvider()
            screen = titlebar_widget.get_screen() or Gdk.Screen.get_default()
            # Priority 850 > APPLICATION (600) so we win over Terminator's own styling.
            Gtk.StyleContext.add_provider_for_screen(screen, provider, 850)
            self.tb_provider[terminal] = provider
        provider = self.tb_provider[terminal]

        if override:
            bg_hex, fg_hex = override
            parts = []
            if bg_hex:
                parts.append(
                    '.%(cls)s {'
                    '  background-color: %(bg)s;'
                    '  background-image: none;'
                    '}' % {'cls': cls, 'bg': bg_hex})
            if fg_hex:
                parts.append(
                    '.%(cls)s label {'
                    '  color: %(fg)s;'
                    '}' % {'cls': cls, 'fg': fg_hex})
            css = '\n'.join(parts)
        else:
            css = ''

        try:
            provider.load_from_data(css.encode())
        except Exception as exc:
            err('TitlebarChanger: titlebar CSS load failed: %s' % exc)

    def _clear_all_titlebar_css(self):
        for provider in self.tb_provider.values():
            try:
                provider.load_from_data(b'')
            except Exception:
                pass

    # ── context menu ──────────────────────────────────────────────────────────

    def callback(self, menuitems, _menu, _terminal):
        self._update_watched()
        item = Gtk.MenuItem.new_with_mnemonic(_('_Titlebar Changer'))
        submenu = Gtk.Menu()
        item.set_submenu(submenu)
        prefs = Gtk.MenuItem.new_with_mnemonic(_('_Preferences…'))
        prefs.connect('activate', self.configure)
        submenu.append(prefs)
        menuitems.append(item)

    # ── configuration dialog ──────────────────────────────────────────────────

    def configure(self, widget, _data=None):
        dialog = Gtk.Dialog(
            _('Titlebar Changer – Rules'),
            None,
            Gtk.DialogFlags.MODAL,
            (_('_Cancel'), Gtk.ResponseType.REJECT,
             _('_OK'),     Gtk.ResponseType.ACCEPT))
        if widget:
            try:
                dialog.set_transient_for(widget.get_toplevel())
            except Exception:
                pass
        dialog.set_default_size(720, 460)

        # ── target selector ───────────────────────────────────────────────────
        target_frame = Gtk.Frame(label=_(' Color target '))
        target_box = Gtk.HBox(spacing=18)
        target_box.set_border_width(8)

        rb_window   = Gtk.RadioButton.new_with_mnemonic(
            None, _('_Window title bar  (OS-level CSD; any matching pane triggers it)'))
        rb_titlebar = Gtk.RadioButton.new_with_mnemonic_from_widget(
            rb_window, _('_Titlebar  (per-pane strip; each split reacts independently)'))

        if self.target == TARGET_TITLEBAR:
            rb_titlebar.set_active(True)
        else:
            rb_window.set_active(True)

        target_box.pack_start(rb_window,   False, False, 0)
        target_box.pack_start(rb_titlebar, False, False, 0)
        target_frame.add(target_box)
        dialog.vbox.pack_start(target_frame, False, False, 6)

        # ── rule list ─────────────────────────────────────────────────────────
        store = Gtk.ListStore(bool, str, str, str, str)
        for rule in self.rules:
            store.append([rule.get('enabled', True),
                          rule.get('name', ''),
                          rule.get('pattern', ''),
                          rule.get('bg_color', ''),
                          rule.get('fg_color', '')])

        treeview = Gtk.TreeView(model=store)
        treeview.get_selection().set_mode(Gtk.SelectionMode.SINGLE)

        rend = Gtk.CellRendererToggle()
        rend.connect('toggled', self._on_toggled, store)
        treeview.append_column(
            Gtk.TreeViewColumn(_('On'), rend, active=COL_ENABLED))

        rend = Gtk.CellRendererText()
        rend.set_property('editable', True)
        rend.connect('edited', self._on_text_edited, store, COL_NAME)
        col = Gtk.TreeViewColumn(_('Name'), rend, text=COL_NAME)
        col.set_min_width(110)
        treeview.append_column(col)

        rend = Gtk.CellRendererText()
        rend.set_property('editable', True)
        rend.connect('edited', self._on_text_edited, store, COL_PATTERN)
        col = Gtk.TreeViewColumn(_('Regex Pattern'), rend, text=COL_PATTERN)
        col.set_expand(True)
        treeview.append_column(col)

        for title, col_idx in ((_('BG Color'), COL_BG), (_('FG Color'), COL_FG)):
            rend = Gtk.CellRendererText()
            rend.set_property('editable', False)
            col = Gtk.TreeViewColumn(title, rend, text=col_idx)
            col.set_cell_data_func(rend, self._render_color_cell, col_idx)
            col.set_min_width(88)
            treeview.append_column(col)

        treeview.connect('row-activated',
                         lambda tv, _p, _c: self._on_edit(None, tv, dialog))

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(treeview)

        hbox = Gtk.HBox(spacing=6)
        hbox.pack_start(scroll, True, True, 0)

        btn_box = Gtk.VBox(spacing=4)
        for lbl, fn in (
                (_('Add'),    lambda b, tv: self._on_add(b, tv, dialog)),
                (_('Edit'),   lambda b, tv: self._on_edit(b, tv, dialog)),
                (_('Delete'), self._on_delete),
                (_('Up'),     self._on_up),
                (_('Down'),   self._on_down)):
            btn = Gtk.Button(label=lbl)
            btn.connect('clicked', fn, treeview)
            btn_box.pack_start(btn, False, False, 0)
        hbox.pack_start(btn_box, False, False, 0)

        dialog.vbox.pack_start(hbox, True, True, 6)

        hint = Gtk.Label()
        hint.set_markup(_(
            '<small>'
            'Regex matched against the VTE window title (set by your shell prompt).\n'
            'First matching rule wins.  '
            '<b>Titlebar</b>: colors each pane\'s own title strip independently.  '
            '<b>Window</b>: colors the OS CSD header bar — any matching pane is enough.'
            '</small>'))
        hint.set_line_wrap(True)
        hint.set_xalign(0)
        dialog.vbox.pack_start(hint, False, False, 4)

        dialog.show_all()

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            new_target = TARGET_TITLEBAR if rb_titlebar.get_active() else TARGET_WINDOW

            # Clear stale CSS when switching modes.
            if new_target != self.target:
                if self.target == TARGET_WINDOW:
                    self._clear_all_window_css()
                else:
                    self._clear_all_titlebar_css()
                self.target = new_target

            self.rules = []
            it = store.get_iter_first()
            while it is not None:
                self.rules.append({
                    'enabled':  store.get_value(it, COL_ENABLED),
                    'name':     (store.get_value(it, COL_NAME)    or '').strip(),
                    'pattern':  (store.get_value(it, COL_PATTERN) or '').strip(),
                    'bg_color': store.get_value(it, COL_BG) or '',
                    'fg_color': store.get_value(it, COL_FG) or '',
                })
                it = store.iter_next(it)
            self._save_config()

            # Re-evaluate all terminals against the new rules / target.
            for terminal in self.watched:
                self._check_and_set(terminal, terminal.get_window_title() or '')
                self._dispatch_update(terminal)

        dialog.destroy()

    # ── tree-view helpers ─────────────────────────────────────────────────────

    def _render_color_cell(self, _col, cell, model, it, col_idx):
        hex_color = model.get_value(it, col_idx) or ''
        cell.set_property('text', hex_color or '—')
        rgba = _hex_to_rgba(hex_color) if hex_color else None
        if rgba:
            cell.set_property('background-rgba', rgba)
            lum = 0.299 * rgba.red + 0.587 * rgba.green + 0.114 * rgba.blue
            cell.set_property('foreground', '#000000' if lum > 0.5 else '#ffffff')
            cell.set_property('foreground-set', True)
            cell.set_property('background-set', True)
        else:
            cell.set_property('background-set', False)
            cell.set_property('foreground-set', False)

    def _on_toggled(self, _rend, path, store):
        it = store.get_iter(path)
        store.set_value(it, COL_ENABLED, not store.get_value(it, COL_ENABLED))

    def _on_text_edited(self, _rend, path, new_text, store, col):
        store[path][col] = new_text

    def _on_add(self, _btn, treeview, parent=None):
        result = self._edit_rule_dialog(None, parent or treeview.get_toplevel())
        if result:
            treeview.get_model().append([
                result['enabled'], result['name'],
                result['pattern'], result['bg_color'], result['fg_color'],
            ])

    def _on_edit(self, _btn, treeview, parent=None):
        store, it = treeview.get_selection().get_selected()
        if it is None:
            return
        current = {
            'enabled':  store.get_value(it, COL_ENABLED),
            'name':     store.get_value(it, COL_NAME),
            'pattern':  store.get_value(it, COL_PATTERN),
            'bg_color': store.get_value(it, COL_BG),
            'fg_color': store.get_value(it, COL_FG),
        }
        result = self._edit_rule_dialog(current, parent or treeview.get_toplevel())
        if result:
            store.set(it,
                      COL_ENABLED, result['enabled'],
                      COL_NAME,    result['name'],
                      COL_PATTERN, result['pattern'],
                      COL_BG,      result['bg_color'],
                      COL_FG,      result['fg_color'])

    def _on_delete(self, _btn, treeview):
        store, it = treeview.get_selection().get_selected()
        if it is not None:
            store.remove(it)

    def _on_up(self, _btn, treeview):
        store, it = treeview.get_selection().get_selected()
        if it is None:
            return
        idx = store.get_path(it).get_indices()[0]
        if idx > 0:
            store.swap(it, store.get_iter(idx - 1))

    def _on_down(self, _btn, treeview):
        store, it = treeview.get_selection().get_selected()
        if it is None:
            return
        nxt = store.iter_next(it)
        if nxt is not None:
            store.swap(it, nxt)

    # ── add/edit rule dialog ──────────────────────────────────────────────────

    def _edit_rule_dialog(self, current, parent=None):
        dialog = Gtk.Dialog(
            _('Edit Rule') if current else _('Add Rule'),
            parent,
            Gtk.DialogFlags.MODAL,
            (_('_Cancel'), Gtk.ResponseType.REJECT,
             _('_OK'),     Gtk.ResponseType.ACCEPT))
        dialog.set_default_size(440, 0)

        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(10)
        grid.set_border_width(14)

        def _lbl(text):
            l = Gtk.Label(label=text)
            l.set_halign(Gtk.Align.END)
            return l

        row = 0

        grid.attach(_lbl(_('Enabled:')), 0, row, 1, 1)
        enabled_cb = Gtk.CheckButton()
        enabled_cb.set_active((current or {}).get('enabled', True))
        grid.attach(enabled_cb, 1, row, 2, 1)
        row += 1

        grid.attach(_lbl(_('Name:')), 0, row, 1, 1)
        name_entry = Gtk.Entry()
        name_entry.set_text((current or {}).get('name', ''))
        name_entry.set_hexpand(True)
        grid.attach(name_entry, 1, row, 2, 1)
        row += 1

        grid.attach(_lbl(_('Regex Pattern:')), 0, row, 1, 1)
        pat_entry = Gtk.Entry()
        pat_entry.set_text((current or {}).get('pattern', ''))
        pat_entry.set_hexpand(True)
        grid.attach(pat_entry, 1, row, 2, 1)
        row += 1

        grid.attach(_lbl(_('BG color:')), 0, row, 1, 1)
        bg_init  = (current or {}).get('bg_color', '')
        bg_check = Gtk.CheckButton(label=_('Custom'))
        bg_check.set_active(bool(bg_init))
        bg_btn   = Gtk.ColorButton()
        bg_rgba  = _hex_to_rgba(bg_init) if bg_init else Gdk.RGBA(0.8, 0.0, 0.0, 1.0)
        if bg_rgba:
            bg_btn.set_rgba(bg_rgba)
        bg_btn.set_sensitive(bool(bg_init))
        bg_check.connect('toggled', lambda w: bg_btn.set_sensitive(w.get_active()))
        grid.attach(bg_check, 1, row, 1, 1)
        grid.attach(bg_btn,   2, row, 1, 1)
        row += 1

        grid.attach(_lbl(_('FG color:')), 0, row, 1, 1)
        fg_init  = (current or {}).get('fg_color', '')
        fg_check = Gtk.CheckButton(label=_('Custom'))
        fg_check.set_active(bool(fg_init))
        fg_btn   = Gtk.ColorButton()
        fg_rgba  = _hex_to_rgba(fg_init) if fg_init else Gdk.RGBA(1.0, 1.0, 1.0, 1.0)
        if fg_rgba:
            fg_btn.set_rgba(fg_rgba)
        fg_btn.set_sensitive(bool(fg_init))
        fg_check.connect('toggled', lambda w: fg_btn.set_sensitive(w.get_active()))
        grid.attach(fg_check, 1, row, 1, 1)
        grid.attach(fg_btn,   2, row, 1, 1)

        dialog.vbox.pack_start(grid, True, True, 0)
        dialog.show_all()

        result = None
        while True:
            if dialog.run() != Gtk.ResponseType.ACCEPT:
                break
            pattern = pat_entry.get_text().strip()
            try:
                re.compile(pattern)
            except re.error as exc:
                msg = Gtk.MessageDialog(
                    dialog, Gtk.DialogFlags.MODAL,
                    Gtk.MessageType.ERROR, Gtk.ButtonsType.CLOSE,
                    _('Invalid regular expression:\n%s') % str(exc))
                msg.run()
                msg.destroy()
                continue
            result = {
                'enabled':  enabled_cb.get_active(),
                'name':     name_entry.get_text().strip(),
                'pattern':  pattern,
                'bg_color': _rgba_to_hex(bg_btn.get_rgba()) if bg_check.get_active() else '',
                'fg_color': _rgba_to_hex(fg_btn.get_rgba()) if fg_check.get_active() else '',
            }
            break

        dialog.destroy()
        return result
