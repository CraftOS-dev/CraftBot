"""The installer window.

Layout is absolute (`place`) and the window is a fixed size — an installer is
a fixed-size dialog on every OS, and absolute positioning keeps the vertical
rhythm exact without a layout manager second-guessing it.

## What is on screen, and what is not

One animated mark, one line of status, one primary button. There is no log
panel: during a twenty-minute install the useful signal is "which stage, how
far", not ten thousand lines of pip output. That output still exists — it goes
to craftbot.log, and `Open log` hands it to the OS — but showing it by default
made the window big and busy for something almost nobody reads.

## Why text is drawn on a canvas

Tk widgets are opaque rectangles, and a label is a rectangle whether you want
one or not. Text that should have no surface of its own — the wordmark, the
status line, the links — is drawn as a *canvas item* instead, which puts
glyphs on the background and nothing else. Text that lives inside a control
is a normal label filled with that control's colour.

Canvas items cannot be drawn on top of a widget — Tk always draws widgets
above them — which is the whole reason for the split.

## Threading

`api.get_state()` shells out to `tasklist` on Windows to test whether the
agent's PID is alive. Calling that on the Tk main loop would stutter the
window every second, and freeze it outright for the call's 5s timeout if
tasklist hung. So state is polled on a daemon thread and handed back through a
Queue the UI drains on its own tick. `api.drain_output()` is just a lock and a
list, and is cheap enough to call from the UI thread.
"""

from __future__ import annotations

import os
import queue
import random
import subprocess
import sys
import threading
import time
import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from installer.ui import chrome
from installer.ui.glass import elide, pick_font
from installer.ui.theme import PALETTE

__all__ = ["InstallerWindow", "run"]

# Design size, in layout units, scaled by the display's DPI factor. See Metrics.
BASE_WIDTH = 440
BASE_HEIGHT = 540

OUTPUT_TICK_MS = 200  # drain buffered log lines (cheap, UI thread)
STATE_TICK_S = 1.0  # re-poll install/run state (expensive, worker thread)
MEASURED_GRACE_S = 3.0  # how long a byte count keeps the bar determinate

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_UI_DIR))

#: Pre-rendered from craftbot_logo_1.png into installer/ui/assets/ by
#: scripts/build_installer_marks.py. Two reasons it is not the icon file
#: itself:
#:
#:   * Tk can only scale a PhotoImage by integer subsample/zoom, which turns
#:     the 3000px source into an aliased mess at this size.
#:   * The icon draws the robot on a dark rounded-square tile, which reads as
#:     a box sitting on the window. These have the tile removed, so the mark
#:     sits directly on the background.
MARK_SIZES = (96, 144, 192)
MARK_BASE = 96

#: Blink frames per size, closing the eyes progressively. Frame 0 is the
#: open mark itself, so only 1..N are separate files.
BLINK_FRAMES = 3
#: Frame order for one blink: close, hold, open. Ends on 0 so the mark is
#: left open between blinks.
BLINK_SEQUENCE = (1, 2, 3, 3, 2, 1, 0)
BLINK_STEP_MS = 45


class Metrics:
    """Layout constants, scaled once for the display.

    CustomTkinter's automatic DPI handling scales the widgets it draws but
    knows nothing about `place()` coordinates, so on a 150% display the
    controls would grow while the positions stayed put. We turn its scaling
    off and do the arithmetic here, keeping one source of truth.
    """

    def __init__(self, factor: float) -> None:
        self.factor = factor
        self.width = self.px(BASE_WIDTH)
        self.height = self.px(BASE_HEIGHT)
        self.pad = self.px(28)
        self.content_width = self.width - 2 * self.pad
        # Nearest pre-rendered mark, rather than asking Tk to rescale one.
        self.mark = min(MARK_SIZES, key=lambda s: abs(s - MARK_BASE * factor))

    def px(self, value: float) -> int:
        return int(round(value * self.factor))

    @staticmethod
    def font(size: int) -> int:
        # Tk font sizes are in points and are DPI-scaled by Tk itself, so
        # these must NOT be multiplied again.
        return size


def _display_scale() -> float:
    """The display's scale factor, as a multiplier on the design size."""
    if sys.platform != "win32":
        return 1.0  # Tk handles Retina and most Linux HiDPI transparently
    try:
        import ctypes

        dpi = ctypes.windll.user32.GetDpiForSystem()  # Windows 10 1607+
        return max(1.0, min(2.0, dpi / 96.0))
    except Exception:
        return 1.0


class InstallerWindow(ctk.CTk):
    """The whole UI. Owns no install logic — every action is a call into
    WizardAPI, which is shared with the command-line path."""

    #: Placeholders _read_bundled_version() returns for a local build.
    #: "Version latest" is worse than no version at all.
    _UNVERSIONED = {"", "latest", "dev", "unknown"}

    def __init__(self, api, version: str = "") -> None:
        super().__init__()
        self.api = api
        self.version = version
        self.p = PALETTE
        self.m = Metrics(_display_scale())

        self._state: Dict = {"state": "not_installed", "worker_busy": False}
        self._state_q: "queue.Queue[Dict]" = queue.Queue()
        self._stopping = threading.Event()
        self._target_dir = ""
        self._primary_action: Optional[Callable[[], None]] = None
        self._alive = True

        # Hide during construction so the user does not watch a small empty
        # box jump across the screen before the real UI appears.
        #
        # This MUST NOT use withdraw(). CustomTkinter's CTk.withdraw() records
        # `_withdraw_called_before_window_exists`, and its mainloop() then
        # deliberately skips the deiconify() it would otherwise do — leaving
        # the window mapped but permanently invisible, with mainloop running
        # forever behind it. To the user that looks exactly like the installer
        # opening and instantly closing, and it survives an explicit
        # deiconify() here because CTk re-withdraws while setting the
        # title-bar colour. Alpha is not intercepted; where a platform has no
        # compositor it is ignored and the only cost is the flash it avoids.
        self._set_opacity(0.0)
        self._configure_window()
        self._build()
        self._set_opacity(1.0)
        self._start_polling()

    def _set_opacity(self, value: float) -> None:
        try:
            self.attributes("-alpha", value)
        except Exception:
            pass

    # ── Window setup ────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        self.title("CraftBot Setup")
        self.resizable(False, False)
        chrome.center(self, self.m.width, self.m.height)
        # The root's own background shows for a beat before the canvas is
        # mapped; matching it avoids a pale flash on open.
        self.configure(fg_color=self.p.base)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        chrome.set_window_icon(
            self,
            os.path.join(_ROOT, "craftbot_logo_1.ico"),
            os.path.join(_ROOT, "craftbot_logo_1.png"),
        )
        # Paint the title bar the window's own colour so the frame and the
        # content read as one surface.
        chrome.apply_native_chrome(
            self,
            caption=self.p.base,
            caption_text=self.p.text_dim,
        )

    def _build(self) -> None:
        self.font_display = ctk.CTkFont(pick_font("display"), self.m.font(23), "bold")
        self.font_ui = ctk.CTkFont(pick_font("ui"), self.m.font(12))
        self.font_small = ctk.CTkFont(pick_font("ui"), self.m.font(11))
        self.font_button = ctk.CTkFont(pick_font("ui"), self.m.font(14), "bold")

        self.canvas = tk.Canvas(
            self,
            width=self.m.width,
            height=self.m.height,
            highlightthickness=0,
            bd=0,
            bg=self.p.base,
        )
        self.canvas.place(x=0, y=0)

        self._build_sections()

        # Put the background canvas at the BOTTOM of the stacking order.
        #
        # It is a full-window canvas created before every control, so on Tk
        # the controls land above it by creation order alone — which is why
        # this was never needed on Windows. Relying on that is an implicit
        # assumption about sibling stacking, and a canvas that covers the
        # whole window is exactly the thing that swallows clicks when the
        # assumption does not hold.
        #
        # Via Misc, not self.canvas.lower(): Canvas overrides lower() to mean
        # tag_lower (restack a canvas ITEM), so calling it on the widget
        # raises "wrong # args". This is the widget-stacking one.
        tk.Misc.lower(self.canvas)

    def _build_sections(self) -> None:
        self._build_mark()
        self._build_identity()
        self._build_location()
        self._build_actions()
        self._build_footer()

    def _text(self, x, y, text, font, color, anchor="center") -> int:
        """Draw text straight onto the backdrop, with no widget and so no
        rectangle. Returns the item id for later itemconfigure()."""
        return self.canvas.create_text(
            x, y, text=text, font=font, fill=color, anchor=anchor
        )

    # ── The mark ────────────────────────────────────────────────────────

    def _build_mark(self) -> None:
        """The logo, which blinks.

        The animation is frame-based rather than drawn: the frames are
        pre-rendered from the source logo at build time (see MARK_SIZES), so
        the closing eyes are properly antialiased at every DPI scale. Tk's
        canvas has no antialiasing, so shapes drawn here would have jagged
        edges — and Tk has no alpha channel, so an overlay covering the eyes
        would have to match the head colour exactly and would still be hard.

        An earlier attempt floated the whole mark a couple of pixels and spun
        a ring around it. Both were too subtle to notice, which is worse than
        no animation: it costs a frame timer and reads as static anyway.
        A blink is unmistakable.
        """
        m = self.m
        cx, cy = m.width / 2, m.px(112)
        assets = os.path.join(_UI_DIR, "assets")

        # Frame 0 is the open mark; 1..3 progressively close the eyes.
        names = [f"craftbot_mark_{m.mark}.png"] + [
            f"craftbot_mark_{m.mark}_blink{i}.png" for i in range(1, BLINK_FRAMES + 1)
        ]
        self._mark_frames: List = []
        self._mark_item = None
        for name in names:
            path = os.path.join(assets, name)
            try:
                # Tk drops a PhotoImage as soon as its last Python reference
                # goes away, which shows as an image that paints once then
                # blanks. Holding them on the instance is the fix.
                self._mark_frames.append(tk.PhotoImage(file=path))
            except Exception as e:
                # A missing asset must not stop someone installing — but it
                # must not fail *silently* either. An asset loaded by path is
                # invisible to PyInstaller's module graph, so a packaging
                # mistake would ship a build that quietly looks wrong. That is
                # exactly how issue #439 happened.
                from installer.wizard import _log

                _log(f"mark frame missing ({path}): {type(e).__name__}: {e}")
                break

        if self._mark_frames:
            self._mark_item = self.canvas.create_image(
                cx, cy, image=self._mark_frames[0]
            )
            if len(self._mark_frames) > BLINK_FRAMES:
                self.after(self._blink_gap(), self._blink)
        else:
            self._text(cx, cy, "CB", self.font_display, self.p.text)

    @staticmethod
    def _blink_gap() -> int:
        """Milliseconds until the next blink. Randomised so it reads as alive
        rather than as a metronome."""
        return random.randint(2800, 5200)

    def _blink(self, step: int = 0) -> None:
        """Play one blink, a frame at a time, then wait and do it again."""
        if not self._alive or self._mark_item is None:
            return
        try:
            self.canvas.itemconfigure(
                self._mark_item, image=self._mark_frames[BLINK_SEQUENCE[step]]
            )
            if step + 1 < len(BLINK_SEQUENCE):
                self.after(BLINK_STEP_MS, self._blink, step + 1)
            else:
                self.after(self._blink_gap(), self._blink, 0)
        except Exception:
            return  # the window went away between the check and the draw

    # ── Identity + status ───────────────────────────────────────────────

    def _build_identity(self) -> None:
        m = self.m
        self._text(m.width / 2, m.px(204), "CraftBot", self.font_display, self.p.text)
        self.status_item = self._text(
            m.width / 2, m.px(228), "Checking…", self.font_small, self.p.text_dim
        )

    def _set_status(self, text: str, color: Optional[str] = None) -> None:
        self.canvas.itemconfigure(
            self.status_item, text=text, fill=color or self.p.text_dim
        )

    # ── Install location ────────────────────────────────────────────────

    def _build_location(self) -> None:
        m = self.m
        self.path_item = self._text(
            m.width / 2, m.px(296), "", self.font_small, self.p.text_faint
        )
        # A link, not a button. Changing the location is a rare, secondary
        # act; giving it a bordered pill put it in the same visual class as
        # Stop/Repair/Uninstall and competed with the one action that matters.
        self.change_item = self._link(
            m.width / 2, m.px(318), "Change location", self._on_change_location
        )
        self._set_target(self.api.get_default_install_location())

    def _set_change_enabled(self, enabled: bool) -> None:
        """Links have no disabled state, so fade it and drop the binding."""
        self._change_enabled = enabled
        self.canvas.itemconfigure(
            self.change_item,
            fill=self.p.text_dim if enabled else self.p.text_faint,
            state="normal" if enabled else "disabled",
        )

    def _set_target(self, path: str) -> None:
        self._target_dir = path or ""
        self.canvas.itemconfigure(self.path_item, text=elide(self._target_dir, 42))

    # ── Actions ─────────────────────────────────────────────────────────

    def _build_actions(self) -> None:
        m = self.m
        pw, ph = m.px(240), m.px(46)
        px_, py = (m.width - pw) // 2, m.px(378)
        self.btn_primary = ctk.CTkButton(
            self,
            text="Install CraftBot",
            width=pw,
            height=ph,
            corner_radius=ph // 2,
            font=self.font_button,
            fg_color=self.p.accent,
            hover_color=self.p.accent_hover,
            text_color=self.p.accent_text,
            text_color_disabled=self.p.text_dim,
            bg_color=self.p.base,
            command=self._on_primary,
        )
        self.btn_primary.place(x=px_, y=py)
        # A disabled button keeping the full accent fill still reads as
        # pressable, so busy state swaps it for glass.
        self._primary_busy_fill = self.p.surface_raised

        # Progress sits directly under the status line, which is where the
        # byte count it belongs to is written — and out of the gap between
        # the primary and the secondary row, which is deliberately tight.
        # Created now, placed only once there is real progress: a bar sitting
        # at zero for two minutes reads as "stuck".
        self._bar_w, self._bar_h = m.px(240), m.px(5)
        self._bar_pos = ((m.width - self._bar_w) // 2, m.px(252))
        self.progress = ctk.CTkProgressBar(
            self,
            width=self._bar_w,
            height=self._bar_h,
            corner_radius=self._bar_h // 2,
            progress_color=self.p.accent,
            fg_color=self.p.film(0.12),
            bg_color=self.p.base,
        )
        self.progress.set(0)
        self._progress_shown = False
        self._progress_mode = "determinate"
        # When a measured download last reported. The state poll and the
        # output drain both want the bar, and without this the once-a-second
        # state poll kept resetting a real percentage to indeterminate.
        self._last_measured = 0.0

        # Secondary actions, deliberately quiet and never duplicating the
        # primary — Start/Stop/Open are whatever the primary currently is.
        specs: List[Tuple[str, str, Callable[[], None]]] = [
            ("stop", "Stop", lambda: self.api.stop()),
            ("repair", "Repair", lambda: self.api.repair()),
            ("uninstall", "Uninstall", lambda: self.api.uninstall()),
        ]
        bw, bh, gap = m.px(94), m.px(30), m.px(10)
        total = len(specs) * bw + (len(specs) - 1) * gap
        sx, sy = (m.width - total) // 2, m.px(440)
        self.secondary: Dict[str, ctk.CTkButton] = {}
        for i, (key, label, command) in enumerate(specs):
            bx = sx + i * (bw + gap)
            self.secondary[key] = ctk.CTkButton(
                self,
                text=label,
                width=bw,
                height=bh,
                corner_radius=bh // 2,
                font=self.font_small,
                fg_color=self.p.surface,
                hover_color=self.p.surface_raised,
                text_color=self.p.text_dim,
                text_color_disabled=self.p.text_faint,
                border_width=1,
                border_color=self.p.hairline,
                bg_color=self.p.base,
                command=command,
            )
            self.secondary[key].place(x=bx, y=sy)

    def _build_footer(self) -> None:
        m = self.m
        version = (self.version or "").strip()
        label = f"Version {version}" if version.lower() not in self._UNVERSIONED else ""
        self._text(
            m.pad, m.height - m.px(24), label, self.font_small, self.p.text_faint, "w"
        )
        # The log is not on screen any more, so there has to be a way to reach
        # it when an install fails.
        self.log_item = self._link(
            m.width - m.pad,
            m.height - m.px(24),
            "Open log",
            self._on_open_log,
            anchor="e",
        )

    def _link(self, x, y, text, command, anchor="center") -> int:
        """Clickable text. Brightens on hover and shows a hand cursor.

        Canvas text rather than a widget: a link has no surface of its own, so
        a CTkButton with a transparent fill would still be a rectangle with a
        hover fill. This is the same treatment `Open log` always had.
        """
        item = self._text(x, y, text, self.font_small, self.p.text_faint, anchor)

        def hover(on: bool) -> None:
            self.canvas.itemconfigure(
                item, fill=self.p.text_dim if on else self.p.text_faint
            )
            try:
                self.canvas.configure(cursor="hand2" if on else "")
            except Exception:
                pass

        self.canvas.tag_bind(item, "<Button-1>", lambda _e: command())
        self.canvas.tag_bind(item, "<Enter>", lambda _e: hover(True))
        self.canvas.tag_bind(item, "<Leave>", lambda _e: hover(False))
        return item

    # ── Polling ─────────────────────────────────────────────────────────

    def _start_polling(self) -> None:
        threading.Thread(target=self._state_loop, daemon=True).start()
        self.after(OUTPUT_TICK_MS, self._tick)

    def _state_loop(self) -> None:
        """Poll install/run state off the UI thread. See module docstring."""
        while not self._stopping.is_set():
            try:
                self._state_q.put(self.api.get_state())
            except Exception:
                pass
            self._stopping.wait(STATE_TICK_S)

    def _tick(self) -> None:
        if not self._alive:
            return
        try:
            out = self.api.drain_output()
        except Exception:
            out = None
        if out:
            # The lines are not displayed; only the most recent meaningful one
            # becomes the status. The full output is in craftbot.log.
            lines = out.get("lines") or []
            if lines:
                latest = _last_meaningful_line("".join(lines))
                if latest:
                    self._set_status(latest)
            progress = out.get("progress")
            if progress:
                self._show_progress(progress.get("read", 0), progress.get("total"))

        latest_state = None
        while True:
            try:
                latest_state = self._state_q.get_nowait()
            except queue.Empty:
                break
        if latest_state is not None:
            self._apply_state(latest_state)

        self.after(OUTPUT_TICK_MS, self._tick)

    # ── State -> UI ─────────────────────────────────────────────────────

    def _apply_state(self, s: Dict) -> None:
        self._state = s
        state = s.get("state", "not_installed")
        busy = bool(s.get("worker_busy"))

        # "Starting" is the window between the agent's process existing and it
        # actually serving. Treating it as Running sent people to a browser
        # tab that was not up yet — see WizardAPI._agent_ready().
        starting = state == "installed_starting"
        running = state in ("installed_running", "running_uninstalled")
        installed = state in (
            "installed_running",
            "installed_stopped",
            "installed_starting",
        )

        # While busy the status line belongs to the running stage, which
        # _tick() is already writing there.
        if not busy:
            if starting:
                detail = (s.get("detail") or "").strip()
                self._set_status(
                    f"Starting · {detail}" if detail else "Starting CraftBot…",
                    self.p.amber,
                )
            elif running:
                self._set_status(
                    f"Running · PID {s['pid']}" if s.get("pid") else "Running",
                    self.p.green,
                )
            elif state == "installed_stopped":
                self._set_status("Installed · not running", self.p.amber)
            else:
                self._set_status("Not installed")

        if starting:
            label, action = "Starting…", None
        elif state == "installed_running":
            label, action = "Open CraftBot", self._on_open
        elif state == "installed_stopped":
            label, action = "Start CraftBot", lambda: self.api.start()
        else:
            label, action = "Install CraftBot", self._on_install
        self._primary_action = action
        # Offering "Open CraftBot" mid-boot is the whole bug: the click
        # succeeds and the browser shows nothing.
        held = busy or starting
        self.btn_primary.configure(
            text="Working…" if busy else label,
            state="disabled" if held else "normal",
            fg_color=self._primary_busy_fill if held else self.p.accent,
        )

        # Stop stays available while starting, so a boot that hangs can still
        # be cancelled.
        enabled = {
            "stop": running or starting,
            "repair": installed,
            "uninstall": installed,
        }
        for key, button in self.secondary.items():
            on = enabled[key] and not busy
            button.configure(state="normal" if on else "disabled")

        # Choosing where to install is meaningless once it is installed.
        self._set_change_enabled(not installed and not busy)

        # Any busy stage gets a bar; a measured download upgrades it to a
        # real percentage in _show_progress().
        # ...but never over the top of a live download. MEASURED_GRACE_S
        # after the last byte count, assume that stage is done and go back to
        # an indeterminate bar.
        if busy or starting:
            if time.monotonic() - self._last_measured > MEASURED_GRACE_S:
                self._show_working()
        elif self._progress_shown:
            self._hide_progress()

    # ── Progress ────────────────────────────────────────────────────────

    def _show_progress(self, read: int, total: Optional[int]) -> None:
        """A measured download: exact bytes, exact bar."""
        self._place_bar()
        mb = 1024 * 1024
        if total:
            self._last_measured = time.monotonic()
            self._set_progress_mode("determinate")
            self.progress.set(max(0.0, min(1.0, read / total)))
            self._set_status(f"Downloading… {read / mb:.0f} of {total / mb:.0f} MB")
        else:
            # Unknown length: a moving bar is more honest than a fabricated
            # percentage.
            self._set_progress_mode("indeterminate")
            self._set_status(f"Downloading… {read / mb:.0f} MB")

    def _show_working(self) -> None:
        """Busy with nothing measurable — npm, pip resolution, Playwright.

        Without this the window is completely still for minutes at a time and
        reads as hung. This is where the "something is happening" signal lives
        now that the mark is static.
        """
        self._place_bar()
        self._set_progress_mode("indeterminate")

    def _place_bar(self) -> None:
        if not self._progress_shown:
            self.progress.place(x=self._bar_pos[0], y=self._bar_pos[1])
            self._progress_shown = True

    def _set_progress_mode(self, mode: str) -> None:
        """Switch the bar between measured and indeterminate.

        CTkProgressBar drives indeterminate motion from its own timer, so the
        old mode has to be stopped before the new one is set — otherwise the
        animation keeps running underneath a determinate value.
        """
        if mode == self._progress_mode:
            return
        if self._progress_mode == "indeterminate":
            self.progress.stop()
        self.progress.configure(mode=mode)
        self._progress_mode = mode
        if mode == "indeterminate":
            self.progress.start()
        else:
            self.progress.set(0)

    def _hide_progress(self) -> None:
        self._set_progress_mode("determinate")
        self.progress.place_forget()
        self.progress.set(0)
        self._progress_shown = False

    # ── Actions ─────────────────────────────────────────────────────────

    def _on_primary(self) -> None:
        if self._primary_action:
            self._primary_action()

    def _on_install(self) -> None:
        self._set_status("Preparing…")
        self.api.install(self._target_dir or self.api.get_default_install_location())

    def _on_open(self) -> None:
        self.api.open_in_browser()

    def _on_open_log(self) -> None:
        """Hand the log to the OS rather than rendering it.

        With no panel on screen this is the only route to the detail when an
        install fails, so it falls back to the installer's own startup trace
        when the agent never got far enough to write craftbot.log.
        """
        import craftbot

        from installer.wizard import _log_path

        path = craftbot.LOG_FILE
        if not os.path.isfile(path):
            path = _log_path()
        if not os.path.isfile(path):
            self._set_status("No log yet", self.p.text_faint)
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606 - opening a log we wrote
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            self._set_status(path, self.p.text_faint)

    def _on_change_location(self) -> None:
        """Ask for a directory using Tk's own chooser.

        Tk maps this to the real shell dialog on each platform — the modern
        Vista-style picker on Windows, NSOpenPanel on macOS, the GTK chooser
        on Linux — so it looks native everywhere with no per-OS code.
        """
        from tkinter import filedialog

        initial = self._target_dir or self.api.get_default_install_location()
        chosen = filedialog.askdirectory(
            parent=self,
            title="Choose where to install CraftBot",
            initialdir=os.path.dirname(initial) or initial,
        )
        if not chosen:
            return  # cancelled — keep the current target
        chosen = os.path.normpath(chosen)
        # If they picked a parent rather than a CraftBot folder, append one so
        # the install does not scatter itself through e.g. Documents.
        if os.path.basename(chosen).lower() != "craftbot":
            chosen = os.path.join(chosen, "CraftBot")
        self._set_target(chosen)

    def _on_close(self) -> None:
        if self._state.get("worker_busy"):
            from tkinter import messagebox

            if not messagebox.askokcancel(
                "CraftBot Setup",
                "Setup is still working. Closing now may leave a partial "
                "install.\n\nClose anyway?",
                parent=self,
            ):
                return
        self._alive = False
        self._stopping.set()
        self.destroy()


def _last_meaningful_line(blob: str) -> str:
    """The last line worth putting on the status line.

    pip and npm emit blank lines, rules and progress noise; showing the raw
    last line would leave the status flickering between fragments.
    """
    for line in reversed(blob.splitlines()):
        text = line.strip()
        if len(text) < 3:
            continue
        if set(text) <= set("-=_─━ *#"):
            continue
        return text[:60]
    return ""


def run(api, version: str = "") -> None:
    """Open the window and block until it closes."""
    ctk.set_appearance_mode("dark")
    try:
        ctk.deactivate_automatic_dpi_awareness()  # see Metrics
    except Exception:
        pass
    InstallerWindow(api, version=version).mainloop()
