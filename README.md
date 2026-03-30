# RC Car Lap Timer

Full-screen webcam overlay with automatic lap timing via microphone click detection.

## Setup

```bash
pip install -r requirements.txt
```

> **macOS:** If `pyaudio` fails to install, first run:
> ```bash
> brew install portaudio
> pip install pyaudio
> ```

## Run

```bash
python timer.py
```

## How it works

1. Point your webcam at the finish line.
2. Place a clicker / strip / noise-maker at the finish line.
3. The **first click** starts the timer.
4. Every **subsequent click** records a lap and resets the timer.

The microphone listens continuously. When the RMS volume spikes above the
threshold it counts as a trigger — with a built-in debounce so a single
physical click can't fire twice.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `R` | Reset session (keeps all-time best) |
| `T` | Adjust mic sensitivity threshold |

## Tuning the threshold

The default threshold is `0.15`. If the timer triggers on background noise,
raise it. If it misses clicks, lower it. Press `T` while the app is running
to change it without restarting, or edit `AUDIO_THRESHOLD` at the top of
`timer.py`.

## Files

| File | Purpose |
|------|---------|
| `timer.py` | Main application |
| `best_times.json` | Persisted all-time best (auto-created) |
