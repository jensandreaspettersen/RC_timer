#!/usr/bin/env python3
"""
RC Car Track Timer
A fun track timer for kids using webcam and microphone.

Usage:
  python3 rc_timer.py

Controls:
  - Drag the checkered finish line up/down on the camera feed
  - Clap or press START to begin timing
  - Lap trigger mode:
      Motion – car crossing the finish line (webcam) records a lap
      Sound  – car passing the microphone (placed at finish line) records a lap
  - Press STOP to manually record a lap and stop
  - Press RESET ALL to clear all times
"""

import tkinter as tk
from tkinter import font as tkfont
import cv2
import numpy as np
import threading
import time
import sys
import sounddevice as sd
from PIL import Image, ImageTk
import queue


CANVAS_W = 560
CANVAS_H = 420
BG_DARK    = '#1a1a2e'
BG_PANEL   = '#16213e'
BG_ACCENT  = '#0f3460'
FG_TEAL    = '#4ecca3'
FG_GOLD    = '#ffd700'
FG_PINK    = '#e84393'
FG_WHITE   = '#ffffff'
FG_GREY    = '#888888'

IS_MAC = sys.platform == 'darwin'


def _open_camera(index: int):
    """Open a camera, preferring AVFoundation on macOS for correct permissions."""
    if IS_MAC:
        cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    else:
        cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def _list_cameras(max_test: int = 5) -> list[int]:
    """Return indices of available cameras."""
    available = []
    for i in range(max_test):
        cap = _open_camera(i)
        if cap.isOpened():
            available.append(i)
            cap.release()
    return available if available else [0]


class RCTimerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RC Car Track Timer")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)

        # --- Timer state ---
        self.running       = False
        self.start_time    = None
        self.current_time  = 0.0
        self.lap_times: list[float] = []
        self.best_time: float | None = None

        # --- Detection ---
        self.line_position      = 0.6    # 0..1 fraction of frame height
        self.detection_cooldown = 2.0    # seconds between car detections
        self.last_detection     = 0.0
        self.motion_threshold   = 30     # pixel-diff threshold (5–100)

        # Sound thresholds (0..1 normalised)
        self.clap_threshold      = 0.08  # clap-to-start
        self.car_sound_threshold = 0.20  # car-passing-mic lap trigger

        # Lap trigger mode: 'motion' or 'sound'
        self.lap_trigger_mode = 'motion'

        # --- Camera ---
        self.cam_index  = 0
        self.cap        = None
        self.frame_queue: queue.Queue[Image.Image] = queue.Queue(maxsize=2)
        self.prev_gray  = None
        self._cam_lock  = threading.Lock()

        # --- Drag state ---
        self.dragging_line = False

        # --- Audio ---
        self.audio_level     = 0.0
        self.last_clap_start = 0.0   # debounce for clap-start

        # Discover cameras before building UI
        self._available_cams = _list_cameras()

        self._build_ui()
        self._switch_camera(self._available_cams[0])
        self._start_audio()
        self._update_display()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        title_font = tkfont.Font(family='Helvetica', size=22, weight='bold')
        tk.Label(
            self.root, text="RC CAR TRACK TIMER",
            font=title_font, bg=BG_DARK, fg=FG_GOLD
        ).pack(pady=(12, 6))

        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        self._build_camera_panel(main)
        self._build_control_panel(main)
        self._build_audio_bar()

    def _build_camera_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, relief=tk.RAISED, bd=2)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        # Header row: label + camera selector
        header = tk.Frame(frame, bg=BG_PANEL)
        header.pack(pady=(8, 4), fill=tk.X, padx=8)

        tk.Label(header, text="CAMERA FEED",
                 font=('Helvetica', 11, 'bold'), bg=BG_PANEL, fg=FG_TEAL
                 ).pack(side=tk.LEFT)

        tk.Label(header, text="  Camera:",
                 font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(20, 2))

        cam_labels = [f"Camera {i}" for i in self._available_cams]
        self._cam_var = tk.StringVar(value=cam_labels[0])
        cam_menu = tk.OptionMenu(header, self._cam_var, *cam_labels,
                                 command=self._on_camera_select)
        cam_menu.config(bg=BG_ACCENT, fg=FG_WHITE, font=('Helvetica', 9),
                        highlightthickness=0, relief=tk.FLAT, cursor='hand2')
        cam_menu['menu'].config(bg=BG_ACCENT, fg=FG_WHITE)
        cam_menu.pack(side=tk.LEFT)

        self.canvas = tk.Canvas(frame, bg='black', width=CANVAS_W, height=CANVAS_H,
                                highlightthickness=0)
        self.canvas.pack(padx=6, pady=(0, 4))
        self.canvas.bind('<Button-1>',        self._on_canvas_click)
        self.canvas.bind('<B1-Motion>',       self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

        # Show "no camera" placeholder text
        self._no_cam_text = self.canvas.create_text(
            CANVAS_W // 2, CANVAS_H // 2,
            text="No camera – grant access in\nSystem Settings > Privacy > Camera\nthen restart the app",
            fill=FG_GREY, font=('Helvetica', 14), justify=tk.CENTER
        )

        tk.Label(frame, text="Drag the finish line to position it",
                 font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY
                 ).pack(pady=(0, 6))

    def _build_control_panel(self, parent):
        frame = tk.Frame(parent, bg=BG_PANEL, relief=tk.RAISED, bd=2, width=300)
        frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(6, 0))
        frame.pack_propagate(False)

        # Current time
        tk.Label(frame, text="CURRENT TIME",
                 font=('Helvetica', 11, 'bold'), bg=BG_PANEL, fg=FG_TEAL
                 ).pack(pady=(14, 2))
        self.time_display = tk.Label(
            frame, text="00:00.00",
            font=('Courier', 38, 'bold'), bg=BG_PANEL, fg=FG_WHITE
        )
        self.time_display.pack()

        self.status_label = tk.Label(
            frame, text="READY",
            font=('Helvetica', 13, 'bold'), bg=BG_PANEL, fg=FG_GOLD
        )
        self.status_label.pack(pady=4)

        # Best time
        best_frame = tk.Frame(frame, bg=BG_ACCENT, relief=tk.SUNKEN, bd=2)
        best_frame.pack(fill=tk.X, padx=10, pady=6)
        tk.Label(best_frame, text="BEST TIME",
                 font=('Helvetica', 10, 'bold'), bg=BG_ACCENT, fg=FG_GOLD
                 ).pack(pady=(6, 2))
        self.best_display = tk.Label(
            best_frame, text="--:--.--",
            font=('Courier', 22, 'bold'), bg=BG_ACCENT, fg=FG_GOLD
        )
        self.best_display.pack(pady=(2, 8))

        # Buttons
        btn_frame = tk.Frame(frame, bg=BG_PANEL)
        btn_frame.pack(pady=6)

        self.start_btn = tk.Button(
            btn_frame, text="START\n(or clap!)",
            command=self.manual_start,
            font=('Helvetica', 12, 'bold'), bg=FG_TEAL, fg='black',
            width=11, height=2, relief=tk.RAISED, cursor='hand2'
        )
        self.start_btn.grid(row=0, column=0, padx=4, pady=4)

        self.stop_btn = tk.Button(
            btn_frame, text="STOP\n& Record",
            command=self.manual_stop,
            font=('Helvetica', 12, 'bold'), bg=FG_PINK, fg='white',
            width=11, height=2, relief=tk.RAISED, cursor='hand2',
            state=tk.DISABLED
        )
        self.stop_btn.grid(row=0, column=1, padx=4, pady=4)

        tk.Button(
            btn_frame, text="RESET ALL",
            command=self.reset_all,
            font=('Helvetica', 10), bg='#444444', fg='white',
            width=25, relief=tk.RAISED, cursor='hand2'
        ).grid(row=1, column=0, columnspan=2, padx=4, pady=4)

        # ---- Lap trigger mode ----
        trigger_frame = tk.LabelFrame(
            frame, text=" Lap Trigger Mode ",
            font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY, labelanchor='n'
        )
        trigger_frame.pack(fill=tk.X, padx=10, pady=(4, 2))

        self._trigger_var = tk.StringVar(value='motion')
        modes = [("Motion  (webcam finish line)", 'motion'),
                 ("Sound   (mic at finish line)",  'sound')]
        for label, val in modes:
            tk.Radiobutton(
                trigger_frame, text=label, variable=self._trigger_var, value=val,
                command=self._on_trigger_mode_change,
                bg=BG_PANEL, fg=FG_WHITE, selectcolor=BG_ACCENT,
                activebackground=BG_PANEL, activeforeground=FG_TEAL,
                font=('Helvetica', 10)
            ).pack(anchor=tk.W, padx=8, pady=2)

        # ---- Sensitivity sliders (shown/hidden by mode) ----
        self._motion_frame = tk.Frame(frame, bg=BG_PANEL)
        self._motion_frame.pack(fill=tk.X, padx=10, pady=(0, 2))
        tk.Label(self._motion_frame, text="Motion sensitivity:",
                 font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY).pack(anchor=tk.W)
        self.motion_var = tk.IntVar(value=self.motion_threshold)
        tk.Scale(
            self._motion_frame, from_=5, to=100, orient=tk.HORIZONTAL,
            variable=self.motion_var, command=self._update_motion_threshold,
            bg=BG_PANEL, fg='#aaaaaa', highlightthickness=0,
            troughcolor='#333333', length=240, showvalue=True
        ).pack()

        self._sound_frame = tk.Frame(frame, bg=BG_PANEL)
        # (packed/unpacked by _on_trigger_mode_change)
        tk.Label(self._sound_frame,
                 text="Car sound threshold:\n(adjust so bar hits red when car passes)",
                 font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY,
                 justify=tk.LEFT).pack(anchor=tk.W)
        self._car_sound_var = tk.DoubleVar(value=self.car_sound_threshold)
        self._car_sound_scale = tk.Scale(
            self._sound_frame, from_=0.05, to=1.0, resolution=0.01,
            orient=tk.HORIZONTAL,
            variable=self._car_sound_var, command=self._update_car_sound_threshold,
            bg=BG_PANEL, fg='#aaaaaa', highlightthickness=0,
            troughcolor='#333333', length=240, showvalue=True
        )
        self._car_sound_scale.pack()

        # Lap times
        lap_frame = tk.LabelFrame(
            frame, text=" LAP TIMES ",
            font=('Helvetica', 10, 'bold'), bg=BG_PANEL, fg=FG_TEAL, labelanchor='n'
        )
        lap_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))

        inner = tk.Frame(lap_frame, bg=BG_PANEL)
        inner.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        sb = tk.Scrollbar(inner)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.lap_listbox = tk.Listbox(
            inner, yscrollcommand=sb.set,
            bg='#0a0a1a', fg=FG_WHITE, font=('Courier', 11),
            selectbackground=FG_TEAL, selectforeground='black',
            relief=tk.FLAT, highlightthickness=0
        )
        self.lap_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.config(command=self.lap_listbox.yview)

    def _build_audio_bar(self):
        bar_frame = tk.Frame(self.root, bg=BG_DARK)
        bar_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        tk.Label(bar_frame, text="Mic level:",
                 font=('Helvetica', 9), bg=BG_DARK, fg=FG_GREY
                 ).pack(side=tk.LEFT, padx=(0, 6))

        self.audio_canvas = tk.Canvas(
            bar_frame, width=280, height=16,
            bg='#333333', highlightthickness=1, highlightbackground='#555555'
        )
        self.audio_canvas.pack(side=tk.LEFT)

        self._audio_hint = tk.Label(
            bar_frame, text="  Clap to start, car sound triggers lap",
            font=('Helvetica', 9, 'italic'), bg=BG_DARK, fg=FG_GREY
        )
        self._audio_hint.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Mode / camera callbacks
    # ------------------------------------------------------------------

    def _on_trigger_mode_change(self):
        mode = self._trigger_var.get()
        self.lap_trigger_mode = mode
        if mode == 'motion':
            self._sound_frame.pack_forget()
            self._motion_frame.pack(fill=tk.X, padx=10, pady=(0, 2),
                                    before=self._sound_frame)
        else:
            self._motion_frame.pack_forget()
            self._sound_frame.pack(fill=tk.X, padx=10, pady=(0, 2))

    def _on_camera_select(self, choice: str):
        idx = int(choice.split()[-1])
        self._switch_camera(idx)

    def _switch_camera(self, index: int):
        with self._cam_lock:
            if self.cap:
                self.cap.release()
                self.cap = None
            self.prev_gray = None
            self.cam_index = index
            cap = _open_camera(index)
            if cap.isOpened():
                self.cap = cap
                if not hasattr(self, '_cam_thread') or not self._cam_thread.is_alive():
                    self._cam_thread = threading.Thread(
                        target=self._camera_loop, daemon=True)
                    self._cam_thread.start()
            else:
                cap.release()

    # ------------------------------------------------------------------
    # Canvas drag handlers
    # ------------------------------------------------------------------

    def _on_canvas_click(self, event):
        line_y = int(self.line_position * CANVAS_H)
        if abs(event.y - line_y) < 18:
            self.dragging_line = True

    def _on_canvas_drag(self, event):
        if self.dragging_line:
            self.line_position = max(0.1, min(0.9, event.y / CANVAS_H))

    def _on_canvas_release(self, _event):
        self.dragging_line = False

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _camera_loop(self):
        while True:
            with self._cam_lock:
                cap = self.cap
            if cap and cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    frame = cv2.flip(frame, 1)
                    self._process_frame(frame)
            time.sleep(0.033)

    def _process_frame(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        line_y = int(self.line_position * h)
        band_h = 22

        car_crossed = False

        if self.lap_trigger_mode == 'motion':
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if self.prev_gray is not None:
                diff = cv2.absdiff(
                    gray[max(0, line_y - band_h): line_y + band_h, :],
                    self.prev_gray[max(0, line_y - band_h): line_y + band_h, :]
                )
                score = float(np.mean(diff))
                now = time.time()
                if (score > self.motion_threshold
                        and self.running
                        and now - self.last_detection > self.detection_cooldown):
                    self.last_detection = now
                    car_crossed = True
                    self.root.after(0, self._car_detected)

            self.prev_gray = gray

        # --- Draw finish line ---
        line_color = (0, 80, 255) if car_crossed else (50, 220, 50)
        sq = 12
        for x in range(0, w, sq):
            col = (255, 255, 255) if (x // sq) % 2 == 0 else (0, 0, 0)
            cv2.rectangle(frame, (x, line_y - 5), (x + sq, line_y + 5), col, -1)
        cv2.line(frame, (0, line_y), (w, line_y), line_color, 2)

        mode_tag = "MOTION" if self.lap_trigger_mode == 'motion' else "SOUND"
        cv2.putText(frame, f"FINISH LINE  [{mode_tag}]", (10, line_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, line_color, 2)

        if car_crossed:
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (0, 255, 120), -1)
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        display = cv2.resize(frame, (CANVAS_W, CANVAS_H))
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        if not self.frame_queue.full():
            self.frame_queue.put(img)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _start_audio(self):
        threading.Thread(target=self._audio_loop, daemon=True).start()

    def _audio_loop(self):
        try:
            def callback(indata, _frames, _time, _status):
                level = float(np.max(np.abs(indata)))
                self.audio_level = level
                now = time.time()

                # Clap-to-start (when timer is NOT running)
                if (level > self.clap_threshold
                        and not self.running
                        and now - self.last_clap_start > 1.5):
                    self.last_clap_start = now
                    self.root.after(0, self.manual_start)
                    return

                # Car sound lap trigger (when timer IS running, sound mode)
                if (self.lap_trigger_mode == 'sound'
                        and self.running
                        and level > self.car_sound_threshold
                        and now - self.last_detection > self.detection_cooldown):
                    self.last_detection = now
                    self.root.after(0, self._car_detected)

            with sd.InputStream(callback=callback, channels=1,
                                samplerate=44100, blocksize=512):
                while True:
                    time.sleep(0.05)
        except Exception as exc:
            print(f"Audio unavailable: {exc}")

    # ------------------------------------------------------------------
    # Timer logic
    # ------------------------------------------------------------------

    def _car_detected(self):
        if self.running:
            self._record_lap()

    def manual_start(self):
        if not self.running:
            self.running    = True
            self.start_time = time.time()
            self.status_label.config(text="RACING!", fg=FG_TEAL)
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)

    def manual_stop(self):
        if self.running:
            self._record_lap()
            self.running = False
            self.status_label.config(text="READY", fg=FG_GOLD)
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)

    def _record_lap(self):
        if self.start_time is None:
            return
        lap_time = time.time() - self.start_time
        self.lap_times.append(lap_time)

        is_best = self.best_time is None or lap_time < self.best_time
        if is_best:
            self.best_time = lap_time
            self.best_display.config(text=self._fmt(lap_time))

        lap_num = len(self.lap_times)
        marker  = "  BEST!" if is_best else ""
        self.lap_listbox.insert(tk.END, f"  Lap {lap_num:2d}:  {self._fmt(lap_time)}{marker}")
        self.lap_listbox.see(tk.END)

        self.start_time = time.time()
        self.time_display.config(fg=FG_TEAL)
        self.root.after(350, lambda: self.time_display.config(fg=FG_WHITE))

    def reset_all(self):
        self.running        = False
        self.start_time     = None
        self.current_time   = 0.0
        self.lap_times      = []
        self.best_time      = None
        self.last_detection = 0.0
        self.time_display.config(text="00:00.00", fg=FG_WHITE)
        self.best_display.config(text="--:--.--")
        self.status_label.config(text="READY", fg=FG_GOLD)
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.lap_listbox.delete(0, tk.END)

    # ------------------------------------------------------------------
    # Display update loop
    # ------------------------------------------------------------------

    def _update_display(self):
        # Timer digits
        if self.running and self.start_time:
            self.current_time = time.time() - self.start_time
            self.time_display.config(text=self._fmt(self.current_time))

        # Camera frame
        if not self.frame_queue.empty():
            img = self.frame_queue.get_nowait()
            self._tk_img = ImageTk.PhotoImage(img)
            self.canvas.delete('all')
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)
        elif self.cap is None or not self.cap.isOpened():
            # Redraw no-camera placeholder
            self.canvas.delete('all')
            self.canvas.create_text(
                CANVAS_W // 2, CANVAS_H // 2,
                text="No camera – grant access in\nSystem Settings > Privacy > Camera\nthen restart the app",
                fill=FG_GREY, font=('Helvetica', 14), justify=tk.CENTER
            )

        # Audio bar — shows two threshold markers
        self.audio_canvas.delete('all')
        bar_w = 280

        # Fill bar proportional to peak level (capped at 1.0)
        ratio   = min(1.0, self.audio_level / 1.0)
        fill_w  = int(ratio * bar_w)
        # Colour: green < clap, yellow < car sound, red >= car sound
        if self.audio_level >= self.car_sound_threshold:
            colour = '#ff4444'
        elif self.audio_level >= self.clap_threshold:
            colour = FG_GOLD
        else:
            colour = FG_TEAL
        if fill_w > 0:
            self.audio_canvas.create_rectangle(0, 0, fill_w, 16,
                                               fill=colour, outline='')

        # Clap threshold marker (white tick)
        clap_x = int(self.clap_threshold * bar_w)
        self.audio_canvas.create_line(clap_x, 0, clap_x, 16, fill='white', width=1)

        # Car sound threshold marker (orange tick) – only in sound mode
        if self.lap_trigger_mode == 'sound':
            car_x = int(self.car_sound_threshold * bar_w)
            self.audio_canvas.create_line(car_x, 0, car_x, 16,
                                          fill=FG_GOLD, width=2)

        self.root.after(33, self._update_display)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_motion_threshold(self, val):
        self.motion_threshold = int(val)

    def _update_car_sound_threshold(self, val):
        self.car_sound_threshold = float(val)

    @staticmethod
    def _fmt(seconds: float) -> str:
        m  = int(seconds // 60)
        s  = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{m:02d}:{s:02d}.{cs:02d}"

    def cleanup(self):
        with self._cam_lock:
            if self.cap:
                self.cap.release()


# ----------------------------------------------------------------------

def main():
    root = tk.Tk()
    app  = RCTimerApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.cleanup(), root.destroy()))
    root.mainloop()


if __name__ == '__main__':
    main()
