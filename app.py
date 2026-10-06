"""SpokenSlate: transcribe production audio and title clips from their content."""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))

AUDIO_EXTENSIONS = {
    ".wav", ".bwf", ".mp3", ".m4a", ".aac", ".flac", ".ogg",
    ".opus", ".wma", ".aif", ".aiff", ".mp4", ".mov",
}
APP_NAME = "SpokenSlate"
OUTPUT_NAME = "_SpokenSlate"
LEGACY_OUTPUT_NAME = "_Lav Namer"
MAX_TITLE_LENGTH = 64


def active_explorer_folder() -> Path | None:
    """Return the currently focused Explorer folder, before our GUI takes focus."""
    if os.name != "nt":
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        class_name = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value not in {"CabinetWClass", "ExploreWClass"}:
            return None
        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            f"$window = $shell.Windows() | Where-Object {{ $_.HWND -eq {hwnd} }} | Select-Object -First 1; "
            "if ($window) { $window.Document.Folder.Self.Path }"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=8, creationflags=0x08000000,
        )
        location = result.stdout.strip()
        if not location:
            return None
        folder = Path(location)
        return folder if result.returncode == 0 and folder.is_dir() else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def clean_title(value: str) -> str:
    value = value.strip().splitlines()[0] if value.strip() else ""
    value = re.sub(r"^(?:title|filename)\s*:\s*", "", value, flags=re.I)
    value = value.strip(" \"'`“”.,;:-_")
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if len(value) > MAX_TITLE_LENGTH:
        value = value[:MAX_TITLE_LENGTH].rsplit(" ", 1)[0].strip(" .")
    if value.upper() in {"CON", "PRN", "AUX", "NUL"}:
        value += " recording"
    return value or "Needs review"


def transcript_excerpt(segments: list[dict]) -> str:
    if not segments:
        return ""
    if len(segments) <= 36:
        chosen = segments
    else:
        mid = len(segments) // 2
        chosen = segments[:14] + segments[mid - 5:mid + 5] + segments[-10:]
    return " ".join(s["text"] for s in chosen)[:7000]


def fallback_title(transcript: str) -> str:
    words = re.findall(r"[\w'-]+", transcript, flags=re.UNICODE)
    if len(words) < 3:
        return "Needs review"
    return clean_title(" ".join(words[:7]))


def request_json(url: str, payload: dict | None = None, timeout: float = 10) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


class LocalTitleModel:
    def __init__(self, report):
        self.report = report
        self.process: subprocess.Popen | None = None
        self.port: int | None = None

    def __enter__(self):
        binary = ROOT / "llama" / "llama-server.exe"
        model = ROOT / "model" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
        if not binary.is_file() or not model.is_file():
            self.report("Local title model is missing. Using spoken words as titles.")
            return self
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        command = [
            str(binary), "--model", str(model), "--host", "127.0.0.1",
            "--port", str(self.port), "--ctx-size", "4096", "--threads", "8",
            "--no-webui", "--log-disable",
        ]
        try:
            self.process = subprocess.Popen(
                command, cwd=binary.parent, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0,
            )
            for _ in range(120):
                if self.process.poll() is not None:
                    break
                try:
                    if request_json(f"http://127.0.0.1:{self.port}/health", timeout=1).get("status") == "ok":
                        return self
                except (OSError, ValueError):
                    pass
                time.sleep(0.5)
        except OSError as exc:
            self.report(f"Title model could not start: {exc}")
        self.report("Title model unavailable. Using spoken words as titles.")
        self.close()
        return self

    def title(self, segments: list[dict], transcript: str) -> str:
        if not transcript or len(re.findall(r"\w+", transcript)) < 3:
            return "Needs review"
        if self.process is None or self.process.poll() is not None:
            return fallback_title(transcript)
        prompt = (
            "Name a production audio recording for a video editor. "
            "Return ONLY one specific, plain-English filename title, 3 to 8 words. "
            "Describe the actual subject or action. Use a person's name only if the "
            "transcript explicitly establishes that person is speaking or being discussed. "
            "Do not invent people, locations, events, or topics. "
            "If the content is unclear, reply Needs review.\n\n"
            f"Transcript: {transcript_excerpt(segments)}"
        )
        try:
            response = request_json(
                f"http://127.0.0.1:{self.port}/v1/chat/completions",
                {
                    "model": "local", "temperature": 0.1, "max_tokens": 36,
                    "messages": [
                        {"role": "system", "content": "You make accurate, short file titles from transcripts."},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=120,
            )
            title = clean_title(response["choices"][0]["message"]["content"])
            return title if title.lower() != "needs review" else "Needs review"
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.report(f"Title model error: {exc}. Using spoken words.")
            return fallback_title(transcript)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def __exit__(self, *_):
        self.close()


def unique_destination(directory: Path, name: str, suffix: str) -> Path:
    path = directory / f"{name}{suffix}"
    number = 2
    while path.exists() or path.with_suffix(".txt").exists():
        path = directory / f"{name} ({number}){suffix}"
        number += 1
    return path


def process_folder(folder: Path, mode: str, report, should_stop=lambda: False) -> dict:
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Folder does not exist: {folder}")
    files = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS),
        key=lambda p: p.name.casefold(),
    )
    if not files:
        raise ValueError("No supported audio files were found in this folder.")
    model_path = ROOT / "model" / "model.bin"
    if not model_path.is_file():
        raise FileNotFoundError(f"Speech model missing: {model_path}")
    from faster_whisper import WhisperModel

    # Keep existing jobs in their original results folder so upgrading from
    # Lav Namer does not produce a second set of copies on the next run.
    legacy_output = folder / LEGACY_OUTPUT_NAME
    output = legacy_output if (legacy_output / "processed.json").is_file() and not (folder / OUTPUT_NAME).exists() else folder / OUTPUT_NAME
    output.mkdir(exist_ok=True)
    state_path = output / "processed.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    report("Loading local speech model...")
    whisper = WhisperModel(str(ROOT / "model"), device="cpu", compute_type="int8", cpu_threads=8)
    summary = {"done": 0, "skipped": 0, "failed": 0, "output": str(output)}
    manifest = output / "manifest.csv"
    fields = ["original", "named_file", "title", "duration_seconds", "status", "processed_at"]
    with LocalTitleModel(report) as titler, manifest.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fields)
        if manifest.stat().st_size == 0:
            writer.writeheader()
        for index, source in enumerate(files, 1):
            if should_stop():
                report("Stopped after the current file.")
                break
            signature = f"{source.name}|{source.stat().st_size}|{source.stat().st_mtime_ns}"
            prior = state.get(signature)
            prior_dir = folder if prior and prior.get("mode") == "rename" else output
            if prior and prior.get("mode") == mode and (prior_dir / prior["named_file"]).is_file():
                summary["skipped"] += 1
                report(f"[{index}/{len(files)}] Skipped {source.name} (already processed)")
                continue
            report(f"[{index}/{len(files)}] Transcribing {source.name}...")
            try:
                raw_segments, info = whisper.transcribe(
                    str(source), language="en", beam_size=5, vad_filter=True,
                    condition_on_previous_text=False,
                )
                segments = [
                    {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                    for s in raw_segments if s.text.strip()
                ]
                transcript = " ".join(s["text"] for s in segments).strip()
                title = titler.title(segments, transcript)
                source_id = clean_title(source.stem)
                basename = f"{title} [{source_id}]"
                destination_dir = folder if mode == "rename" else output
                destination = unique_destination(destination_dir, basename, source.suffix)
                if mode == "rename":
                    source.rename(destination)
                else:
                    temp = output / f".{source.name}.copying"
                    try:
                        shutil.copy2(source, temp)
                        temp.replace(destination)
                    finally:
                        temp.unlink(missing_ok=True)
                transcript_path = output / f"{destination.stem}.txt"
                transcript_path.write_text(
                    f"Original: {source.name}\nNamed file: {destination.name}\n"
                    f"Title: {title}\nDuration: {info.duration:.1f} seconds\n\n"
                    + "\n".join(
                        f"[{s['start']:>7.2f}–{s['end']:>7.2f}] {s['text']}" for s in segments
                    ) + "\n",
                    encoding="utf-8",
                )
                writer.writerow({
                    "original": source.name, "named_file": destination.name,
                    "title": title, "duration_seconds": round(info.duration, 1),
                    "status": "review" if title == "Needs review" else "named",
                    "processed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                })
                csv_file.flush()
                # A rename changes the file's signature. Track the new identity
                # so the next run skips it instead of titling it a second time.
                saved_signature = (
                    f"{destination.name}|{destination.stat().st_size}|{destination.stat().st_mtime_ns}"
                    if mode == "rename" else signature
                )
                state[saved_signature] = {"named_file": destination.name, "mode": mode}
                state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                summary["done"] += 1
                report(f"  -> {destination.name}")
            except Exception as exc:
                summary["failed"] += 1
                report(f"  ERROR {source.name}: {exc}")
    return summary


def launch_gui(initial: Path | None = None):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("720x520")
    root.minsize(600, 420)
    root.configure(bg="#151a20")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background="#151a20")
    style.configure("TLabel", background="#151a20", foreground="#f3f4f6", font=("Segoe UI", 10))
    style.configure("TButton", font=("Segoe UI", 10), padding=8)
    style.configure("TRadiobutton", background="#151a20", foreground="#e5e7eb", font=("Segoe UI", 10))
    style.map("TRadiobutton", background=[("active", "#151a20")], foreground=[("active", "#ffffff")])

    frame = ttk.Frame(root, padding=22)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="SPOKENSLATE", font=("Segoe UI Semibold", 20)).pack(anchor="w")
    ttk.Label(frame, text="Turn a folder of recordings into searchable, descriptive files.").pack(anchor="w", pady=(2, 18))
    folder_var = tk.StringVar(value=str(initial) if initial else "")
    row = ttk.Frame(frame)
    row.pack(fill="x")
    entry = ttk.Entry(row, textvariable=folder_var, font=("Segoe UI", 10))
    entry.pack(side="left", fill="x", expand=True)
    def browse():
        chosen = filedialog.askdirectory(title="Choose the folder containing lav recordings", initialdir=folder_var.get() or None)
        if chosen:
            folder_var.set(chosen)
    ttk.Button(row, text="Choose folder", command=browse).pack(side="left", padx=(8, 0))
    mode_var = tk.StringVar(value="copy")
    ttk.Radiobutton(frame, text="Make named copies in a results folder (recommended)", variable=mode_var, value="copy").pack(anchor="w", pady=(18, 0))
    ttk.Radiobutton(frame, text="Rename original recordings in this folder", variable=mode_var, value="rename").pack(anchor="w")
    ttk.Label(frame, text="Timestamped transcripts and a manifest are saved in _SpokenSlate.").pack(anchor="w", pady=(8, 12))
    events: queue.Queue = queue.Queue()
    stop = threading.Event()
    log = tk.Text(frame, height=12, bg="#0e1217", fg="#d8e2eb", insertbackground="#ffffff", relief="flat", wrap="word", font=("Consolas", 9), state="disabled")
    log.pack(fill="both", expand=True)
    def append(text: str):
        log.configure(state="normal")
        log.insert("end", text + "\n")
        log.see("end")
        log.configure(state="disabled")
    button_row = ttk.Frame(frame)
    button_row.pack(fill="x", pady=(12, 0))
    start = ttk.Button(button_row, text="Name recordings")
    start.pack(side="left")
    cancel = ttk.Button(button_row, text="Stop after current file", command=stop.set, state="disabled")
    cancel.pack(side="left", padx=(8, 0))
    open_output = ttk.Button(button_row, text="Open results", state="disabled")
    open_output.pack(side="right")
    def run():
        folder = Path(folder_var.get().strip().strip('"'))
        if not folder.is_dir():
            messagebox.showerror("Choose a folder", "Select a folder containing your recordings.")
            return
        stop.clear()
        start.configure(state="disabled")
        cancel.configure(state="normal")
        open_output.configure(state="disabled")
        append(f"Folder: {folder}")
        selected_mode = mode_var.get()
        def worker():
            try:
                result = process_folder(folder, selected_mode, lambda s: events.put(("log", s)), stop.is_set)
                events.put(("done", result))
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    start.configure(command=run)
    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "log":
                    append(value)
                elif kind == "done":
                    append(f"Done: {value['done']} named, {value['skipped']} skipped, {value['failed']} failed.")
                    start.configure(state="normal")
                    cancel.configure(state="disabled")
                    open_output.configure(state="normal", command=lambda p=value["output"]: os.startfile(p))
                elif kind == "error":
                    append("ERROR: " + value)
                    start.configure(state="normal")
                    cancel.configure(state="disabled")
                    messagebox.showerror(APP_NAME, value)
        except queue.Empty:
            pass
        root.after(100, poll)
    root.after(100, poll)
    if initial:
        root.after(500, run)
    else:
        root.after(250, browse)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description="Transcribe and descriptively name lav recordings.")
    parser.add_argument("folder", nargs="?", type=Path, help="Folder of audio files; defaults to the active Explorer folder")
    parser.add_argument("--mode", choices=["copy", "rename"], default="copy")
    parser.add_argument("--no-gui", action="store_true")
    args = parser.parse_args()
    folder = args.folder or active_explorer_folder()
    if args.no_gui:
        if folder is None:
            parser.error("A folder is required with --no-gui")
        result = process_folder(folder, args.mode, print)
        print(json.dumps(result, indent=2))
        return
    launch_gui(folder)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if "--no-gui" in sys.argv:
            raise
        from tkinter import messagebox
        messagebox.showerror(APP_NAME, str(error))
