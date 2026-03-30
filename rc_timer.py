#!/usr/bin/env python3
"""
RC Car Track Timer
A fun track timer for kids using webcam and microphone.

Usage:
  python3 rc_timer.py

Controls:
  - Drag the checkered finish line up/down on the camera feed
  - Clap or press START to begin timing
  - Car crossing the finish line records a lap
  - Press STOP to manually record a lap and stop
  - Press RESET ALL to clear all times
"""

import tkinter as tk
from tkinter import font as tkfont
import cv2
import numpy as np
import threading
import time
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

        # --- Detection settings ---
        self.line_position      = 0.6    # 0..1 fraction of frame height
        self.detection_cooldown = 2.0    # seconds between car detections
        self.last_detection     = 0.0
        self.motion_threshold   = 30     # pixel-diff threshold (10–100)
        self.sound_threshold    = 0.08   # normalised audio level (0..1)

        # --- Camera ---
        self.cap        = None
        self.frame_queue: queue.Queue[Image.Image] = queue.Queue(maxsize=2)
        self.prev_gray  = None

        # --- Drag state ---
        self.dragging_line = False

        # --- Audio level (updated from audio thread) ---
        self.audio_level = 0.0
        # Debounce clap: ignore clap for 1s after a start
        self.last_clap_start = 0.0

        self._build_ui()
        self._start_camera()
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

        tk.Label(
            frame, text="CAMERA FEED",
            font=('Helvetica', 11, 'bold'), bg=BG_PANEL, fg=FG_TEAL
        ).pack(pady=(8, 4))

        self.canvas = tk.Canvas(frame, bg='black', width=CANVAS_W, height=CANVAS_H,
                                highlightthickness=0)
        self.canvas.pack(padx=6, pady=(0, 4))
        self.canvas.bind('<Button-1>',       self._on_canvas_click)
        self.canvas.bind('<B1-Motion>',      self._on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_canvas_release)

        tk.Label(
            frame, text="Drag the finish line to position it",
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

        # Motion sensitivity
        sens_frame = tk.LabelFrame(
            frame, text=" Motion Sensitivity ",
            font=('Helvetica', 9), bg=BG_PANEL, fg=FG_GREY, labelanchor='n'
        )
        sens_frame.pack(fill=tk.X, padx=10, pady=4)

        self.motion_var = tk.IntVar(value=self.motion_threshold)
        self.motion_scale = tk.Scale(
            sens_frame, from_=5, to=100, orient=tk.HORIZONTAL,
            variable=self.motion_var, command=self._update_motion_threshold,
            bg=BG_PANEL, fg='#aaaaaa', highlightthickness=0,
            troughcolor='#333333', length=230, showvalue=True
        )
        self.motion_scale.pack(padx=6, pady=4)

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
            bar_frame, width=220, height=14,
            bg='#333333', highlightthickness=1, highlightbackground='#555555'
        )
        self.audio_canvas.pack(side=tk.LEFT)

        tk.Label(bar_frame, text="  Clap or press START to begin",
                 font=('Helvetica', 9, 'italic'), bg=BG_DARK, fg=FG_GREY
                 ).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Canvas drag handlers (move finish line)
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

    def _start_camera(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            print("Warning: camera not available – running without video.")
            return
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        threading.Thread(target=self._camera_loop, daemon=True).start()

    def _camera_loop(self):
        while True:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    frame = cv2.flip(frame, 1)   # mirror so it feels natural
                    self._process_frame(frame)
            time.sleep(0.033)   # ~30 fps

    def _process_frame(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        line_y = int(self.line_position * h)
        band_h = 22

        # --- Motion detection on finish-line band ---
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        car_crossed = False
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
        cv2.putText(frame, "FINISH LINE", (10, line_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, line_color, 2)

        # Flash on detection
        if car_crossed:
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (0, 255, 120), -1)
            cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        # Resize to canvas size and enqueue
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
                if (level > self.sound_threshold
                        and not self.running
                        and now - self.last_clap_start > 1.5):
                    self.last_clap_start = now
                    self.root.after(0, self.manual_start)

            with sd.InputStream(callback=callback, channels=1,
                                samplerate=44100, blocksize=1024):
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

        lap_num  = len(self.lap_times)
        marker   = "  BEST!" if is_best else ""
        self.lap_listbox.insert(tk.END, f"  Lap {lap_num:2d}:  {self._fmt(lap_time)}{marker}")
        self.lap_listbox.see(tk.END)

        # Reset lap start
        self.start_time = time.time()

        # Green flash on the timer
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
    # Display update loop (~30 fps via after())
    # ------------------------------------------------------------------

    def _update_display(self):
        # Update timer digits
        if self.running and self.start_time:
            self.current_time = time.time() - self.start_time
            self.time_display.config(text=self._fmt(self.current_time))

        # Push new camera frame to canvas
        if not self.frame_queue.empty():
            img = self.frame_queue.get_nowait()
            self._tk_img = ImageTk.PhotoImage(img)   # keep reference
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self._tk_img)

        # Audio level bar
        self.audio_canvas.delete('all')
        ratio     = min(1.0, self.audio_level / max(self.sound_threshold, 0.001))
        bar_w     = int(ratio * 220)
        bar_color = '#ff4444' if ratio >= 1.0 else FG_TEAL
        if bar_w > 0:
            self.audio_canvas.create_rectangle(0, 0, bar_w, 14, fill=bar_color, outline='')

        self.root.after(33, self._update_display)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_motion_threshold(self, val):
        self.motion_threshold = int(val)

    @staticmethod
    def _fmt(seconds: float) -> str:
        m  = int(seconds // 60)
        s  = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{m:02d}:{s:02d}.{cs:02d}"

    def cleanup(self):
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
