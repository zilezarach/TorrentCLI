# 🏴‍☠️ Yarr – The Pirate's Terminal

> A beautiful, feature-rich command-line client for searching and downloading
> torrents, books, movies and game repacks – all from your terminal.

```
  ██╗   ██╗ █████╗ ██████╗ ██████╗
  ╚██╗ ██╔╝██╔══██╗██╔══██╗██╔══██╗
   ╚████╔╝ ███████║██████╔╝██████╔╝
    ╚██╔╝  ██╔══██║██╔══██╗██╔══██╗
     ██║   ██║  ██║██║  ██║██║  ██║
     ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝

  Torrents  •  Books  •  Movies  •  Games
  Powered by ZilTor
```

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
  - [zil\_tor – API Backend](#zil_tor--api-backend)
  - [qBittorrent](#qbittorrent)
- [Installation](#installation)
  - [Quick Install (recommended)](#quick-install-recommended)
  - [Manual Install](#manual-install)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Commands](#commands)
  - [Examples](#examples)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Yarr is a terminal UI (TUI) built with [Rich](https://github.com/Textualize/rich)
and [Typer](https://typer.tiangolo.com/) that wraps the
[**zil\_tor**](https://github.com/zilezarach/zil_tor) Go API server to give you:

| Feature | Details |
|---|---|
| 🔍 Universal search | Movies (YTS), Books (LibGen + Anna's Archive), Games (FitGirl/DODI repacks), General torrents (1337x) |
| ⬇️ Torrent download | Sends magnet links straight to qBittorrent and shows a live progress bar |
| 📦 Direct download | Streams book files (PDF, EPUB, …) directly to disk with resume support |
| 📊 Dashboard | Live view of active downloads, download history and API server health |
| ⚙️ Config | JSON config file at `~/.yarr/config.json` |
| 📜 History | Persistent download history |

---

## Prerequisites

### zil_tor – API Backend

**Yarr requires the [zil_tor](https://github.com/zilezarach/zil_tor) Go API server
to be running.** It is the backbone that federates searches across all indexers and
handles torrent metadata resolution.

#### Option A – Docker (recommended)

```bash
# Pull and run the latest image
docker pull ghcr.io/zilezarach/zil_tor:latest
docker run -d --name zil_tor -p 9117:9117 ghcr.io/zilezarach/zil_tor:latest

# Verify it is healthy
curl http://127.0.0.1:9117/api/v1/health
```

#### Option B – docker-compose

```bash
git clone https://github.com/zilezarach/zil_tor.git
cd zil_tor
docker-compose up -d
```

#### Option C – Build from source (requires Go 1.21+)

```bash
git clone https://github.com/zilezarach/zil_tor.git
cd zil_tor
go build -o zil_tor ./cmd/server
./zil_tor        # listens on :9117 by default
```

The API server listens on `http://127.0.0.1:9117` by default. This address is
stored in `~/.yarr/config.json` (`zil_api` key) and can be changed there.

### qBittorrent

Torrent downloads are handled by [qBittorrent](https://www.qbittorrent.org/).
You must have qBittorrent installed **with Web UI enabled**:

1. Open qBittorrent → **Tools → Preferences → Web UI**
2. Enable *"Web User Interface (Remote control)"*
3. Set a username / password (defaults: `admin` / `adminpass`)
4. The Web UI should listen on `http://127.0.0.1:8080`

> 💡 On headless servers install `qbittorrent-nox`:
> `sudo apt install qbittorrent-nox`

---

## Installation

### Quick Install (recommended)

```bash
git clone https://github.com/zilezarach/TorrentCLI.git
cd TorrentCLI
chmod +x install.sh
./install.sh
```

The installer will:

1. Detect whether **pipx** is available and use it for an isolated install, *or*
   fall back to creating a local `.venv` and placing a wrapper script on `PATH`.
2. Print clear next-steps for starting the zil\_tor backend.
3. Requires **Python 3.10+**.

After installation, `yarr` is available **without activating any virtual
environment**:

```bash
yarr --help
```

### Manual Install

#### With pipx (recommended for isolation)

```bash
pip install pipx        # if not already installed
pipx install .
```

#### With pip (system / user)

```bash
pip install --user .
# make sure ~/.local/bin is on your PATH
```

#### Development install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Configuration

On first run, Yarr creates `~/.yarr/config.json` with sensible defaults:

```json
{
  "download_path": "~/Downloads/Torrents",
  "zil_api": "http://127.0.0.1:9117",
  "qbittorrent": {
    "host": "http://127.0.0.1:8080",
    "username": "admin",
    "password": "adminpass"
  },
  "health_check_interval": 3600,
  "schedule_check_interval": 60,
  "max_active_downloads": 5,
  "auto_remove_completed": false,
  "direct_download_path": "~/Downloads/Books",
  "theme": "dark"
}
```

| Key | Description |
|---|---|
| `download_path` | Directory where torrent files are saved |
| `direct_download_path` | Directory where direct-download files (books) are saved |
| `zil_api` | URL of the running zil\_tor API server |
| `qbittorrent.host` | qBittorrent Web UI URL |
| `qbittorrent.username` | Web UI username |
| `qbittorrent.password` | Web UI password |
| `max_active_downloads` | Cap on simultaneous torrent downloads |
| `auto_remove_completed` | Remove completed torrents from qBittorrent (files are kept) |
| `health_check_interval` | Seconds between background API health checks |

Edit with any text editor:

```bash
nano ~/.yarr/config.json
```

---

## Usage

### Commands

```
yarr                    Interactive main menu
yarr browse             Interactive search & download (recommended)
yarr search <query>     Quick search across all indexers
yarr download <index>   Download result by index from last search
yarr list               Show active torrent downloads
yarr list --all         Show all torrents in qBittorrent
yarr dashboard          Live dashboard (server health + active downloads)
yarr server-info        Detailed API server / indexer status
yarr history            Show download history
yarr config             Show current configuration
yarr quick              Quick category-filtered search
yarr --help             Full help
```

### Examples

```bash
# Interactive browse – the easiest way to find and download anything
yarr browse

# Search for a movie
yarr search "Inception 2010"

# Download result #3 from the last search
yarr download 3

# Check what is currently downloading
yarr list

# View server and indexer health
yarr server-info

# Open the full dashboard
yarr dashboard
```

---

## Project Structure

```
TorrentCLI/
├── yarr.py              # CLI application (Typer + Rich)
├── zil_api_client.py    # HTTP client for the zil_tor API
├── requirements.txt     # Pinned dependencies (for reproducible installs)
├── pyproject.toml       # Package metadata & console-script entry point
├── install.sh           # One-command installer (no manual venv activation)
└── README.md            # This file
```

Runtime data is stored under `~/.yarr/`:

```
~/.yarr/
├── config.json          # User configuration
├── history.json         # Download history
├── schedule.json        # Scheduled downloads
└── last.json            # Results from the most recent search
```

---

## Contributing

Pull requests are welcome! Please open an issue first to discuss significant
changes.

```bash
git clone https://github.com/zilezarach/TorrentCLI.git
cd TorrentCLI
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## License

MIT © [zilezarach](https://github.com/zilezarach)
