# SpokenSlate

**Give production audio a useful name before the edit begins.** SpokenSlate transcribes recordings in a folder, makes a short title from what was said, and keeps the original recorder filename in brackets. It runs locally after a one-time setup.

`A001_003.wav` → `Austin discusses next week's concrete pour [A001_003].wav`

The default makes a named copy, a timestamped transcript, and a CSV manifest. Your originals remain in place. Clips with little or unclear speech become `Needs review [original-name]` so a guessed title does not hide them.

## Requirements

- Windows 10 or 11, 64-bit
- Python 3.10–3.12 available as `python` in Command Prompt
- Internet for the first setup (about 2 GB of downloads); processing is offline afterward
- Enough free disk space for the models and named copies

SpokenSlate currently transcribes **English** speech. It uses the CPU, so a long folder can take time.

## Install

1. Download or clone this repository.
2. Double-click **`Setup SpokenSlate.cmd`** and let it finish. It creates a private `.venv` and downloads the speech model, title model, and portable runtime into this folder.
3. Double-click **`Launch SpokenSlate.vbs`** to open the app.

The setup can be rerun after an interrupted download. It leaves Python's global packages alone.

## Use

1. Open your audio folder in File Explorer and leave that window active.
2. Launch SpokenSlate. It detects the open folder and begins processing automatically.
3. Open the `_SpokenSlate` folder inside your audio folder for the named copies, `.txt` transcripts, `manifest.csv`, and `processed.json` run state.

If Explorer was not active, SpokenSlate asks you to choose a folder. Review the folder shown, then click **Name recordings**. To rename originals in place, select that option before starting a job. Only files directly inside the selected folder are processed; subfolders are ignored. Running the same folder again skips files already processed whose named result still exists.

Supported formats: WAV/BWF, MP3, M4A, AAC, FLAC, OGG/Opus, WMA, AIFF, MP4/MOV. Audio is decoded without changing the media format of the copies.

### Stream Deck

Add **System → Open** to a key and set **App / File** to `Launch SpokenSlate.vbs` in your installation folder. A physical key press launches the same workflow; keep the target Explorer folder active when pressing it.

### Command line

```powershell
.\.venv\Scripts\python.exe app.py "D:\Project\Audio" --no-gui
.\.venv\Scripts\python.exe app.py "D:\Project\Audio" --no-gui --mode rename
```

## Naming and privacy

The speech model transcribes the words. A local language model turns excerpts from the start, middle, and end of the transcript into a concise filename. A person's name is used only when the words establish who is speaking or being discussed; this tool does not recognize people by voice. All model inference stays on your computer. Setup downloads models from Hugging Face and a portable runtime from GitHub; recorded audio is not uploaded.

The title is an editing aid, so check transcripts for important recordings. The manifest preserves a mapping to the original filename. When upgrading from the earlier *Lav Namer*, SpokenSlate continues using an existing `_Lav Namer` results folder that contains `processed.json` rather than processing those clips twice. New folders use `_SpokenSlate`.

## Components

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with [Whisper small.en](https://huggingface.co/Systran/faster-whisper-small.en) for local transcription
- [Qwen2.5 1.5B Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) for local titles
- [llama.cpp](https://github.com/ggml-org/llama.cpp) for title model inference

Models and executables are downloaded during setup and are not stored in this repository. See each component's license at its linked source. The code in this repository is licensed separately; see `LICENSE`.
