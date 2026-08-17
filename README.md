# Any Video Downloader

A local PySide6 desktop interface for the official open-source
[yt-dlp](https://github.com/yt-dlp/yt-dlp) engine. Analyze an exact URL,
review discovered videos, and manage single or bulk downloads without
freezing the interface.

Use only for content you own, have permission to download, or that is legally
offered for download. Does not bypass DRM, paywalls, authentication, CAPTCHAs,
or geographic controls.

## Requirements

- Python 3.11+, Git, FFmpeg
- Linux desktop, or WSL 2 with WSLg
- Internet access

```bash
sudo apt update
sudo apt install python3 python3-venv git ffmpeg
```

## Get the code

```bash
git clone https://github.com/nthxdev/any-video-downloader.git
cd any-video-downloader
```

## Get the yt-dlp engine

`vendor/yt-dlp` is not committed to this repo. From inside the
`any-video-downloader` folder, clone it in before first run — this always
places it at `any-video-downloader/vendor/yt-dlp`:

```bash
mkdir -p vendor
git clone https://github.com/yt-dlp/yt-dlp.git vendor/yt-dlp
```

To update it later:

```bash
git -C vendor/yt-dlp pull --ff-only
```

## Install and Launch

```bash
chmod +x run.sh
./run.sh
```

`run.sh` sets up `.venv`, installs dependencies, checks display/FFmpeg, and
opens the app.

Manual setup:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.main
```

## Usage

- **Single URL:** paste a URL, **Analyze** to review details, then
  **Download**.
- **Bulk File:** load a `.txt`, `.md`, or `.csv` file, review/select rows,
  then **Download selected**.
- **Discovery:** paste a profile/channel/playlist URL, **Analyze**, then
  select and download entries (default limit 1000, configurable in Settings).
- **Clean a link file:** `python3 scripts/clean_links.py yourfile.md`
  extracts unique valid URLs and backs up the original.
- **Cookies:** in Settings, select a local browser so yt-dlp can read its
  cookies for sites requiring sign-in (use only your own account).
- Completed downloads are tracked in `data/downloaded.txt` to avoid repeats
  (toggle in Settings).

## Project Structure

```text
app/         models, services, ui, workers
scripts/     link cleaner
tests/       offline unit tests
data/        settings and download archive
downloads/   default output folder
vendor/yt-dlp/  official upstream checkout (separately licensed)
```

## Credits & License

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), the official open-source
engine that performs all extraction and downloading. The MIT `LICENSE`
applies to this GUI code only; `vendor/yt-dlp` retains its own upstream
license and copyright notices.
