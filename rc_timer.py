#!/usr/bin/env python3
"""
RC Car Track Timer – F1 edition.

Place the Mac's microphone at the finish line.
Clap once to start. The RC car's motor sound triggers each lap.

Keys:
  F / F11   toggle fullscreen
  Escape    exit fullscreen
"""

import tkinter as tk
import numpy as np
import threading
import time
import sounddevice as sd


# ── F1 colour palette ────────────────────────────────────────────────
BG          = '#000000'   # pure black
BG_PANEL    = '#111111'   # dark panel
BG_BEST     = '#1e003a'   # deep purple (fastest-lap panel)
FG_RED      = '#e8002d'   # F1 red
FG_WHITE    = '#ffffff'
FG_SILVER   = '#c0c0c0'
FG_GOLD     = '#ffd700'
FG_PURPLE   = '#cc00ff'   # fastest-lap purple
FG_GREY     = '#555555'
FG_DIMGREY  = '#333333'


def _get_input_devices() -> list[tuple[int, str]]:
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_input_channels'] > 0:
            devices.append((i, dev['name']))
    return devices


class RCTimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RC Car Track Timer")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self._fullscreen = False

        # Timer state
        self.running    = False
        self.start_time = None
        self.lap_times: list[float] = []
        self.best_time: float | None = None

        # Audio
        self.audio_level    = 0.0
        self.clap_threshold = 0.08
        self.car_threshold  = 0.20
        self.cooldown       = 2.0
        self.last_lap_time  = 0.0
        self.last_clap_time = 0.0

        self._input_devices = _get_input_devices()
        self._active_device = None
        self._audio_stop    = threading.Event()
        self._audio_thread  = None

        self._build_ui()
        self._bind_keys()
        self._start_audio()
        self._tick()

    # ------------------------------------------------------------------
    # Keyboard / fullscreen
    # ------------------------------------------------------------------

    def _bind_keys(self):
        self.root.bind('<F11>', lambda _e: self._toggle_fullscreen())
        self.root.bind('<f>',   lambda _e: self._toggle_fullscreen())
        self.root.bind('<Escape>', lambda _e: self._exit_fullscreen())

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes('-fullscreen', self._fullscreen)
        icon = '✕  EXIT FULL' if self._fullscreen else '⛶  FULLSCREEN'
        self._fs_btn.config(text=icon)

    def _exit_fullscreen(self):
        if self._fullscreen:
            self._fullscreen = False
            self.root.attributes('-fullscreen', False)
            self._fs_btn.config(text='⛶  FULLSCREEN')

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Header bar ──────────────────────────────────────────────
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill=tk.X, padx=0, pady=0)

        tk.Label(header, text="RC CAR TRACK TIMER",
                 font=('Impact', 32), bg=BG, fg=FG_WHITE
                 ).pack(side=tk.LEFT, padx=20, pady=(14, 0))

        self._fs_btn = tk.Button(
            header, text='⛶  FULLSCREEN',
            command=self._toggle_fullscreen,
            font=('Helvetica', 11), bg=FG_DIMGREY, fg=FG_SILVER,
            relief=tk.FLAT, cursor='hand2', padx=10, pady=4,
            activebackground='#444444', activeforeground=FG_WHITE
        )
        self._fs_btn.pack(side=tk.RIGHT, padx=16, pady=(14, 0))

        # Red F1 stripe
        tk.Frame(self.root, bg=FG_RED, height=4).pack(fill=tk.X)

        # ── Microphone row ──────────────────────────────────────────
        mic_row = tk.Frame(self.root, bg=BG)
        mic_row.pack(fill=tk.X, padx=20, pady=(10, 2))

        tk.Label(mic_row, text="MIC",
                 font=('Helvetica', 10, 'bold'), bg=BG, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 8))

        default_label = "System default"
        dev_names = [default_label] + [n for _, n in self._input_devices]
        self._dev_var = tk.StringVar(value=default_label)
        dev_menu = tk.OptionMenu(mic_row, self._dev_var, *dev_names,
                                 command=self._on_device_change)
        dev_menu.config(bg='#1a1a1a', fg=FG_SILVER,
                        font=('Helvetica', 11), highlightthickness=0,
                        relief=tk.FLAT, activebackground='#2a2a2a',
                        activeforeground=FG_WHITE, cursor='hand2', width=38)
        dev_menu['menu'].config(bg='#1a1a1a', fg=FG_SILVER,
                                font=('Helvetica', 11),
                                activebackground=FG_RED,
                                activeforeground=FG_WHITE)
        dev_menu.pack(side=tk.LEFT)

        self._dev_status = tk.Label(mic_row, text="",
                                    font=('Helvetica', 10, 'italic'),
                                    bg=BG, fg=FG_GREY)
        self._dev_status.pack(side=tk.LEFT, padx=(12, 0))

        # ── Timers row ──────────────────────────────────────────────
        timers = tk.Frame(self.root, bg=BG)
        timers.pack(fill=tk.X, padx=20, pady=(12, 0))
        timers.columnconfigure(0, weight=1)
        timers.columnconfigure(1, weight=1)

        # Current lap — left panel with red top stripe
        cur_wrap = tk.Frame(timers, bg=FG_RED)
        cur_wrap.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        cur_inner = tk.Frame(cur_wrap, bg=BG_PANEL)
        cur_inner.pack(fill=tk.BOTH, expand=True, padx=0, pady=(4, 0))
        tk.Label(cur_inner, text="CURRENT LAP",
                 font=('Helvetica', 13, 'bold'), bg=BG_PANEL, fg=FG_RED
                 ).pack(pady=(10, 2))
        self.time_display = tk.Label(cur_inner, text="00:00.00",
                                     font=('Courier', 72, 'bold'),
                                     bg=BG_PANEL, fg=FG_WHITE)
        self.time_display.pack(pady=(0, 12))

        # Best time — right panel with purple top stripe
        best_wrap = tk.Frame(timers, bg=FG_PURPLE)
        best_wrap.grid(row=0, column=1, sticky='nsew')
        best_inner = tk.Frame(best_wrap, bg=BG_BEST)
        best_inner.pack(fill=tk.BOTH, expand=True, padx=0, pady=(4, 0))
        tk.Label(best_inner, text="FASTEST LAP",
                 font=('Helvetica', 13, 'bold'), bg=BG_BEST, fg=FG_PURPLE
                 ).pack(pady=(10, 2))
        self.best_display = tk.Label(best_inner, text="--:--.--",
                                     font=('Courier', 72, 'bold'),
                                     bg=BG_BEST, fg=FG_PURPLE)
        self.best_display.pack(pady=(0, 12))

        # ── Status ──────────────────────────────────────────────────
        self.status_label = tk.Label(
            self.root, text="READY  —  CLAP TO START",
            font=('Impact', 22), bg=BG, fg=FG_SILVER
        )
        self.status_label.pack(pady=(12, 8))

        # ── Buttons ─────────────────────────────────────────────────
        btn_row = tk.Frame(self.root, bg=BG)
        btn_row.pack(pady=(0, 12))

        self.start_btn = tk.Button(
            btn_row, text="START  (or clap!)",
            command=self.manual_start,
            font=('Helvetica', 14, 'bold'), bg=FG_RED, fg=FG_WHITE,
            width=18, height=2, relief=tk.FLAT, cursor='hand2',
            activebackground='#ff3355', activeforeground=FG_WHITE
        )
        self.start_btn.grid(row=0, column=0, padx=6)

        self.stop_btn = tk.Button(
            btn_row, text="STOP  & Record",
            command=self.manual_stop,
            font=('Helvetica', 14, 'bold'), bg='#2a2a2a', fg=FG_SILVER,
            width=18, height=2, relief=tk.FLAT, cursor='hand2',
            activebackground='#3a3a3a', activeforeground=FG_WHITE,
            state=tk.DISABLED
        )
        self.stop_btn.grid(row=0, column=1, padx=6)

        tk.Button(
            btn_row, text="RESET ALL",
            command=self.reset_all,
            font=('Helvetica', 14, 'bold'), bg='#1a1a1a', fg=FG_GREY,
            width=14, height=2, relief=tk.FLAT, cursor='hand2',
            activebackground='#2a2a2a', activeforeground=FG_WHITE
        ).grid(row=0, column=2, padx=6)

        # ── Mic level bar ────────────────────────────────────────────
        mic_bar_row = tk.Frame(self.root, bg=BG)
        mic_bar_row.pack(fill=tk.X, padx=20, pady=(0, 4))

        tk.Label(mic_bar_row, text="LEVEL",
                 font=('Helvetica', 9, 'bold'), bg=BG, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 8))

        self.mic_canvas = tk.Canvas(mic_bar_row, height=20, bg='#1a1a1a',
                                    highlightthickness=0)
        self.mic_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ── Threshold slider ─────────────────────────────────────────
        thr_row = tk.Frame(self.root, bg=BG)
        thr_row.pack(fill=tk.X, padx=20, pady=(0, 12))

        tk.Label(thr_row, text="CAR THRESHOLD",
                 font=('Helvetica', 9, 'bold'), bg=BG, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 8))

        self._thr_var = tk.DoubleVar(value=self.car_threshold)
        tk.Scale(thr_row, variable=self._thr_var, from_=0.05, to=1.0,
                 resolution=0.01, orient=tk.HORIZONTAL,
                 command=lambda v: setattr(self, 'car_threshold', float(v)),
                 length=360, bg=BG, fg=FG_GREY,
                 troughcolor=FG_DIMGREY, highlightthickness=0,
                 showvalue=True, font=('Helvetica', 9),
                 activebackground=FG_RED
                 ).pack(side=tk.LEFT)

        tk.Label(thr_row,
                 text="← red bar = car detected",
                 font=('Helvetica', 9, 'italic'), bg=BG, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(10, 0))

        # ── Lap list ─────────────────────────────────────────────────
        # Header row
        hdr = tk.Frame(self.root, bg='#1a1a1a')
        hdr.pack(fill=tk.X, padx=20)
        tk.Label(hdr, text="  LAP", font=('Helvetica', 11, 'bold'),
                 bg='#1a1a1a', fg=FG_GREY, width=6, anchor='w'
                 ).pack(side=tk.LEFT)
        tk.Label(hdr, text="TIME", font=('Helvetica', 11, 'bold'),
                 bg='#1a1a1a', fg=FG_GREY, width=12, anchor='w'
                 ).pack(side=tk.LEFT)
        tk.Label(hdr, text="GAP TO BEST", font=('Helvetica', 11, 'bold'),
                 bg='#1a1a1a', fg=FG_GREY
                 ).pack(side=tk.LEFT)

        # List
        lap_frame = tk.Frame(self.root, bg=BG)
        lap_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 16))

        sb = tk.Scrollbar(lap_frame, bg='#1a1a1a', troughcolor=BG)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lap_list = tk.Listbox(
            lap_frame, yscrollcommand=sb.set,
            bg=BG_PANEL, fg=FG_SILVER,
            font=('Courier', 18),
            selectbackground=FG_RED, selectforeground=FG_WHITE,
            relief=tk.FLAT, highlightthickness=0,
            borderwidth=0
        )
        self.lap_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lap_list.yview)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _on_device_change(self, choice: str):
        if choice == "System default":
            self._active_device = None
        else:
            for idx, name in self._input_devices:
                if name == choice:
                    self._active_device = idx
                    break
        self._dev_status.config(text="switching…", fg=FG_GREY)
        threading.Thread(target=self._restart_audio, daemon=True).start()

    def _restart_audio(self):
        self._audio_stop.set()
        if self._audio_thread:
            self._audio_thread.join(timeout=3)
        self._audio_stop.clear()
        self._start_audio()

    def _start_audio(self):
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._audio_thread.start()

    def _audio_loop(self):
        device = self._active_device
        try:
            if device is not None:
                info = sd.query_devices(device, 'input')
            else:
                info = sd.query_devices(kind='input')
            samplerate = int(info['default_samplerate'])
            dev_name   = info['name']

            self.root.after(0, lambda: self._dev_status.config(
                text=f"● {dev_name}  ({samplerate} Hz)", fg=FG_GREY))

            def callback(indata, _frames, _time, _status):
                level = float(np.max(np.abs(indata)))
                self.audio_level = level
                now = time.time()
                if (not self.running
                        and level > self.clap_threshold
                        and now - self.last_clap_time > 1.5):
                    self.last_clap_time = now
                    self.root.after(0, self.manual_start)
                elif (self.running
                        and level > self.car_threshold
                        and now - self.last_lap_time > self.cooldown):
                    self.last_lap_time = now
                    self.root.after(0, self._record_lap)

            with sd.InputStream(callback=callback, channels=1,
                                samplerate=samplerate, blocksize=512,
                                device=device):
                while not self._audio_stop.is_set():
                    time.sleep(0.05)

        except Exception as exc:
            msg = str(exc)
            self.root.after(0, lambda: self._dev_status.config(
                text=f"Error: {msg}", fg=FG_RED))
            print(f"Audio error (device={device}): {exc}")

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def manual_start(self):
        if not self.running:
            self.running       = True
            self.start_time    = time.time()
            self.last_lap_time = time.time()
            self.status_label.config(text="GO!  GO!  GO!", fg=FG_RED)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL, bg=FG_RED, fg=FG_WHITE)

    def manual_stop(self):
        if self.running:
            self._record_lap()
            self.running = False
            self.status_label.config(text="READY  —  CLAP TO START",
                                     fg=FG_SILVER)
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED, bg='#2a2a2a', fg=FG_SILVER)

    def _record_lap(self):
        if self.start_time is None:
            return
        lap    = time.time() - self.start_time
        self.lap_times.append(lap)

        is_best = self.best_time is None or lap < self.best_time
        if is_best:
            self.best_time = lap
            self.best_display.config(text=self._fmt(lap))

        n   = len(self.lap_times)
        gap = f"+{self._fmt(lap - self.best_time)}" if (
            self.best_time and lap > self.best_time) else "FASTEST"
        entry = f"  {n:2d}      {self._fmt(lap)}    {gap}"
        self.lap_list.insert(tk.END, entry)

        # Colour fastest-lap row purple, rest white
        for i in range(self.lap_list.size()):
            if "FASTEST" in self.lap_list.get(i):
                self.lap_list.itemconfig(i, fg=FG_PURPLE)
            else:
                self.lap_list.itemconfig(i, fg=FG_SILVER)

        self.lap_list.see(tk.END)
        self.start_time = time.time()

        # Flash
        flash_col = FG_PURPLE if is_best else FG_RED
        self.time_display.config(fg=flash_col)
        self.root.after(400, lambda: self.time_display.config(fg=FG_WHITE))

    def reset_all(self):
        self.running       = False
        self.start_time    = None
        self.lap_times     = []
        self.best_time     = None
        self.last_lap_time = 0.0
        self.time_display.config(text="00:00.00", fg=FG_WHITE)
        self.best_display.config(text="--:--.--")
        self.status_label.config(text="READY  —  CLAP TO START", fg=FG_SILVER)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED, bg='#2a2a2a', fg=FG_SILVER)
        self.lap_list.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Display loop
    # ------------------------------------------------------------------

    def _tick(self):
        if self.running and self.start_time:
            self.time_display.config(text=self._fmt(time.time() - self.start_time))

        c = self.mic_canvas
        c.update_idletasks()
        w = c.winfo_width() or 600
        c.delete('all')

        # Background segments (timing-tower style)
        seg = max(1, w // 40)
        for i in range(0, w, seg * 2):
            c.create_rectangle(i, 0, i + seg, 20, fill='#1a1a1a', outline='')

        level  = self.audio_level
        fill_w = int(min(level, 1.0) * w)
        if fill_w > 0:
            if level >= self.car_threshold:
                colour = FG_RED
            elif level >= self.clap_threshold:
                colour = FG_GOLD
            else:
                colour = '#444444'
            c.create_rectangle(0, 2, fill_w, 18, fill=colour, outline='')

        # Clap threshold — white tick
        cx = int(self.clap_threshold * w)
        c.create_line(cx, 0, cx, 20, fill=FG_WHITE, width=2)

        # Car threshold — red tick
        tx = int(self.car_threshold * w)
        c.create_line(tx, 0, tx, 20, fill=FG_RED, width=3)

        self.root.after(33, self._tick)

    # ------------------------------------------------------------------

    @staticmethod
    def _fmt(s: float) -> str:
        return f"{int(s//60):02d}:{int(s%60):02d}.{int((s%1)*100):02d}"


def main():
    root = tk.Tk()
    root.geometry("860x780")
    RCTimerApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
