#!/usr/bin/env python3
"""
RC Car Lap Timer
- Webcam shows full-screen video feed (dimmed)
- Microphone detects click sound at finish line to trigger laps
- Displays current timer, last 5 laps, and all-time best
"""

import cv2
import numpy as np
import pyaudio
import threading
import time
import json
import os
import sys

# ── Configuration ────────────────────────────────────────────────────────────

AUDIO_THRESHOLD   = 0.15   # RMS level to count as a click (0.0–1.0); tune this
MIN_LAP_SECONDS   = 2.0    # Ignore triggers closer than this (debounce)
CAMERA_INDEX      = 0      # Change if your webcam isn't index 0
DIM_FACTOR        = 0.45   # How much to dim the video (0 = black, 1 = full)
BEST_TIMES_FILE   = "best_times.json"

# ── Colours (BGR) ────────────────────────────────────────────────────────────
WHITE   = (255, 255, 255)
YELLOW  = (0,   220, 255)
GREEN   = (100, 255, 100)
GRAY    = (160, 160, 160)
BLACK   = (0,     0,   0)

# ── State (shared between threads) ───────────────────────────────────────────
state_lock         = threading.Lock()
timer_running      = False
start_time         = 0.0
laps: list[float]  = []          # all laps this session
all_time_best: float | None = None
flash_until        = 0.0         # show "LAP!" flash until this time
last_trigger       = 0.0         # for debounce


def load_best() -> float | None:
    if os.path.exists(BEST_TIMES_FILE):
        try:
            data = json.load(open(BEST_TIMES_FILE))
            v = data.get("best")
            return float(v) if v is not None else None
        except Exception:
            pass
    return None


def save_best(t: float) -> None:
    try:
        json.dump({"best": t}, open(BEST_TIMES_FILE, "w"))
    except Exception:
        pass


def fmt(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


# ── Audio thread ─────────────────────────────────────────────────────────────

def audio_loop() -> None:
    global timer_running, start_time, laps, all_time_best, flash_until, last_trigger

    pa     = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paFloat32,
        channels=1,
        rate=44100,
        input=True,
        frames_per_buffer=1024,
    )

    print("Microphone active. Listening for clicks…")
    while True:
        try:
            raw   = stream.read(1024, exception_on_overflow=False)
            chunk = np.frombuffer(raw, dtype=np.float32)
            rms   = float(np.sqrt(np.mean(chunk ** 2)))
        except Exception:
            continue

        now = time.time()
        if rms < AUDIO_THRESHOLD:
            continue
        if now - last_trigger < MIN_LAP_SECONDS:
            continue

        with state_lock:
            last_trigger = now
            if not timer_running:
                # First click → start timer
                timer_running = True
                start_time    = now
                print("Timer started.")
            else:
                # Subsequent click → record lap, reset timer
                lap_time      = now - start_time
                laps.append(lap_time)
                start_time    = now
                flash_until   = now + 1.2

                if all_time_best is None or lap_time < all_time_best:
                    all_time_best = lap_time
                    save_best(all_time_best)

                print(f"Lap {len(laps)}: {fmt(lap_time)}")


# ── Drawing helpers ───────────────────────────────────────────────────────────

def draw_text_shadowed(img, text, pos, scale, color, thickness=2):
    """Draw text with a drop-shadow for readability over any background."""
    x, y = pos
    cv2.putText(img, text, (x+2, y+2), cv2.FONT_HERSHEY_SIMPLEX,
                scale, BLACK, thickness + 2, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, color, thickness, cv2.LINE_AA)


def draw_rect_alpha(img, x1, y1, x2, y2, color_bgr, alpha=0.45):
    """Draw a semi-transparent filled rectangle."""
    roi    = img[y1:y2, x1:x2]
    rect   = np.full_like(roi, color_bgr, dtype=np.uint8)
    cv2.addWeighted(rect, alpha, roi, 1 - alpha, 0, roi)
    img[y1:y2, x1:x2] = roi


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    global all_time_best

    all_time_best = load_best()

    # Start audio thread
    t = threading.Thread(target=audio_loop, daemon=True)
    t.start()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"ERROR: Cannot open camera index {CAMERA_INDEX}", file=sys.stderr)
        sys.exit(1)

    # Try to get native resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    cv2.namedWindow("RC Timer", cv2.WINDOW_NORMAL)
    cv2.setWindowProperty("RC Timer", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    print("Press  Q  to quit  |  R  to reset session  |  T  to adjust threshold")

    while True:
        ret, frame = cap.read()
        if not ret:
            # Show black frame if camera fails
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        h, w = frame.shape[:2]

        # Dim the video
        frame = (frame.astype(np.float32) * DIM_FACTOR).clip(0, 255).astype(np.uint8)

        with state_lock:
            running      = timer_running
            t_start      = start_time
            snap_laps    = list(laps)
            snap_best    = all_time_best
            snap_flash   = flash_until

        now = time.time()

        # ── Current elapsed time ──────────────────────────────────────────
        if running:
            elapsed = now - t_start
            timer_color = GREEN
        else:
            elapsed = 0.0
            timer_color = GRAY

        timer_str = fmt(elapsed)

        # Background panel behind the big timer
        draw_rect_alpha(frame, 0, 0, w, int(h * 0.22), (0, 0, 0), alpha=0.5)

        # Big timer centred at top
        scale_big = w / 600
        (tw, th), _ = cv2.getTextSize(timer_str, cv2.FONT_HERSHEY_SIMPLEX, scale_big, 3)
        tx = (w - tw) // 2
        ty = int(h * 0.16)
        draw_text_shadowed(frame, timer_str, (tx, ty), scale_big, timer_color, thickness=3)

        # "Waiting…" hint before first trigger
        if not running:
            hint = "clap or click to start"
            scale_hint = w / 2000
            (hw, _), _ = cv2.getTextSize(hint, cv2.FONT_HERSHEY_SIMPLEX, scale_hint, 1)
            draw_text_shadowed(frame, hint, ((w - hw) // 2, ty + int(h * 0.06)),
                               scale_hint, GRAY, thickness=1)

        # ── Lap list (last 5) ─────────────────────────────────────────────
        recent       = snap_laps[-5:]
        scale_lap    = w / 1400
        line_h       = int(h * 0.075)
        panel_top    = int(h * 0.24)
        panel_bottom = panel_top + len(recent) * line_h + int(h * 0.04)
        if recent:
            draw_rect_alpha(frame, 0, panel_top, int(w * 0.38), panel_bottom,
                            (0, 0, 0), alpha=0.45)

        for i, lap in enumerate(recent):
            lap_num = len(snap_laps) - len(recent) + i + 1
            label   = f"Lap {lap_num}:  {fmt(lap)}"
            y_pos   = panel_top + int(h * 0.045) + i * line_h

            is_best = (snap_best is not None and abs(lap - snap_best) < 0.001)
            color   = YELLOW if is_best else WHITE
            draw_text_shadowed(frame, label, (int(w * 0.025), y_pos),
                               scale_lap, color, thickness=2)
            if is_best:
                draw_text_shadowed(frame, " ★ BEST", (int(w * 0.025) + int(w * 0.28), y_pos),
                                   scale_lap * 0.8, YELLOW, thickness=1)

        # ── All-time best (bottom right) ──────────────────────────────────
        if snap_best is not None:
            best_str   = f"ALL-TIME BEST  {fmt(snap_best)}"
            scale_best = w / 1600
            (bw, _), _ = cv2.getTextSize(best_str, cv2.FONT_HERSHEY_SIMPLEX, scale_best, 2)
            draw_rect_alpha(frame, w - bw - int(w * 0.05), h - int(h * 0.1),
                            w, h, (0, 0, 0), alpha=0.5)
            draw_text_shadowed(frame, best_str,
                               (w - bw - int(w * 0.025), h - int(h * 0.04)),
                               scale_best, YELLOW, thickness=2)

        # ── LAP flash ─────────────────────────────────────────────────────
        if now < snap_flash:
            alpha_f    = (snap_flash - now) / 1.2
            scale_f    = w / 300
            flash_str  = "LAP!"
            (fw, fh), _ = cv2.getTextSize(flash_str, cv2.FONT_HERSHEY_SIMPLEX, scale_f, 4)
            fx = (w - fw) // 2
            fy = (h + fh) // 2
            # crude fade: blend white text proportional to remaining time
            flash_color = tuple(int(c * alpha_f) for c in GREEN)
            draw_text_shadowed(frame, flash_str, (fx, fy), scale_f,
                               flash_color, thickness=4)

        # ── Threshold indicator (bottom left) ────────────────────────────
        thr_str = f"Mic threshold: {AUDIO_THRESHOLD:.2f}  (T to adjust)"
        draw_text_shadowed(frame, thr_str,
                           (int(w * 0.01), h - int(h * 0.025)),
                           w / 3000, GRAY, thickness=1)

        cv2.imshow("RC Timer", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            with state_lock:
                timer_running = False
                start_time    = 0.0
                laps.clear()
            print("Session reset.")
        elif key == ord('t'):
            _adjust_threshold()

    cap.release()
    cv2.destroyAllWindows()


def _adjust_threshold():
    global AUDIO_THRESHOLD
    val = input(f"Current threshold: {AUDIO_THRESHOLD:.2f}. New value (0.01–1.0): ").strip()
    try:
        v = float(val)
        if 0.01 <= v <= 1.0:
            AUDIO_THRESHOLD = v
            print(f"Threshold set to {AUDIO_THRESHOLD:.2f}")
        else:
            print("Out of range, keeping current value.")
    except ValueError:
        print("Invalid input, keeping current value.")


if __name__ == "__main__":
    main()
