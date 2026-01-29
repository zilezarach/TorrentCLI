#!/home/zil/production/torrent_cli/venv/bin/python3
"""
Torrent CLI Script - Enhanced UI Version
A command-line interface for interacting with qBittorrent via Typer, with support
for searching torrents via zil_tor API, scheduling downloads, and monitoring torrent progress.
"""
import sys
import json
import time
import threading
import subprocess
import requests
import typer
from pathlib import Path
from datetime import datetime
from qbittorrentapi import Client as QBClient
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    DownloadColumn,
    TransferSpeedColumn,
)
from rich.panel import Panel
from rich import box
from rich.traceback import install
from rich.prompt import Prompt, Confirm
from rich.layout import Layout
from rich.live import Live
from rich.align import Align
from rich.text import Text
from rich.rule import Rule
from typing import Any, Dict, List, Optional
from zil_api_client import GoTorrentAPI, SearchResult, DownloadType, APIError

install()
app = typer.Typer()
console = Console()

# Set up configuration locations
HOME = Path.home()
CONFIG_DIR = HOME / "torrent_cli"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"
SCHEDULE_PATH = CONFIG_DIR / "schedule.json"
LAST_RESULTS = CONFIG_DIR / "last.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "download_path": "/mnt/nextcloud/Downloads",
    "zil_api": "http://127.0.0.1:9117",
    "qbittorrent": {
        "host": "http://127.0.0.1:8080",
        "username": "zile",
        "password": "zile123",
    },
    "health_check_interval": 3600,
    "schedule_check_interval": 60,
    "max_active_downloads": 5,
    "auto_remove_completed": False,
    "direct_download_path": "/mnt/nextcloud/Downloads",
}


def ensure_files() -> None:
    """Ensure directories and configuration/history/schedule files exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text())
    else:
        cfg = DEFAULT_CONFIG
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    # Ensure download directories exist
    Path(cfg["download_path"]).mkdir(parents=True, exist_ok=True)
    Path(cfg.get("direct_download_path", DEFAULT_CONFIG["direct_download_path"])).mkdir(
        parents=True, exist_ok=True
    )
    for p in (HISTORY_PATH, SCHEDULE_PATH, LAST_RESULTS):
        if not p.exists():
            p.write_text(json.dumps([], indent=2))


def load_json(path: Path) -> Any:
    """Load JSON data from the given file path."""
    ensure_files()
    return json.loads(path.read_text())


def save_json(path: Path, data: Any) -> None:
    """Save JSON data to the given file path."""
    ensure_files()
    path.write_text(json.dumps(data, indent=2))


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert a value to string."""
    return str(value) if value is not None else default


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_speed(speed_bytes: int) -> str:
    """Format bytes/s into human-readable speed."""
    return f"{format_size(speed_bytes)}/s"


def get_health_icon(value: int, thresholds: tuple = (10, 50)) -> str:
    """Get a colored icon based on health value."""
    if value >= thresholds[1]:
        return "🟢"
    elif value >= thresholds[0]:
        return "🟡"
    return "🔴"


def get_api_client() -> GoTorrentAPI:
    """Return configured Go API client."""
    cfg = load_json(CONFIG_PATH)
    api_url = cfg.get("zil_api", DEFAULT_CONFIG["zil_api"])
    return GoTorrentAPI(api_url)


def qb_client() -> QBClient:
    """Return an authenticated qBittorrent client instance."""
    cfg = load_json(CONFIG_PATH)
    qb_cfg = cfg["qbittorrent"]
    qb = QBClient(
        host=qb_cfg["host"],
        username=qb_cfg["username"],
        password=qb_cfg["password"],
        VERIFY_WEBUI_CERTIFICATE=False,
    )
    qb.auth_log_in()
    return qb


def fetch(
    query: str, limit: int = 10, category: Optional[str] = None
) -> List[SearchResult]:
    """Fetch search results from Go API."""
    try:
        api = get_api_client()
        return api.search(query, limit, category)
    except APIError as e:
        console.print(f"[red]✗ API error: {e}[/red]")
        return []


def health_monitor() -> None:
    """Periodically check the health of Jackett and qBittorrent."""
    while True:
        cfg = load_json(CONFIG_PATH)
        is_healthy = True
        try:
            test_url = cfg["zil_api"] + "/test"
            r = requests.get(test_url, timeout=20)
            is_healthy &= r.status_code == 200
        except Exception:
            is_healthy = False
        try:
            qb_client()
        except Exception:
            is_healthy = False
        if not is_healthy:
            subprocess.run(
                ["notify-send", "TorrentCLI", "Health check failed"], check=False
            )
        time.sleep(cfg.get("health_check_interval", 3600))


def schedule_runner() -> None:
    """Run scheduled downloads based on the defined schedule."""
    while True:
        sched = load_json(SCHEDULE_PATH)
        cfg = load_json(CONFIG_PATH)
        qb = qb_client()
        updated = False
        for task in sched:
            if (
                not task.get("done")
                and datetime.fromisoformat(task["time"]) <= datetime.now()
            ):
                results = fetch(task["query"], task.get("limit", 5))
                if results:
                    mag = results[0].get("MagnetUri") or results[0].get("Link")
                    qb.torrents_add(urls=mag, save_path=cfg["download_path"])
                    task["done"] = True
                    updated = True
        if updated:
            save_json(SCHEDULE_PATH, sched)
        time.sleep(cfg.get("schedule_check_interval", 60))


def show_welcome_banner():
    console.clear()

    INNER_WIDTH = 67  # must match box width minus borders

    def line(content="", style="bold cyan"):
        return Text(f"║ {content.center(INNER_WIDTH)} ║\n", style=style)

    banner = Text()
    banner.append("╔" + "═" * (INNER_WIDTH + 2) + "╗\n", style="bold cyan")

    banner.append(line())
    banner.append(line("██╗  ██╗ █████╗ ██████╗ ██████╗  ██████╗ ████████╗", "bold magenta"))
    banner.append(line("██║  ██║██╔══██╗██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝", "bold magenta"))
    banner.append(line("███████║███████║██████╔╝██████╔╝██║   ██║   ██║", "bold magenta"))
    banner.append(line("╚════██║██╔══██║██╔══██╗██╔══██╗██║   ██║   ██║", "bold magenta"))
    banner.append(line("     ██║██║  ██║██║  ██║██║  ██║╚██████╔╝   ██║", "bold magenta"))
    banner.append(line("     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝    ╚═╝", "bold magenta"))
    banner.append(line())

    banner.append(line("🏴‍☠️  TorrentCLI β — Shadow Terminal Edition  🏴‍☠️", "bold yellow"))
    banner.append(line("ZilTorrent • qBittorrent • Multi-Indexer", "dim white"))
    banner.append(line())

    banner.append("╚" + "═" * (INNER_WIDTH + 2) + "╝\n", style="bold cyan")

    console.print(banner)


def find_torrent_by_name(
    qb: QBClient, search_name: str, max_wait: int = 10
) -> Optional[str]:
    """Find a torrent's hash by matching the torrent name."""
    search_name_lower = search_name.lower()
    for attempt in range(max_wait):
        all_torrents = qb.torrents_info()
        for t in all_torrents:
            torrent_name = safe_str(t.name).lower()
            if (
                search_name_lower in torrent_name
                or torrent_name in search_name_lower
                or any(
                    word in torrent_name
                    for word in search_name_lower.split()
                    if len(word) > 3
                )
            ):
                return t.hash
        time.sleep(1)
    return None


def download_direct_file(result: Dict[str, Any]) -> bool:
    """
    Download a direct file (for LibGen books, etc.)
    Returns:
        True if successful, False otherwise
    """
    cfg = load_json(CONFIG_PATH)
    download_path = Path(
        cfg.get("direct_download_path", DEFAULT_CONFIG["direct_download_path"])
    )
    download_path.mkdir(parents=True, exist_ok=True)
    # Create filename from title and extension
    extra = result.get("extra", {})
    extension = extra.get("extension", "pdf")
    safe_title = "".join(
        c for c in result.get("title", "") if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    safe_title = safe_title[:200]  # Limit filename length
    filename = f"{safe_title}.{extension}"
    destination = download_path / filename
    # Get MD5 from extra data
    md5 = extra.get("md5")
    if not md5:
        console.print(
            Panel(
                "No MD5 hash found for this book. Cannot download.",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False
    # Show info panel
    info_panel = Panel(
        f"[cyan]Title:[/cyan] {result.get('title')}\n"
        f"[cyan]Size:[/cyan] {result.get('size')}\n"
        f"[cyan]Type:[/cyan] Direct Download\n"
        f"[cyan]Extension:[/cyan] {extension}\n"
        f"[cyan]Destination:[/cyan] {destination}",
        title="[bold green]Downloading File[/bold green]",
        border_style="green",
        box=box.ROUNDED,
    )
    console.print(info_panel)
    # Get the actual download URL from the API
    console.print("[dim]→ Getting download URL...[/dim]")
    try:
        api = get_api_client()
        source_hint = ""
        if result.get("source", "").lower().startswith("annas"):
            source_hint = "annasarchive"
        elif result.get("source", "").lower() == "libgen":
            source_hint = "libgen"
        console.print(
            f"[dim]→ Getting download URL (source=auto, hint={source_hint or 'none'})...[/dim]"
        )
        download_url_info = api.get_download_url(
            md5, source="auto", source_hint=source_hint
        )
        download_url = download_url_info.get("download_url") or download_url_info.get(
            "mirror"
        )
        if not download_url:
            console.print(
                Panel(
                    "Could not get download URL from API",
                    title="[bold red]✗ Error[/bold red]",
                    border_style="red",
                )
            )
            return False
        console.print(f"[dim]→ Download URL obtained[/dim]")
    except Exception as e:
        console.print(
            Panel(
                f"Failed to get download URL: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False
    # Download with progress and retry logic
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}[/bold blue]"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                DownloadColumn(),
                TransferSpeedColumn(),
                console=console,
                expand=True,
            ) as progress:
                # Check if partial file exists for resume
                downloaded_size = 0
                if destination.exists():
                    downloaded_size = destination.stat().st_size
                    console.print(f"[yellow]→ Resuming download from {format_size(downloaded_size)}...[/yellow]")
                
                # Prepare headers for resume
                headers = {}
                if downloaded_size > 0:
                    headers['Range'] = f'bytes={downloaded_size}-'
                
                task = progress.add_task(
                    f"Downloading {filename[:40]}...", 
                    total=100,
                    completed=0
                )
                
                # Download file with resume support
                response = requests.get(
                    download_url, 
                    stream=True, 
                    timeout=60,
                    headers=headers,
                    allow_redirects=True
                )
                response.raise_for_status()
                
                # Get total size
                total_size = int(response.headers.get("content-length", 0))
                if downloaded_size > 0 and response.status_code == 206:  # Partial content
                    total_size += downloaded_size
                
                # Open file in append mode if resuming, write mode otherwise
                mode = "ab" if downloaded_size > 0 else "wb"
                
                with open(destination, mode) as f:
                    for chunk in response.iter_content(chunk_size=32768):  # Larger chunk size
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                percentage = (downloaded_size / total_size) * 100
                                progress.update(task, completed=percentage)
                            else:
                                # If we don't know total size, just show as indeterminate
                                progress.update(
                                    task, completed=(downloaded_size / (1024 * 1024)) % 100
                                )
                
                # Download completed successfully, break retry loop
                break
                
        except (requests.exceptions.ChunkedEncodingError, 
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                Exception) as e:
            retry_count += 1
            if retry_count < max_retries:
                console.print(
                    f"[yellow]⚠ Download interrupted: {str(e)[:100]}[/yellow]"
                )
                console.print(
                    f"[yellow]→ Retrying... (attempt {retry_count + 1}/{max_retries})[/yellow]"
                )
                time.sleep(2)  # Wait before retry
            else:
                console.print(
                    Panel(
                        f"Download failed after {max_retries} attempts: {e}",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                # Clean up partial download
                if destination.exists():
                    destination.unlink()
                return False
    
    # Verify file was downloaded
    if not destination.exists():
        console.print(
            Panel(
                "Download file not found after completion",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False
    
    file_size = destination.stat().st_size
    if file_size < 1024:  # Less than 1KB is suspicious
        console.print(
            Panel(
                f"Download may have failed - file size is only {file_size} bytes",
                title="[bold yellow]⚠ Warning[/bold yellow]",
                border_style="yellow",
            )
        )
        if not Confirm.ask("[yellow]Keep this file anyway?[/yellow]"):
            destination.unlink()
            return False
    
    console.print(
        Panel(
            f"[green]✓ Download complete![/green]\n"
            f"[dim]Saved to: {destination}[/dim]\n"
            f"[dim]Size: {format_size(file_size)}[/dim]",
            title="[bold green]Success[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    
    # Add to history
    history = load_json(HISTORY_PATH)
    history.append(
        {
            "title": result.get("title"),
            "time": time.time(),
            "type": "direct",
            "path": str(destination),
            "source": result.get("source"),
            "size": file_size,
        }
    )
    save_json(HISTORY_PATH, history)
    return True


def download_with_progress(item: Dict[str, Any]) -> None:
    """Add a torrent to qBittorrent and track its progress."""
    if item.get("DownloadType") == DownloadType.DIRECT:
        download_direct_file(item)
        return
    cfg = load_json(CONFIG_PATH)
    qb = qb_client()
    # Show torrent info panel
    info_panel = Panel(
        f"[cyan]Title:[/cyan] {safe_str(item.get('Title'))}\n"
        f"[cyan]Size:[/cyan] {safe_str(item.get('Size'))}\n"
        f"[cyan]Seeders:[/cyan] {get_health_icon(item.get('Seeders', 0))} {safe_str(item.get('Seeders', 0))}\n"
        f"[cyan]Leechers:[/cyan] {safe_str(item.get('Leechers', 0))}",
        title="[bold green]Adding Torrent[/bold green]",
        border_style="green",
        box=box.ROUNDED,
    )
    console.print(info_panel)
    active_downloads = qb.torrents_info(filter="downloading")
    if len(active_downloads) >= cfg.get("max_active_downloads", 5):
        console.print(
            Panel(
                f"Maximum active downloads ({cfg.get('max_active_downloads', 5)}) reached.\n"
                "Please wait or increase the limit in config.",
                title="[bold yellow]⚠ Warning[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    mag = item.get("MagnetUri") or item.get("Link")
    if not mag:
        console.print(
            Panel(
                "No magnet link or download link found in torrent data!",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    if not mag.startswith(("magnet:", "http")):
        console.print(
            Panel(
                f"Invalid link format. Link should start with 'magnet:' or 'http'",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    download_path = cfg["download_path"]
    try:
        result = qb.torrents_add(
            urls=mag,
            save_path=download_path,
            use_auto_torrent_management=False,
            is_sequential_download=False,
            is_first_last_piece_priority=False,
        )
    except Exception as e:
        console.print(
            Panel(
                f"Failed to add torrent: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    console.print("[dim]→ Searching for torrent in qBittorrent...[/dim]")
    time.sleep(2)
    name = safe_str(item.get("Title"))
    task_hash = find_torrent_by_name(qb, name, max_wait=15)
    if not task_hash:
        console.print(
            Panel(
                "Could not find the torrent in qBittorrent after adding.",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    console.print(f"[green]✓ Found torrent (hash: {task_hash[:8]}...)[/green]")
    last_state = None
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        BarColumn(bar_width=40),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("↓ [cyan]{task.fields[download_speed]}[/cyan]"),
        TextColumn("↑ [magenta]{task.fields[upload_speed]}[/magenta]"),
        TextColumn("•"),
        TextColumn("[yellow]{task.fields[state]}[/yellow]"),
        TimeElapsedColumn(),
        console=console,
        expand=True,
    ) as progress:
        task = progress.add_task(
            name[:50] + "..." if len(name) > 50 else name,
            total=100,
            download_speed="0 B/s",
            upload_speed="0 B/s",
            state="initializing",
        )
        while not progress.finished:
            try:
                info = qb.torrents_info(torrent_hashes=task_hash)[0]
            except IndexError:
                console.print(
                    Panel(
                        "Torrent disappeared from qBittorrent",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                break
            current_state = safe_str(info.state)
            progress.update(
                task,
                completed=info.progress * 100 if info.progress is not None else 0,
                download_speed=format_speed(info.dlspeed)
                if info.dlspeed is not None
                else "0 B/s",
                upload_speed=format_speed(info.upspeed)
                if info.upspeed is not None
                else "0 B/s",
                state=current_state,
            )
            if last_state != current_state:
                last_state = current_state
            if info.progress >= 1.0 and info.state in ["downloading", "metaDL"]:
                progress.update(task, state="completing")
            elif info.progress >= 1.0 and info.state in [
                "uploading",
                "stalledUP",
                "queuedUP",
            ]:
                break
            elif info.state in ["error"]:
                console.print(
                    Panel(
                        "Torrent encountered an error",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                break
            time.sleep(1)
    console.print(
        Panel(
            f"[green]✓ Download complete![/green]\n"
            f"[dim]Saved to: {download_path}[/dim]",
            title="[bold green]Success[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        )
    )
    history = load_json(HISTORY_PATH)
    history.append({"title": item.get("Title"), "time": time.time(), "hash": task_hash})
    save_json(HISTORY_PATH, history)
    if cfg.get("auto_remove_completed") and task_hash:
        try:
            qb.torrents_delete(torrent_hashes=task_hash, delete_files=False)
            console.print(
                "[dim]→ Automatically removed from qBittorrent (files kept)[/dim]"
            )
        except Exception as e:
            console.print(f"[yellow]⚠ Failed to auto-remove: {e}[/yellow]")


def browse_interactive() -> None:
    """Interactive browse and download."""
    console.print(Rule("[bold cyan]🔍 Torrent & Books Search[/bold cyan]"))
    # Ask for search type
    search_type = Prompt.ask(
        "[cyan]Search type[/cyan]",
        choices=["general", "books", "games", "movies"],
        default="general",
    )
    query = Prompt.ask("[cyan]Enter search query[/cyan]")
    with console.status("[bold green]Searching...", spinner="dots"):
        api = get_api_client()
        if search_type == "books":
            results = api.search_books(query, 50)
        elif search_type == "games":
            results = api.search_games(query, 50)
        elif search_type == "movies":
            results = api.search_movies(query, 50)
        else:
            results = api.search(query, 50)
    if not results:
        console.print(
            Panel(
                "No results found",
                title="[bold yellow]No Results[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    page_size = 10
    page = 0
    while True:
        start = page * page_size
        page_items = results[start : start + page_size]
        total_pages = (len(results) - 1) // page_size + 1
        console.clear()
        console.print(Rule(f"[bold cyan]Results for '{query}'[/bold cyan]"))
        tbl = Table(
            title=f"Page {page + 1}/{total_pages} | Type: {search_type}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
        )
        tbl.add_column("#", style="dim", width=4)
        tbl.add_column("Title", style="white", no_wrap=False)
        tbl.add_column("Size", justify="right", style="green")
        tbl.add_column("Type", justify="center", style="magenta")
        tbl.add_column("Source", justify="center", style="cyan")
        for i, r in enumerate(page_items, start=start + 1):
            download_type_icon = (
                "📦" if r.download_type == DownloadType.DIRECT else "🧲"
            )
            tbl.add_row(str(i), r.title[:70], r.size, download_type_icon, r.source)
        console.print(tbl)
        console.print("\n[dim]📦 = Direct Download | 🧲 = Torrent[/dim]")
        action = Prompt.ask(
            "[cyan]Action[/cyan] [[bold]n[/bold]]ext | [[bold]p[/bold]]rev | [bold]number[/bold] | [[bold]q[/bold]]uit",
            choices=["n", "p", "q"]
            + [str(i) for i in range(start + 1, start + 1 + len(page_items))],
        )
        if action == "n" and start + page_size < len(results):
            page += 1
        elif action == "p" and page > 0:
            page -= 1
        elif action == "q":
            return
        else:
            try:
                idx = int(action) - 1
                item = results[idx]
                # Show details
                details_text = f"[bold cyan]Title:[/bold cyan] {item.title}\n"
                details_text += f"[bold cyan]Size:[/bold cyan] {item.size}\n"
                details_text += f"[bold cyan]Type:[/bold cyan] {'Direct Download 📦' if item.download_type == DownloadType.DIRECT else 'Torrent 🧲'}\n"
                details_text += f"[bold cyan]Source:[/bold cyan] {item.source}\n"
                if item.download_type == DownloadType.DIRECT:
                    # Show book metadata
                    details_text += f"[bold cyan]Authors:[/bold cyan] {item.extra.get('authors', 'N/A')}\n"
                    details_text += f"[bold cyan]Extension:[/bold cyan] {item.extra.get('extension', 'N/A')}\n"
                    details_text += f"[bold cyan]Publisher:[/bold cyan] {item.extra.get('publisher', 'N/A')}\n"
                else:
                    details_text += f"[bold cyan]Seeders:[/bold cyan] {get_health_icon(item.seeders)} {item.seeders}\n"
                console.print(
                    Panel(
                        details_text,
                        title="[bold green]Details[/bold green]",
                        border_style="green",
                    )
                )
                if Confirm.ask("[bold cyan]Download this?[/bold cyan]"):
                    # Convert to dict for download_with_progress
                    item_dict = {
                        "title": item.title,
                        "Title": item.title,  # Keep both for compatibility
                        "Size": item.size,
                        "size": item.size,
                        "Seeders": item.seeders,
                        "Leechers": item.leechers,
                        "DownloadType": item.download_type,  # Keep enum for function logic
                        "download_type": item.download_type.value,  # String value for JSON
                        "download_url": item.download_url,
                        "MagnetUri": item.download_url
                        if item.download_type != DownloadType.DIRECT
                        else None,
                        "Link": item.download_url,
                        "extra": item.extra,
                        "source": item.source,
                    }
                    download_with_progress(item_dict)
                    # Save to last results - convert enums to strings
                    results_dicts = []
                    for r in results:
                        r_dict = r.__dict__.copy()
                        # Convert DownloadType enum to string
                        if "download_type" in r_dict and isinstance(
                            r_dict["download_type"], DownloadType
                        ):
                            r_dict["download_type"] = r_dict["download_type"].value
                        results_dicts.append(r_dict)
                    save_json(LAST_RESULTS, results_dicts)
                    return
            except (ValueError, IndexError) as e:
                console.print(f"[red]✗ Invalid selection: {e}[/red]")


@app.command()
def browse() -> None:
    """🔍 Interactively browse and download torrents."""
    browse_interactive()


@app.command()
def search(query: str, limit: int = 10) -> None:
    """🔎 Search torrents via zil_tor API."""
    console.print(Rule(f"[bold cyan]🔍 Searching for '{query}'[/bold cyan]"))
    with console.status("[bold green]Fetching results...", spinner="dots"):
        results = fetch(query, limit)
    if not results:
        console.print(
            Panel(
                "No results found",
                title="[bold yellow]No Results[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    # Convert to dicts for JSON serialization - handle enums
    results_dicts = []
    for r in results:
        r_dict = r.__dict__.copy()
        # Convert DownloadType enum to string
        if "download_type" in r_dict and isinstance(
            r_dict["download_type"], DownloadType
        ):
            r_dict["download_type"] = r_dict["download_type"].value
        results_dicts.append(r_dict)
    save_json(LAST_RESULTS, results_dicts)
    tbl = Table(
        title=f"Search Results: {query}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Title", style="white", no_wrap=False)
    tbl.add_column("Size", justify="right", style="green")
    tbl.add_column("Seeds", justify="center", style="yellow")
    tbl.add_column("Health", justify="center")
    for i, r in enumerate(results, 1):
        seeders = r.seeders
        health_icon = get_health_icon(seeders)
        tbl.add_row(
            safe_str(i),
            safe_str(r.title)[:80],
            safe_str(r.size),
            safe_str(seeders),
            health_icon,
        )
    console.print(tbl)
    console.print(f"\n[dim]💡 Tip: Use 'download <number>' to download a result[/dim]")


@app.command()
def download(index: int) -> None:
    """⬇️ Download a torrent from the last search by index."""
    results = load_json(LAST_RESULTS)
    if not 1 <= index <= len(results):
        console.print(
            Panel(
                f"Invalid index. Must be between 1 and {len(results)}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    item = results[index - 1]
    # Convert download_type string back to enum if needed
    if "download_type" in item and isinstance(item["download_type"], str):
        if item["download_type"] == "direct":
            item["DownloadType"] = DownloadType.DIRECT
        else:
            item["DownloadType"] = DownloadType.TORRENT
    download_with_progress(item)


@app.command("list")
def list_downloads(
    all_torrents: bool = typer.Option(
        False, "--all", "-a", help="List all torrents, not just active"
    ),
) -> None:
    """📋 List active or all torrents in qBittorrent."""
    with console.status("[bold green]Fetching torrents...", spinner="dots"):
        qb = qb_client()
        torrents = (
            qb.torrents_info()
            if all_torrents
            else qb.torrents_info(filter="downloading")
        )
    title = "All Torrents" if all_torrents else "Active Downloads"
    if not torrents:
        console.print(
            Panel(
                "No torrents found",
                title="[bold yellow]No Torrents[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))
    tbl = Table(
        box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="blue"
    )
    tbl.add_column("Name", style="white", no_wrap=False, max_width=50)
    tbl.add_column("Progress", justify="center", style="green")
    tbl.add_column("Status", justify="center", style="yellow")
    tbl.add_column("Size", justify="right", style="cyan")
    tbl.add_column("Ratio", justify="center", style="magenta")
    tbl.add_column("Hash", justify="right", style="dim")
    for t in torrents:
        name = safe_str(t.name)
        progress_val = f"{t.progress * 100:.1f}%" if t.progress is not None else "0.0%"
        state = safe_str(t.state)
        size = f"{t.size / (1024**3):.2f} GB" if t.size is not None else "N/A"
        ratio = f"{t.ratio:.2f}" if t.ratio is not None else "N/A"
        torrent_hash = safe_str(t.hash)[:8] + "..."
        tbl.add_row(name[:50], progress_val, state, size, ratio, torrent_hash)
    console.print(tbl)


@app.command()
def server_info() -> None:
    """🖥️  Display detailed server and indexer information."""
    console.print(Rule("[bold cyan]🖥️  Server Information[/bold cyan]"))
    try:
        api = get_api_client()
        # Get health, stats, and indexers
        with console.status("[bold green]Fetching server info...", spinner="dots"):
            health = api.health_check()
            stats = api.get_stats()
            indexers = api.get_indexers()
        # Server status panel
        status_color = (
            "green"
            if health["status"] == "healthy"
            else "yellow"
            if health["status"] == "degraded"
            else "red"
        )
        status_icon = (
            "✅"
            if health["status"] == "healthy"
            else "⚠️ "
            if health["status"] == "degraded"
            else "❌"
        )
        server_panel = Panel(
            f"[{status_color}]{status_icon} Status: {health['status'].upper()}[/{status_color}]\n"
            f"[cyan]Uptime:[/cyan] {health.get('uptime', 'N/A')}\n"
            f"[cyan]Version:[/cyan] {stats.get('version', 'N/A')}\n"
            f"[cyan]Memory Usage:[/cyan] {stats.get('memory_mb', 0)} MB\n"
            f"[cyan]Goroutines:[/cyan] {stats.get('goroutines', 0)}\n"
            f"[cyan]Cache:[/cyan] {'✓ Enabled' if health.get('cache_enabled') else '✗ Disabled'} "
            f"({stats.get('cache_size', 0)} entries)\n"
            f"[cyan]Solver:[/cyan] {'✓ Enabled' if health.get('solver_enabled') else '✗ Disabled'}",
            title="[bold]Server Status[/bold]",
            border_style=status_color,
            box=box.ROUNDED,
        )
        console.print(server_panel)
        # Indexers table
        console.print("\n")
        indexer_table = Table(
            title="📡 Indexers Status",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
        )
        indexer_table.add_column("Indexer", style="white")
        indexer_table.add_column("Status", justify="center")
        indexer_table.add_column("Type", justify="center", style="magenta")
        indexer_table.add_column("Health", justify="center")
        # Group indexers by type
        indexer_types = {
            "YTS": "Movies",
            "1337x": "General",
            "Fitgirl": "Games",
            "DODI": "Games",
            "libgen": "Books",
            "annas": "Books",
            "Repacks": "Games",
        }
        healthy_count = 0
        for idx in indexers:
            name = idx.get("name", "Unknown")
            enabled = idx.get("enabled", False)
            healthy = idx.get("healthy", False)
            if healthy:
                healthy_count += 1
            status = "[green]✓ Online[/green]" if healthy else "[red]✗ Offline[/red]"
            health_icon = "🟢" if healthy else "🔴"
            idx_type = indexer_types.get(name, "Other")
            indexer_table.add_row(name, status, idx_type, health_icon)
        console.print(indexer_table)
        # Summary
        summary_text = Text()
        summary_text.append(f"\n📊 Summary: ", style="bold cyan")
        summary_text.append(f"{healthy_count}/{len(indexers)} ", style="bold green")
        summary_text.append(f"indexers online", style="dim")
        console.print(summary_text)
    except APIError as e:
        console.print(
            Panel(
                f"Failed to connect to server: {e}",
                title="[bold red]✗ Connection Error[/bold red]",
                border_style="red",
            )
        )


@app.command()
def search_movies(query: str, limit: int = 10) -> None:
    """🎬 Search specifically for movies."""
    console.print(Rule(f"[bold cyan]🎬 Searching movies for '{query}'[/bold cyan]"))
    with console.status("[bold green]Fetching movies...", spinner="dots"):
        api = get_api_client()
        results = api.search_movies(query, limit)
    if not results:
        console.print(
            Panel(
                "No movies found",
                title="[bold yellow]No Results[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    # Convert to dicts for JSON serialization
    results_dicts = [r.__dict__ for r in results]
    save_json(LAST_RESULTS, results_dicts)
    tbl = Table(
        title=f"🎬 Movie Results: {query}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="blue",
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Title", style="white", no_wrap=False)
    tbl.add_column("Size", justify="right", style="green")
    tbl.add_column("Quality", justify="center", style="yellow")
    tbl.add_column("Seeds", justify="center", style="yellow")
    tbl.add_column("Source", justify="center", style="magenta")
    for i, r in enumerate(results, 1):
        seeders = r.seeders
        health_icon = get_health_icon(seeders)
        # Try to extract quality from title
        quality = "N/A"
        title = r.title.lower()
        if "2160p" in title or "4k" in title:
            quality = "4K"
        elif "1080p" in title:
            quality = "1080p"
        elif "720p" in title:
            quality = "720p"
        elif "480p" in title:
            quality = "480p"
        tbl.add_row(
            str(i), r.title[:70], r.size, quality, f"{health_icon} {seeders}", r.source
        )
    console.print(tbl)
    console.print(f"\n[dim]💡 Tip: Use 'download <number>' to download a movie[/dim]")


@app.command()
def browse_category(
    category: str = typer.Argument(
        ..., help="Category to browse (movies, books, games)"
    ),
    limit: int = 20,
) -> None:
    """🗂️  Browse content by category without search."""
    console.print(Rule(f"[bold cyan]🗂️  Browsing {category.title()}[/bold cyan]"))
    api = get_api_client()
    try:
        with console.status(f"[bold green]Loading {category}...", spinner="dots"):
            if category.lower() == "games":
                results = api.get_latest_games(limit)
                title = "🎮 Latest Game Repacks"
            elif category.lower() == "movies":
                # For movies, we'd need a "popular" or "latest" endpoint
                # For now, show a helpful message
                console.print(
                    Panel(
                        "Use 'search-movies <query>' to search for movies\n"
                        'Example: search-movies "action"',
                        title="[bold yellow]Info[/bold yellow]",
                        border_style="yellow",
                    )
                )
                return
            elif category.lower() == "books":
                console.print(
                    Panel(
                        "Use 'browse' command and select 'books' search type",
                        title="[bold yellow]Info[/bold yellow]",
                        border_style="yellow",
                    )
                )
                return
            else:
                console.print(
                    Panel(
                        f"Unknown category: {category}\n"
                        "Available: movies, books, games",
                        title="[bold red]Error[/bold red]",
                        border_style="red",
                    )
                )
                return
        if not results:
            console.print(
                Panel(
                    f"No {category} found",
                    title="[bold yellow]No Results[/bold yellow]",
                    border_style="yellow",
                )
            )
            return
        # Display results
        tbl = Table(
            title=title,
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
        )
        tbl.add_column("#", style="dim", width=4)
        tbl.add_column("Title", style="white", no_wrap=False, max_width=60)
        tbl.add_column("Size", justify="right", style="green")
        tbl.add_column("Date", justify="center", style="yellow")
        tbl.add_column("Source", justify="center", style="magenta")
        results_dicts = [r.__dict__ for r in results]
        save_json(LAST_RESULTS, results_dicts)
        for i, r in enumerate(results, 1):
            tbl.add_row(
                str(i),
                r.title[:60],
                r.size,
                r.publish_date[:10] if r.publish_date else "N/A",
                r.source,
            )
        console.print(tbl)
        console.print(f"\n[dim]💡 Tip: Use 'download <number>' to download[/dim]")
    except APIError as e:
        console.print(
            Panel(
                f"Failed to browse {category}: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )


@app.command()
def dashboard() -> None:
    """📊 Show comprehensive dashboard with server status and recent activity."""
    console.clear()
    console.print(Rule("[bold cyan]📊 TorrentCLI Dashboard[/bold cyan]"))
    try:
        api = get_api_client()
        qb = qb_client()
        with console.status("[bold green]Loading dashboard...", spinner="dots"):
            # Get API info
            health = api.health_check()
            stats = api.get_stats()
            indexers = api.get_indexers()
            # Get qBittorrent info
            torrents = qb.torrents_info()
            active_torrents = [
                t for t in torrents if t.state in ["downloading", "uploading"]
            ]
            # Get history
            hist = load_json(HISTORY_PATH)
            recent_hist = hist[-5:] if len(hist) > 0 else []
        # Create layout
        layout = Layout()
        layout.split_column(Layout(name="header", size=7), Layout(name="body"))
        layout["body"].split_row(Layout(name="left"), Layout(name="right"))
        # Header: Server status
        status_color = "green" if health["status"] == "healthy" else "yellow"
        header_text = Text()
        header_text.append("🖥️  Server Status: ", style="bold cyan")
        header_text.append(f"{health['status'].upper()}", style=f"bold {status_color}")
        header_text.append(f"\n⏱️  Uptime: {health.get('uptime', 'N/A')}", style="cyan")
        header_text.append(f" | 💾 Memory: {stats.get('memory_mb', 0)}MB", style="cyan")
        header_text.append(
            f" | 📡 Indexers: {health.get('healthy_count')}/{health.get('total_indexers')}",
            style="cyan",
        )
        layout["header"].update(
            Panel(Align.center(header_text), border_style=status_color, box=box.HEAVY)
        )
        # Left: Active torrents
        active_table = Table(
            title="🔄 Active Downloads",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold cyan",
        )
        active_table.add_column("Name", no_wrap=False, max_width=40)
        active_table.add_column("Progress", justify="center")
        if active_torrents:
            for t in active_torrents[:5]:
                progress = f"{t.progress * 100:.1f}%" if t.progress else "0%"
                active_table.add_row(t.name[:40], f"[green]{progress}[/green]")
        else:
            active_table.add_row("[dim]No active downloads[/dim]", "")
        layout["left"].update(Panel(active_table, border_style="blue"))
        # Right: Recent downloads
        history_table = Table(
            title="📜 Recent Downloads",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold cyan",
        )
        history_table.add_column("Title", no_wrap=False, max_width=40)
        history_table.add_column("Time", justify="right")
        if recent_hist:
            for entry in reversed(recent_hist):
                time_str = datetime.fromtimestamp(entry.get("time", 0)).strftime(
                    "%m/%d %H:%M"
                )
                history_table.add_row(entry.get("title", "")[:40], time_str)
        else:
            history_table.add_row("[dim]No download history[/dim]", "")
        layout["right"].update(Panel(history_table, border_style="blue"))
        console.print(layout)
        # Quick stats bar
        stats_text = Text()
        stats_text.append(f"\n📊 Total Downloads: ", style="bold")
        stats_text.append(f"{len(hist)}", style="green")
        stats_text.append(f"  |  📦 Active: ", style="bold")
        stats_text.append(f"{len(active_torrents)}", style="yellow")
        stats_text.append(f"  |  💾 Cache: ", style="bold")
        stats_text.append(f"{stats.get('cache_size', 0)} entries", style="cyan")
        console.print(Align.center(stats_text))
    except Exception as e:
        console.print(
            Panel(
                f"Failed to load dashboard: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )


@app.command()
def quick_search() -> None:
    """⚡ Quick interactive search with category selection."""
    console.print(Rule("[bold cyan]⚡ Quick Search[/bold cyan]"))
    # Category selection with icons
    category_map = {
        "1": ("movies", "🎬 Movies"),
        "2": ("books", "📚 Books"),
        "3": ("games", "🎮 Games"),
        "4": ("", "🌐 All Categories"),
    }
    console.print("\n[bold cyan]Select Category:[/bold cyan]")
    for key, (_, display) in category_map.items():
        console.print(f"  [{key}] {display}")
    choice = Prompt.ask(
        "\n[cyan]Category[/cyan]", choices=list(category_map.keys()), default="4"
    )
    category_value, category_name = category_map[choice]
    query = Prompt.ask(f"\n[cyan]Search {category_name}[/cyan]")
    with console.status(f"[bold green]Searching {category_name}...", spinner="dots"):
        api = get_api_client()
        if category_value == "movies":
            results = api.search_movies(query, 20)
        elif category_value == "books":
            results = api.search_books(query, 20)
        elif category_value == "games":
            results = api.search_games(query, 20)
        else:
            results = api.search(query, 20)
    if not results:
        console.print(
            Panel(
                "No results found",
                title="[bold yellow]No Results[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    results_dicts = [r.__dict__ for r in results]
    save_json(LAST_RESULTS, results_dicts)
    # Show top 5 results
    console.print(f"\n[bold green]Found {len(results)} results[/bold green]\n")
    for i, r in enumerate(results[:5], 1):
        type_icon = "📦" if r.is_direct_download() else "🧲"
        health = get_health_icon(r.seeders) if not r.is_direct_download() else ""
        console.print(f"[bold cyan]{i}.[/bold cyan] {r.title[:70]}")
        console.print(f"   {type_icon} Size: {r.size} {health}")
        console.print()
    if len(results) > 5:
        console.print(f"[dim]... and {len(results) - 5} more results[/dim]\n")
    if Confirm.ask("[cyan]Download first result?[/cyan]"):
        download_with_progress(results_dicts[0])


@app.command()
def remove(
    hash_or_name: str = typer.Argument(
        ..., help="Torrent hash or part of the name to remove"
    ),
    delete_files: bool = typer.Option(
        False, "--files", "-f", help="Also delete associated files"
    ),
) -> None:
    """🗑️ Remove a torrent by its hash or part of its name."""
    qb = qb_client()
    torrents_to_remove = []
    if len(hash_or_name) == 40 and all(
        c in "0123456789abcdefABCDEF" for c in hash_or_name
    ):
        torrents_to_remove = qb.torrents_info(torrent_hashes=hash_or_name)
    else:
        all_torrents = qb.torrents_info()
        torrents_to_remove = [
            t for t in all_torrents if hash_or_name.lower() in safe_str(t.name).lower()
        ]
    if not torrents_to_remove:
        console.print(
            Panel(
                f"No torrent found matching '{hash_or_name}'",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    if len(torrents_to_remove) > 1:
        console.print(
            Panel(
                "Multiple torrents found matching your query",
                title="[bold yellow]⚠ Multiple Matches[/bold yellow]",
                border_style="yellow",
            )
        )
        tbl = Table(box=box.ROUNDED, border_style="blue")
        tbl.add_column("#", style="cyan")
        tbl.add_column("Name", style="white")
        tbl.add_column("Hash", style="dim")
        for i, t in enumerate(torrents_to_remove):
            tbl.add_row(str(i + 1), safe_str(t.name)[:60], safe_str(t.hash)[:8] + "...")
        console.print(tbl)
        while True:
            choice = Prompt.ask(
                "[cyan]Enter number to remove, or 'q' to quit[/cyan]",
                choices=[str(i + 1) for i in range(len(torrents_to_remove))] + ["q"],
            )
            if choice == "q":
                console.print("[yellow]Removal cancelled[/yellow]")
                return
            try:
                selected_torrent = torrents_to_remove[int(choice) - 1]
                break
            except (ValueError, IndexError):
                console.print("[red]Invalid choice. Please try again.[/red]")
    else:
        selected_torrent = torrents_to_remove[0]
    warning_text = (
        f"Remove '{safe_str(selected_torrent.name)}'?\n"
        f"Hash: {safe_str(selected_torrent.hash)[:16]}...\n"
    )
    if delete_files:
        warning_text += "\n[bold red]⚠️ Files will also be deleted![/bold red]"
    if Confirm.ask(
        Panel(
            warning_text,
            title="[bold red]Confirm Removal[/bold red]",
            border_style="red",
        )
    ):
        qb.torrents_delete(
            torrent_hashes=selected_torrent.hash, delete_files=delete_files
        )
        console.print(
            Panel(
                f"Removed '{safe_str(selected_torrent.name)}'",
                title="[bold green]✓ Success[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print("[yellow]Removal cancelled[/yellow]")


@app.command()
def pause(
    hash_or_name: str = typer.Argument(
        ..., help="Torrent hash or part of the name to pause"
    ),
) -> None:
    """⏸️ Pause a torrent by hash or name."""
    qb = qb_client()
    torrents_to_pause = []
    if len(hash_or_name) == 40 and all(
        c in "0123456789abcdefABCDEF" for c in hash_or_name
    ):
        torrents_to_pause = qb.torrents_info(torrent_hashes=hash_or_name)
    else:
        all_torrents = qb.torrents_info()
        torrents_to_pause = [
            t for t in all_torrents if hash_or_name.lower() in safe_str(t.name).lower()
        ]
    if not torrents_to_pause:
        console.print(
            Panel(
                f"No torrent found matching '{hash_or_name}'",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    if len(torrents_to_pause) > 1:
        tbl = Table(box=box.ROUNDED)
        tbl.add_column("#", style="cyan")
        tbl.add_column("Name")
        tbl.add_column("Hash", style="dim")
        for i, t in enumerate(torrents_to_pause):
            tbl.add_row(str(i + 1), safe_str(t.name)[:60], safe_str(t.hash)[:8] + "...")
        console.print(tbl)
        while True:
            choice = Prompt.ask(
                "[cyan]Enter number to pause, or 'q' to quit[/cyan]",
                choices=[str(i + 1) for i in range(len(torrents_to_pause))] + ["q"],
            )
            if choice == "q":
                console.print("[yellow]Pause cancelled[/yellow]")
                return
            try:
                selected_torrent = torrents_to_pause[int(choice) - 1]
                break
            except (ValueError, IndexError):
                console.print("[red]Invalid choice[/red]")
    else:
        selected_torrent = torrents_to_pause[0]
    qb.torrents_pause(torrent_hashes=selected_torrent.hash)
    console.print(
        Panel(
            f"Paused '{safe_str(selected_torrent.name)}'",
            title="[bold green]✓ Success[/bold green]",
            border_style="green",
        )
    )


@app.command()
def resume(
    hash_or_name: str = typer.Argument(
        ..., help="Torrent hash or part of the name to resume"
    ),
) -> None:
    """▶️ Resume a torrent by hash or name."""
    qb = qb_client()
    torrents_to_resume = []
    if len(hash_or_name) == 40 and all(
        c in "0123456789abcdefABCDEF" for c in hash_or_name
    ):
        torrents_to_resume = qb.torrents_info(torrent_hashes=hash_or_name)
    else:
        all_torrents = qb.torrents_info()
        torrents_to_resume = [
            t for t in all_torrents if hash_or_name.lower() in safe_str(t.name).lower()
        ]
    if not torrents_to_resume:
        console.print(
            Panel(
                f"No torrent found matching '{hash_or_name}'",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    if len(torrents_to_resume) > 1:
        tbl = Table(box=box.ROUNDED)
        tbl.add_column("#", style="cyan")
        tbl.add_column("Name")
        tbl.add_column("Hash", style="dim")
        for i, t in enumerate(torrents_to_resume):
            tbl.add_row(str(i + 1), safe_str(t.name)[:60], safe_str(t.hash)[:8] + "...")
        console.print(tbl)
        while True:
            choice = Prompt.ask(
                "[cyan]Enter number to resume, or 'q' to quit[/cyan]",
                choices=[str(i + 1) for i in range(len(torrents_to_resume))] + ["q"],
            )
            if choice == "q":
                console.print("[yellow]Resume cancelled[/yellow]")
                return
            try:
                selected_torrent = torrents_to_resume[int(choice) - 1]
                break
            except (ValueError, IndexError):
                console.print("[red]Invalid choice[/red]")
    else:
        selected_torrent = torrents_to_resume[0]
    qb.torrents_resume(torrent_hashes=selected_torrent.hash)
    console.print(
        Panel(
            f"Resumed '{safe_str(selected_torrent.name)}'",
            title="[bold green]✓ Success[/bold green]",
            border_style="green",
        )
    )


@app.command()
def set_priority(
    hash_or_name: str = typer.Argument(..., help="Torrent hash or part of the name"),
    priority: int = typer.Argument(
        0, help="Priority (0=Do not download, 1=Normal, 2=High, etc.)"
    ),
) -> None:
    """⚡ Set the download priority of a torrent."""
    qb = qb_client()
    torrents_to_prioritize = []
    if len(hash_or_name) == 40 and all(
        c in "0123456789abcdefABCDEF" for c in hash_or_name
    ):
        torrents_to_prioritize = qb.torrents_info(torrent_hashes=hash_or_name)
    else:
        all_torrents = qb.torrents_info()
        torrents_to_prioritize = [
            t for t in all_torrents if hash_or_name.lower() in safe_str(t.name).lower()
        ]
    if not torrents_to_prioritize:
        console.print(
            Panel(
                f"No torrent found matching '{hash_or_name}'",
                title="[bold yellow]Not Found[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    if len(torrents_to_prioritize) > 1:
        tbl = Table(box=box.ROUNDED)
        tbl.add_column("#", style="cyan")
        tbl.add_column("Name")
        tbl.add_column("Hash", style="dim")
        for i, t in enumerate(torrents_to_prioritize):
            tbl.add_row(str(i + 1), safe_str(t.name)[:60], safe_str(t.hash)[:8] + "...")
        console.print(tbl)
        while True:
            choice = Prompt.ask(
                "[cyan]Enter number to set priority, or 'q' to quit[/cyan]",
                choices=[str(i + 1) for i in range(len(torrents_to_prioritize))]
                + ["q"],
            )
            if choice == "q":
                console.print("[yellow]Priority setting cancelled[/yellow]")
                return
            try:
                selected_torrent = torrents_to_prioritize[int(choice) - 1]
                break
            except (ValueError, IndexError):
                console.print("[red]Invalid choice[/red]")
    else:
        selected_torrent = torrents_to_prioritize[0]
    qb.torrents_set_priority(torrent_hashes=selected_torrent.hash, priority=priority)
    console.print(
        Panel(
            f"Set priority of '{safe_str(selected_torrent.name)}' to {priority}",
            title="[bold green]✓ Success[/bold green]",
            border_style="green",
        )
    )


@app.command()
def stats(days: int = typer.Option(7, help="Last N days stats")) -> None:
    """📊 Display statistics for downloads in the last N days."""
    hist = load_json(HISTORY_PATH)
    cutoff = time.time() - days * 86400
    recent = [e for e in hist if e.get("time", 0) >= cutoff]
    cnt = len(recent)
    console.print(Rule(f"[bold cyan]📊 Download Statistics[/bold cyan]"))
    stats_panel = Panel(
        f"[cyan]Downloads in last {days} days:[/cyan] [bold green]{cnt}[/bold green]\n"
        f"[cyan]Total downloads (all time):[/cyan] [bold]{len(hist)}[/bold]\n"
        f"[cyan]Average per day:[/cyan] [bold]{cnt / days:.1f}[/bold]",
        title="[bold]Statistics[/bold]",
        border_style="cyan",
        box=box.ROUNDED,
    )
    console.print(stats_panel)


@app.command()
def api_status() -> None:
    """📊 Show Go API status and indexers."""
    try:
        api = get_api_client()
        # Health check
        health = api.health_check()
        indexers = api.get_indexers()
        stats = api.get_stats()
        console.print(Rule("[bold cyan]📊 Go API Status[/bold cyan]"))
        # Overall health
        status_color = (
            "green"
            if health["status"] == "healthy"
            else "yellow"
            if health["status"] == "degraded"
            else "red"
        )
        console.print(
            Panel(
                f"[{status_color}]Status: {health['status'].upper()}[/{status_color}]\n"
                f"Healthy Indexers: {health['healthy_count']}/{health['total_indexers']}\n"
                f"Uptime: {health.get('uptime', 'N/A')}\n"
                f"Cache: {'✓ Enabled' if health.get('cache_enabled') else '✗ Disabled'}",
                title="[bold]API Health[/bold]",
                border_style=status_color,
            )
        )
    except APIError as e:
        console.print(
            Panel(
                f"Failed to connect to API: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )


@app.command()
def history() -> None:
    """📜 Show download history."""
    hist = load_json(HISTORY_PATH)
    if not hist:
        console.print(
            Panel(
                "No download history found",
                title="[bold yellow]Empty History[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    console.print(Rule("[bold cyan]📜 Download History[/bold cyan]"))
    tbl = Table(
        box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="blue"
    )
    tbl.add_column("Time", style="green")
    tbl.add_column("Title", style="white", no_wrap=False, max_width=60)
    tbl.add_column("Hash", justify="right", style="dim")
    # Show most recent first
    for e in reversed(hist[-50:]):  # Last 50 entries
        time_str = (
            datetime.fromtimestamp(e.get("time", 0)).strftime("%Y-%m-%d %H:%M")
            if e.get("time") is not None
            else "Unknown"
        )
        tbl.add_row(
            time_str,
            safe_str(e.get("title"))[:60],
            safe_str(e.get("hash", "N/A"))[:8] + "...",
        )
    console.print(tbl)
    console.print(
        f"\n[dim]Showing last {min(50, len(hist))} of {len(hist)} total downloads[/dim]"
    )


@app.command()
def config() -> None:
    """⚙️ Show the current configuration."""
    console.print(Rule("[bold cyan]⚙️ Current Configuration[/bold cyan]"))
    cfg = load_json(CONFIG_PATH)
    # Create a formatted display
    config_text = ""
    for key, value in cfg.items():
        if isinstance(value, dict):
            config_text += f"[bold cyan]{key}:[/bold cyan]\n"
            for sub_key, sub_value in value.items():
                # Mask password
                if sub_key == "password":
                    sub_value = "***"
                config_text += f"  [yellow]{sub_key}:[/yellow] {sub_value}\n"
        else:
            config_text += f"[bold cyan]{key}:[/bold cyan] {value}\n"
    console.print(
        Panel(
            config_text.strip(),
            title="[bold]Configuration[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


@app.command()
def set_config(
    key: str = typer.Argument(
        ..., help="Configuration key (e.g., download_path or qbittorrent.host)"
    ),
    value: str = typer.Argument(..., help="Value to set for the configuration key"),
) -> None:
    """⚙️ Update configuration settings."""
    cfg = load_json(CONFIG_PATH)
    keys = key.split(".")
    temp_cfg = cfg
    for i, k in enumerate(keys):
        if i == len(keys) - 1:
            try:
                if isinstance(temp_cfg, dict):
                    # Convert to proper type when possible
                    if k in [
                        "health_check_interval",
                        "schedule_check_interval",
                        "max_active_downloads",
                    ]:
                        temp_cfg[k] = int(value)
                    elif k == "auto_remove_completed":
                        temp_cfg[k] = value.lower() == "true"
                    else:
                        temp_cfg[k] = value
                    console.print(
                        Panel(
                            f"[cyan]Key:[/cyan] {key}\n[cyan]Value:[/cyan] {value}",
                            title="[bold green]✓ Config Updated[/bold green]",
                            border_style="green",
                        )
                    )
                else:
                    raise TypeError(f"Cannot set key '{k}' on a non-dictionary object.")
            except ValueError:
                console.print(
                    Panel(
                        f"Invalid value '{value}' for key '{k}'. Expected an integer.",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                return
            except TypeError as e:
                console.print(
                    Panel(
                        f"Error setting config key '{key}': {e}",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                return
        else:
            if k not in temp_cfg or not isinstance(temp_cfg[k], dict):
                temp_cfg[k] = {}
            temp_cfg = temp_cfg[k]
    save_json(CONFIG_PATH, cfg)


@app.command()
def schedule_add(
    query: str = typer.Argument(..., help="Search query for the scheduled download"),
    when: str = typer.Argument(..., help="ISO 8601 time (e.g., '2025-05-20T14:30:00')"),
    limit: int = typer.Option(
        5, "--limit", "-l", help="Limit results for the scheduled search"
    ),
) -> None:
    """📅 Add a new scheduled download."""
    try:
        datetime.fromisoformat(when)
    except ValueError:
        console.print(
            Panel(
                "Invalid ISO 8601 time format.\nExample: '2025-05-20T14:30:00'",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    sched = load_json(SCHEDULE_PATH)
    sched.append({"query": query, "time": when, "done": False, "limit": limit})
    save_json(SCHEDULE_PATH, sched)
    console.print(
        Panel(
            f"[cyan]Query:[/cyan] {query}\n"
            f"[cyan]Scheduled for:[/cyan] {when}\n"
            f"[cyan]Result limit:[/cyan] {limit}",
            title="[bold green]✓ Schedule Added[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        )
    )


@app.command()
def schedule_list() -> None:
    """📅 List all scheduled downloads."""
    sched = load_json(SCHEDULE_PATH)
    if not sched:
        console.print(
            Panel(
                "No scheduled downloads",
                title="[bold yellow]Empty Schedule[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    console.print(Rule("[bold cyan]📅 Scheduled Downloads[/bold cyan]"))
    tbl = Table(
        box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="blue"
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Query", style="white")
    tbl.add_column("Time", style="yellow")
    tbl.add_column("Status", justify="center")
    for i, task in enumerate(sched, 1):
        status = (
            "[green]✓ Done[/green]"
            if task.get("done")
            else "[yellow]⏳ Pending[/yellow]"
        )
        tbl.add_row(
            str(i), safe_str(task.get("query")), safe_str(task.get("time")), status
        )
    console.print(tbl)


@app.command()
def schedule_remove(
    index: int = typer.Argument(..., help="Index of the scheduled task to remove"),
) -> None:
    """🗑️ Remove a scheduled download by its index."""
    sched = load_json(SCHEDULE_PATH)
    if not 1 <= index <= len(sched):
        console.print(
            Panel(
                f"Invalid schedule index. Must be between 1 and {len(sched)}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return
    removed_task = sched.pop(index - 1)
    save_json(SCHEDULE_PATH, sched)
    console.print(
        Panel(
            f"[cyan]Query:[/cyan] {safe_str(removed_task.get('query'))}\n"
            f"[cyan]Time:[/cyan] {safe_str(removed_task.get('time'))}",
            title="[bold green]✓ Schedule Removed[/bold green]",
            border_style="green",
        )
    )


@app.command()
def top_torrents(limit: int = 10) -> None:
    """🏆 Display the top torrents from the last search (by seeders)."""
    results = load_json(LAST_RESULTS)
    if not results:
        console.print(
            Panel(
                "No recent search results.\nPlease run 'search' first.",
                title="[bold yellow]No Data[/bold yellow]",
                border_style="yellow",
            )
        )
        return
    sorted_results = sorted(results, key=lambda x: x.get("seeders", 0), reverse=True)
    console.print(Rule(f"[bold cyan]🏆 Top {limit} Torrents by Seeders[/bold cyan]"))
    tbl = Table(
        box=box.ROUNDED, show_header=True, header_style="bold cyan", border_style="blue"
    )
    tbl.add_column("Rank", style="yellow", justify="center", width=6)
    tbl.add_column("Title", style="white", no_wrap=False)
    tbl.add_column("Size", justify="right", style="green")
    tbl.add_column("Seeds", justify="center", style="yellow")
    tbl.add_column("Health", justify="center")
    for i, r in enumerate(sorted_results[:limit], 1):
        seeders = r.get("seeders", 0)
        health_icon = get_health_icon(seeders)
        # Medal for top 3
        rank = ""
        if i == 1:
            rank = "🥇"
        elif i == 2:
            rank = "🥈"
        elif i == 3:
            rank = "🥉"
        else:
            rank = str(i)
        tbl.add_row(
            rank,
            safe_str(r.get("title"))[:70],
            safe_str(r.get("size")),
            safe_str(seeders),
            health_icon,
        )
    console.print(tbl)


if __name__ == "__main__":
    # Start background threads
    threading.Thread(target=health_monitor, daemon=True).start()
    threading.Thread(target=schedule_runner, daemon=True).start()
    # Show welcome only when launched without arguments
    if len(sys.argv) == 1:
        show_welcome_banner()
        # Prompt for command
        user_command = Prompt.ask(
            "\n[bold cyan]Enter command[/bold cyan]",
            default="browse"
        )
        if user_command:
            # Insert the command into sys.argv for Typer to process
            sys.argv.append(user_command)
    app()
