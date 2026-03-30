#!/usr/bin/env python3
"""
RC Car Track Timer – sound-only edition.

Place the Mac's microphone at the finish line.
Clap once to start. The RC car's motor sound triggers each lap automatically.
"""

import tkinter as tk
from tkinter import font as tkfont
import numpy as np
import threading
import time
import sounddevice as sd


BG_DARK   = '#1a1a2e'
BG_PANEL  = '#16213e'
BG_ACCENT = '#0f3460'
FG_TEAL   = '#4ecca3'
FG_GOLD   = '#ffd700'
FG_PINK   = '#e84393'
FG_WHITE  = '#ffffff'
FG_GREY   = '#888888'


def _get_input_devices() -> list[tuple[int, str]]:
    """Return list of (device_index, display_name) for all input devices."""
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] > 0:
            name = dev['name']
            devices.append((i, name))
    return devices


class RCTimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RC Car Track Timer")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)

        # Timer state
        self.running      = False
        self.start_time   = None
        self.lap_times: list[float] = []
        self.best_time: float | None = None

        # Audio
        self.audio_level        = 0.0
        self.clap_threshold     = 0.08   # loud clap  → start
        self.car_threshold      = 0.20   # car passing → lap
        self.cooldown           = 2.0    # seconds between lap triggers
        self.last_lap_time      = 0.0
        self.last_clap_time     = 0.0

        # Device selection — None means system default
        self._input_devices  = _get_input_devices()
        self._active_device  = None   # sounddevice index
        self._audio_stop     = threading.Event()
        self._audio_thread   = None

        self._build_ui()
        self._start_audio()
        self._tick()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Title
        tk.Label(self.root, text="RC CAR TRACK TIMER",
                 font=('Helvetica', 26, 'bold'),
                 bg=BG_DARK, fg=FG_GOLD).pack(pady=(18, 6))

        # ── Microphone source selector ──
        dev_row = tk.Frame(self.root, bg=BG_DARK)
        dev_row.pack(pady=(0, 8))

        tk.Label(dev_row, text="Microphone:",
                 font=('Helvetica', 11), bg=BG_DARK, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 8))

        default_label = "System default"
        dev_names = [default_label] + [name for _, name in self._input_devices]
        self._dev_var = tk.StringVar(value=default_label)
        dev_menu = tk.OptionMenu(dev_row, self._dev_var, *dev_names,
                                 command=self._on_device_change)
        dev_menu.config(bg=BG_ACCENT, fg=FG_WHITE, font=('Helvetica', 11),
                        highlightthickness=0, relief=tk.FLAT,
                        activebackground='#1a3a5e', activeforeground=FG_WHITE,
                        cursor='hand2', width=38)
        dev_menu['menu'].config(bg=BG_ACCENT, fg=FG_WHITE,
                                font=('Helvetica', 11),
                                activebackground=FG_TEAL,
                                activeforeground='black')
        dev_menu.pack(side=tk.LEFT)

        # ── Top row: current time + best time ──
        top = tk.Frame(self.root, bg=BG_DARK)
        top.pack(padx=20, pady=(0, 10), fill=tk.X)

        # Current time
        cur = tk.Frame(top, bg=BG_PANEL, relief=tk.RAISED, bd=2)
        cur.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 10))
        tk.Label(cur, text="CURRENT LAP",
                 font=('Helvetica', 14, 'bold'), bg=BG_PANEL, fg=FG_TEAL
                 ).pack(pady=(14, 4))
        self.time_display = tk.Label(cur, text="00:00.00",
                                     font=('Courier', 64, 'bold'),
                                     bg=BG_PANEL, fg=FG_WHITE)
        self.time_display.pack(pady=(0, 14))

        # Best time
        best = tk.Frame(top, bg=BG_ACCENT, relief=tk.RAISED, bd=2)
        best.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        tk.Label(best, text="BEST TIME",
                 font=('Helvetica', 14, 'bold'), bg=BG_ACCENT, fg=FG_GOLD
                 ).pack(pady=(14, 4))
        self.best_display = tk.Label(best, text="--:--.--",
                                     font=('Courier', 64, 'bold'),
                                     bg=BG_ACCENT, fg=FG_GOLD)
        self.best_display.pack(pady=(0, 14))

        # ── Status ──
        self.status_label = tk.Label(self.root, text="READY  –  clap to start!",
                                     font=('Helvetica', 18, 'bold'),
                                     bg=BG_DARK, fg=FG_GOLD)
        self.status_label.pack(pady=(0, 10))

        # ── Buttons ──
        btn_row = tk.Frame(self.root, bg=BG_DARK)
        btn_row.pack(pady=(0, 12))

        self.start_btn = tk.Button(btn_row, text="START\n(or clap!)",
                                   command=self.manual_start,
                                   font=('Helvetica', 15, 'bold'),
                                   bg=FG_TEAL, fg='black',
                                   width=12, height=2,
                                   relief=tk.RAISED, cursor='hand2')
        self.start_btn.grid(row=0, column=0, padx=8)

        self.stop_btn = tk.Button(btn_row, text="STOP\n& Record",
                                  command=self.manual_stop,
                                  font=('Helvetica', 15, 'bold'),
                                  bg=FG_PINK, fg='white',
                                  width=12, height=2,
                                  relief=tk.RAISED, cursor='hand2',
                                  state=tk.DISABLED)
        self.stop_btn.grid(row=0, column=1, padx=8)

        tk.Button(btn_row, text="RESET ALL",
                  command=self.reset_all,
                  font=('Helvetica', 13), bg='#444444', fg='white',
                  width=12, height=2,
                  relief=tk.RAISED, cursor='hand2'
                  ).grid(row=0, column=2, padx=8)

        # ── Mic bar + threshold ──
        mic_frame = tk.Frame(self.root, bg=BG_DARK)
        mic_frame.pack(padx=20, pady=(0, 8), fill=tk.X)

        tk.Label(mic_frame, text="Mic:", font=('Helvetica', 11),
                 bg=BG_DARK, fg=FG_GREY).pack(side=tk.LEFT, padx=(0, 8))

        self.mic_canvas = tk.Canvas(mic_frame, height=22, bg='#2a2a2a',
                                    highlightthickness=1,
                                    highlightbackground='#555555')
        self.mic_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Car-sound threshold slider
        thr_row = tk.Frame(self.root, bg=BG_DARK)
        thr_row.pack(padx=20, pady=(0, 12), fill=tk.X)

        tk.Label(thr_row, text="Car sound threshold:",
                 font=('Helvetica', 11), bg=BG_DARK, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 8))

        self._thr_var = tk.DoubleVar(value=self.car_threshold)
        tk.Scale(thr_row, variable=self._thr_var, from_=0.05, to=1.0,
                 resolution=0.01, orient=tk.HORIZONTAL,
                 command=lambda v: setattr(self, 'car_threshold', float(v)),
                 length=340, bg=BG_DARK, fg='#aaaaaa',
                 troughcolor='#333333', highlightthickness=0,
                 showvalue=True, font=('Helvetica', 10)
                 ).pack(side=tk.LEFT)

        tk.Label(thr_row,
                 text="← set so gold line aligns with car-passing sound",
                 font=('Helvetica', 10, 'italic'), bg=BG_DARK, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(10, 0))

        # ── Lap list ──
        lap_outer = tk.Frame(self.root, bg=BG_PANEL, relief=tk.RAISED, bd=2)
        lap_outer.pack(padx=20, pady=(0, 20), fill=tk.BOTH, expand=True)

        tk.Label(lap_outer, text="LAP TIMES",
                 font=('Helvetica', 14, 'bold'), bg=BG_PANEL, fg=FG_TEAL
                 ).pack(pady=(10, 4))

        inner = tk.Frame(lap_outer, bg=BG_PANEL)
        inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 10))

        sb = tk.Scrollbar(inner)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lap_list = tk.Listbox(inner, yscrollcommand=sb.set,
                                   bg='#0a0a1a', fg=FG_WHITE,
                                   font=('Courier', 20),
                                   selectbackground=FG_TEAL,
                                   selectforeground='black',
                                   relief=tk.FLAT, highlightthickness=0)
        self.lap_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lap_list.yview)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _on_device_change(self, choice: str):
        """Called when the user picks a different microphone."""
        if choice == "System default":
            self._active_device = None
        else:
            for idx, name in self._input_devices:
                if name == choice:
                    self._active_device = idx
                    break
        # Restart the audio stream on the new device
        self._audio_stop.set()
        if self._audio_thread:
            self._audio_thread.join(timeout=2)
        self._audio_stop.clear()
        self._start_audio()

    def _start_audio(self):
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

    def _audio_loop(self):
        device = self._active_device
        try:
            def callback(indata, _frames, _time, _status):
                level = float(np.max(np.abs(indata)))
                self.audio_level = level
                now = time.time()

                # Clap → start (only when stopped)
                if (not self.running
                        and level > self.clap_threshold
                        and now - self.last_clap_time > 1.5):
                    self.last_clap_time = now
                    self.root.after(0, self.manual_start)

                # Car sound → lap (only when running)
                elif (self.running
                        and level > self.car_threshold
                        and now - self.last_lap_time > self.cooldown):
                    self.last_lap_time = now
                    self.root.after(0, self._record_lap)

            with sd.InputStream(callback=callback, channels=1,
                                samplerate=44100, blocksize=512,
                                device=device):
                while not self._audio_stop.is_set():
                    time.sleep(0.05)
        except Exception as exc:
            print(f"Audio error (device={device}): {exc}")

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def manual_start(self):
        if not self.running:
            self.running    = True
            self.start_time = time.time()
            self.last_lap_time = time.time()   # ignore sound right at start
            self.status_label.config(text="RACING!", fg=FG_TEAL)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)

    def manual_stop(self):
        if self.running:
            self._record_lap()
            self.running = False
            self.status_label.config(text="READY  –  clap to start!", fg=FG_GOLD)
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _record_lap(self):
        if self.start_time is None:
            return
        lap = time.time() - self.start_time
        self.lap_times.append(lap)

        is_best = self.best_time is None or lap < self.best_time
        if is_best:
            self.best_time = lap
            self.best_display.config(text=self._fmt(lap))

        n      = len(self.lap_times)
        marker = "  ★ BEST!" if is_best else ""
        self.lap_list.insert(tk.END, f"  Lap {n:2d}    {self._fmt(lap)}{marker}")
        self.lap_list.see(tk.END)

        self.start_time = time.time()
        self.time_display.config(fg=FG_TEAL)
        self.root.after(400, lambda: self.time_display.config(fg=FG_WHITE))

    def reset_all(self):
        self.running    = False
        self.start_time = None
        self.lap_times  = []
        self.best_time  = None
        self.last_lap_time = 0.0
        self.time_display.config(text="00:00.00", fg=FG_WHITE)
        self.best_display.config(text="--:--.--")
        self.status_label.config(text="READY  –  clap to start!", fg=FG_GOLD)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.lap_list.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Display loop
    # ------------------------------------------------------------------

    def _tick(self):
        # Update running timer
        if self.running and self.start_time:
            self.time_display.config(text=self._fmt(time.time() - self.start_time))

        # Mic level bar
        c = self.mic_canvas
        c.update_idletasks()
        w = c.winfo_width() or 600
        c.delete('all')

        level  = self.audio_level
        fill_w = int(min(level, 1.0) * w)
        if fill_w > 0:
            if level >= self.car_threshold:
                colour = '#ff4444'
            elif level >= self.clap_threshold:
                colour = FG_GOLD
            else:
                colour = FG_TEAL
            c.create_rectangle(0, 0, fill_w, 22, fill=colour, outline='')

        # White tick = clap threshold
        cx = int(self.clap_threshold * w)
        c.create_line(cx, 0, cx, 22, fill='white', width=2)

        # Gold tick = car threshold
        tx = int(self.car_threshold * w)
        c.create_line(tx, 0, tx, 22, fill=FG_GOLD, width=3)

        self.root.after(33, self._tick)

    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(s: float) -> str:
        return f"{int(s//60):02d}:{int(s%60):02d}.{int((s%1)*100):02d}"


def main():
    root = tk.Tk()
    root.geometry("780x720")
    app  = RCTimerApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == '__main__':
    main()
