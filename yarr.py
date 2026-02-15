#!/usr/bin/env python3
"""
Yarr - Enhanced TUI Torrent CLI 🏴‍☠️
A beautiful command-line interface for torrents, books, movies, and games.
With improved error handling, modern design, and smooth user experience.
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
from rich.tree import Tree
from rich.columns import Columns
from rich.markdown import Markdown
from typing import Any, Dict, List, Optional
from zil_api_client import GoTorrentAPI, SearchResult, DownloadType, APIError

install()
app = typer.Typer(add_completion=False)
console = Console()

# Configuration
HOME = Path.home()
CONFIG_DIR = HOME / ".yarr"
CONFIG_PATH = CONFIG_DIR / "config.json"
HISTORY_PATH = CONFIG_DIR / "history.json"
SCHEDULE_PATH = CONFIG_DIR / "schedule.json"
LAST_RESULTS = CONFIG_DIR / "last.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "download_path": str(HOME / "Downloads" / "Torrents"),
    "zil_api": "http://127.0.0.1:9117",
    "qbittorrent": {
        "host": "http://127.0.0.1:8080",
        "username": "admin",
        "password": "adminpass",
    },
    "health_check_interval": 3600,
    "schedule_check_interval": 60,
    "max_active_downloads": 5,
    "auto_remove_completed": False,
    "direct_download_path": str(HOME / "Downloads" / "Books"),
    "theme": "dark",
}


def ensure_files() -> None:
    """Ensure directories and configuration files exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Create config if it doesn't exist
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))

    # Load config directly (no recursion)
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        cfg = DEFAULT_CONFIG
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))

    # Ensure download directories exist
    Path(cfg["download_path"]).mkdir(parents=True, exist_ok=True)
    Path(cfg.get("direct_download_path", DEFAULT_CONFIG["direct_download_path"])).mkdir(
        parents=True, exist_ok=True
    )

    # Create history/schedule files
    for p in (HISTORY_PATH, SCHEDULE_PATH, LAST_RESULTS):
        if not p.exists():
            p.write_text(json.dumps([], indent=2))


def load_json(path: Path) -> Any:
    """Load JSON data from file."""
    if not path.exists():
        ensure_files()

    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return (
            []
            if path.name in ["history.json", "schedule.json", "last.json"]
            else DEFAULT_CONFIG
        )


def save_json(path: Path, data: Any) -> None:
    """Save JSON data to file."""
    ensure_files()
    path.write_text(json.dumps(data, indent=2))


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string."""
    return str(value) if value is not None else default


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_speed(speed_bytes: int) -> str:
    """Format speed to human readable."""
    return f"{format_size(speed_bytes)}/s"


def get_health_icon(value: int, thresholds: tuple = (10, 50)) -> str:
    """Get health indicator icon."""
    if value >= thresholds[1]:
        return "🟢"
    elif value >= thresholds[0]:
        return "🟡"
    return "🔴"


def get_api_client() -> GoTorrentAPI:
    """Get configured API client with error handling."""
    cfg = load_json(CONFIG_PATH)
    api_url = cfg.get("zil_api", DEFAULT_CONFIG["zil_api"])
    return GoTorrentAPI(api_url)


def qb_client() -> QBClient:
    """Get authenticated qBittorrent client."""
    cfg = load_json(CONFIG_PATH)
    qb_cfg = cfg["qbittorrent"]
    try:
        qb = QBClient(
            host=qb_cfg["host"],
            username=qb_cfg["username"],
            password=qb_cfg["password"],
            VERIFY_WEBUI_CERTIFICATE=False,
        )
        qb.auth_log_in()
        return qb
    except Exception as e:
        console.print(
            Panel(
                f"[red]Failed to connect to qBittorrent[/red]\n"
                f"[dim]Error: {e}[/dim]\n\n"
                f"[yellow]Check:[/yellow]\n"
                f"• Is qBittorrent running?\n"
                f"• Is Web UI enabled?\n"
                f"• Are credentials correct?",
                title="[bold red]Connection Error[/bold red]",
                border_style="red",
                box=box.ROUNDED,
            )
        )
        raise typer.Exit(1)


def show_welcome_banner():
    """Display enhanced welcome banner."""
    console.clear()

    banner = Text()
    banner.append("\n")
    banner.append(
        "    ╔════════════════════════════════════════════════════════════════╗\n",
        style="bold cyan",
    )
    banner.append(
        "    ║                                                                ║\n",
        style="bold cyan",
    )
    banner.append(
        "    ║        ██╗   ██╗ █████╗ ██████╗ ██████╗                       ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║        ╚██╗ ██╔╝██╔══██╗██╔══██╗██╔══██╗                      ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║         ╚████╔╝ ███████║██████╔╝██████╔╝                      ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║          ╚██╔╝  ██╔══██║██╔══██╗██╔══██╗                      ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║           ██║   ██║  ██║██║  ██║██║  ██║                      ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║           ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝                      ║\n",
        style="bold magenta",
    )
    banner.append(
        "    ║                                                                ║\n",
        style="bold cyan",
    )
    banner.append(
        "    ║              🏴‍☠️  The Pirate's Terminal  🏴‍☠️                    ║\n",
        style="bold yellow",
    )
    banner.append(
        "    ║                                                                ║\n",
        style="bold cyan",
    )
    banner.append(
        "    ║           Torrents • Books • Movies • Games                    ║\n",
        style="dim white",
    )
    banner.append(
        "    ║                   Powered by ZilTor                            ║\n",
        style="dim white",
    )
    banner.append(
        "    ║                                                                ║\n",
        style="bold cyan",
    )
    banner.append(
        "    ╚════════════════════════════════════════════════════════════════╝\n",
        style="bold cyan",
    )

    console.print(Align.center(banner))

    # Quick stats
    try:
        api = get_api_client()
        health = api.health_check()

        stats = Table.grid(padding=(0, 2))
        stats.add_column(justify="center")
        stats.add_column(justify="center")
        stats.add_column(justify="center")

        status_icon = "✅" if health.get("status") == "healthy" else "⚠️"
        healthy_count = health.get("healthy_count", 0)
        total_count = health.get("total_indexers", 0)

        stats.add_row(
            f"[green]{status_icon} API Online[/green]",
            f"[cyan]📡 {healthy_count}/{total_count} Indexers[/cyan]",
            f"[yellow]⚡ Ready[/yellow]",
        )

        console.print(Align.center(stats))
    except APIError as e:
        console.print(
            Align.center(f"[red]✗ API Offline[/red] [dim]({str(e)[:50]})[/dim]")
        )
    except Exception as e:
        console.print(
            Align.center(
                f"[yellow]⚠ API Status Unknown[/yellow] [dim]({str(e)[:30]})[/dim]"
            )
        )

    console.print()


def find_torrent_by_name(
    qb: QBClient, search_name: str, max_wait: int = 10
) -> Optional[str]:
    """Find torrent hash by name with fuzzy matching."""
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
    """Download direct file with resume support and progress tracking."""
    cfg = load_json(CONFIG_PATH)
    download_path = Path(
        cfg.get("direct_download_path", DEFAULT_CONFIG["direct_download_path"])
    )
    download_path.mkdir(parents=True, exist_ok=True)

    # Create filename
    extra = result.get("extra", {})
    extension = extra.get("extension", "pdf")
    safe_title = "".join(
        c for c in result.get("title", "") if c.isalnum() or c in (" ", "-", "_")
    ).strip()[:200]

    filename = f"{safe_title}.{extension}"
    destination = download_path / filename

    md5 = extra.get("md5")
    if not md5:
        console.print(
            Panel(
                "No MD5 hash found. Cannot download.",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False

    # Show info
    info = Table.grid(padding=(0, 2))
    info.add_row("[cyan]Title:[/cyan]", result.get("title", "Unknown"))
    info.add_row("[cyan]Size:[/cyan]", result.get("size", "Unknown"))
    info.add_row("[cyan]Type:[/cyan]", f"📦 Direct Download")
    info.add_row("[cyan]Format:[/cyan]", extension.upper())
    info.add_row("[cyan]Destination:[/cyan]", str(destination))

    console.print(
        Panel(
            info,
            title="[bold green]🏴‍☠️ Starting Download[/bold green]",
            border_style="green",
            box=box.DOUBLE,
        )
    )

    # Get download URL
    console.print("[dim]→ Fetching download URL...[/dim]")
    try:
        api = get_api_client()
        source_hint = ""
        if result.get("source", "").lower().startswith("annas"):
            source_hint = "annasarchive"
        elif result.get("source", "").lower() == "libgen":
            source_hint = "libgen"

        download_url_info = api.get_download_url(
            md5, source="auto", source_hint=source_hint
        )
        download_url = download_url_info.get("download_url") or download_url_info.get(
            "mirror"
        )

        if not download_url:
            console.print(
                Panel(
                    "Could not get download URL",
                    title="[bold red]✗ Error[/bold red]",
                    border_style="red",
                )
            )
            return False
    except Exception as e:
        console.print(
            Panel(
                f"Failed to get URL: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False

    # Download with retry
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
                downloaded_size = 0
                if destination.exists():
                    downloaded_size = destination.stat().st_size
                    console.print(
                        f"[yellow]→ Resuming from {format_size(downloaded_size)}[/yellow]"
                    )

                headers = {}
                if downloaded_size > 0:
                    headers["Range"] = f"bytes={downloaded_size}-"

                task = progress.add_task(
                    f"Downloading {filename[:40]}...", total=100, completed=0
                )

                response = requests.get(
                    download_url,
                    stream=True,
                    timeout=60,
                    headers=headers,
                    allow_redirects=True,
                )
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                if downloaded_size > 0 and response.status_code == 206:
                    total_size += downloaded_size

                mode = "ab" if downloaded_size > 0 else "wb"

                with open(destination, mode) as f:
                    for chunk in response.iter_content(chunk_size=32768):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                percentage = (downloaded_size / total_size) * 100
                                progress.update(task, completed=percentage)

                break

        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                console.print(f"[yellow]⚠ Error: {str(e)[:100]}[/yellow]")
                console.print(
                    f"[yellow]→ Retry {retry_count + 1}/{max_retries}[/yellow]"
                )
                time.sleep(2)
            else:
                console.print(
                    Panel(
                        f"Download failed: {e}",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                if destination.exists():
                    destination.unlink()
                return False

    # Verify
    if not destination.exists():
        console.print(
            Panel(
                "File not found after download",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return False

    file_size = destination.stat().st_size
    if file_size < 1024:
        console.print(
            Panel(
                f"Suspicious file size: {file_size} bytes",
                title="[bold yellow]⚠ Warning[/bold yellow]",
                border_style="yellow",
            )
        )
        if not Confirm.ask("[yellow]Keep anyway?[/yellow]"):
            destination.unlink()
            return False

    console.print(
        Panel(
            f"[green]✓ Download complete![/green]\n"
            f"[dim]Location: {destination}[/dim]\n"
            f"[dim]Size: {format_size(file_size)}[/dim]",
            title="[bold green]🎉 Success[/bold green]",
            border_style="green",
            box=box.DOUBLE,
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
    """Download torrent with enhanced progress tracking."""
    if item.get("DownloadType") == DownloadType.DIRECT:
        download_direct_file(item)
        return

    cfg = load_json(CONFIG_PATH)
    qb = qb_client()

    # Show info panel
    info = Table.grid(padding=(0, 2))
    info.add_row("[cyan]Title:[/cyan]", safe_str(item.get("Title")))
    info.add_row("[cyan]Size:[/cyan]", safe_str(item.get("Size")))
    info.add_row(
        "[cyan]Seeders:[/cyan]",
        f"{get_health_icon(item.get('Seeders', 0))} {safe_str(item.get('Seeders', 0))}",
    )
    info.add_row("[cyan]Leechers:[/cyan]", safe_str(item.get("Leechers", 0)))

    console.print(
        Panel(
            info,
            title="[bold green]🏴‍☠️ Adding Torrent[/bold green]",
            border_style="green",
            box=box.DOUBLE,
        )
    )

    active_downloads = qb.torrents_info(filter="downloading")
    if len(active_downloads) >= cfg.get("max_active_downloads", 5):
        console.print(
            Panel(
                f"Maximum active downloads ({cfg.get('max_active_downloads', 5)}) reached.\n"
                "Wait or increase limit in config.",
                title="[bold yellow]⚠ Warning[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    mag = item.get("MagnetUri") or item.get("Link")
    if not mag or not mag.startswith(("magnet:", "http")):
        console.print(
            Panel(
                "Invalid magnet/download link",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return

    try:
        qb.torrents_add(
            urls=mag,
            save_path=cfg["download_path"],
            use_auto_torrent_management=False,
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

    console.print("[dim]→ Searching for torrent...[/dim]")
    time.sleep(2)

    name = safe_str(item.get("Title"))
    task_hash = find_torrent_by_name(qb, name, max_wait=15)

    if not task_hash:
        console.print(
            Panel(
                "Torrent not found in qBittorrent",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return

    console.print(f"[green]✓ Found torrent ({task_hash[:8]}...)[/green]")

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
                        "Torrent disappeared",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                break

            progress.update(
                task,
                completed=info.progress * 100 if info.progress else 0,
                download_speed=format_speed(info.dlspeed) if info.dlspeed else "0 B/s",
                upload_speed=format_speed(info.upspeed) if info.upspeed else "0 B/s",
                state=safe_str(info.state),
            )

            if info.progress >= 1.0 and info.state in [
                "uploading",
                "stalledUP",
                "queuedUP",
            ]:
                break
            elif info.state == "error":
                console.print(
                    Panel(
                        "Torrent error",
                        title="[bold red]✗ Error[/bold red]",
                        border_style="red",
                    )
                )
                break

            time.sleep(1)

    console.print(
        Panel(
            f"[green]✓ Download complete![/green]\n"
            f"[dim]Location: {cfg['download_path']}[/dim]",
            title="[bold green]🎉 Success[/bold green]",
            border_style="green",
            box=box.DOUBLE,
        )
    )

    history = load_json(HISTORY_PATH)
    history.append({"title": item.get("Title"), "time": time.time(), "hash": task_hash})
    save_json(HISTORY_PATH, history)

    if cfg.get("auto_remove_completed"):
        try:
            qb.torrents_delete(torrent_hashes=task_hash, delete_files=False)
            console.print("[dim]→ Removed from qBittorrent (files kept)[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Failed to auto-remove: {e}[/yellow]")


def browse_interactive() -> None:
    """Enhanced interactive browse with better UI."""
    console.print(Rule("[bold cyan]🔍 Search & Download[/bold cyan]", style="cyan"))

    # Search type selection with better UI
    type_options = {
        "1": ("general", "🌐 All Categories"),
        "2": ("books", "📚 Books (LibGen + Anna's)"),
        "3": ("games", "🎮 Game Repacks"),
        "4": ("movies", "🎬 Movies (YTS)"),
    }

    console.print("\n[bold cyan]Select Category:[/bold cyan]")
    for key, (_, display) in type_options.items():
        console.print(f"  [{key}] {display}")

    choice = Prompt.ask(
        "\n[cyan]Category[/cyan]", choices=list(type_options.keys()), default="1"
    )
    search_type, _ = type_options[choice]

    query = Prompt.ask("\n[cyan]Search query[/cyan]")

    with console.status(f"[bold green]🔍 Searching...", spinner="dots"):
        try:
            api = get_api_client()
            if search_type == "books":
                results = api.search_books(query, 25)
            elif search_type == "games":
                results = api.search_games(query, 25)
            elif search_type == "movies":
                results = api.search_movies(query, 25)
            else:
                results = api.search(query, 25)
        except APIError as e:
            console.print(
                Panel(
                    f"[red]API Error:[/red] {e}\n\n"
                    f"[yellow]Troubleshooting:[/yellow]\n"
                    f"• Check if API is running: [dim]docker ps[/dim]\n"
                    f"• Check API health: [dim]curl http://127.0.0.1:9117/api/v1/health[/dim]\n"
                    f"• Check logs: [dim]docker logs <container>[/dim]",
                    title="[bold red]✗ Connection Failed[/bold red]",
                    border_style="red",
                    box=box.ROUNDED,
                )
            )
            return

    if not results:
        console.print(
            Panel(
                "No results found",
                title="[bold yellow]📭 Empty[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    # Pagination
    page_size = 10
    page = 0

    while True:
        start = page * page_size
        page_items = results[start : start + page_size]
        total_pages = (len(results) - 1) // page_size + 1

        console.clear()
        console.print(Rule(f"[bold cyan]Results: '{query}'[/bold cyan]", style="cyan"))

        tbl = Table(
            title=f"Page {page + 1}/{total_pages} • {len(results)} results • Type: {search_type}",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            title_style="bold magenta",
        )
        tbl.add_column("#", style="dim", width=4)
        tbl.add_column("Title", style="white", no_wrap=False)
        tbl.add_column("Size", justify="right", style="green")
        tbl.add_column("Type", justify="center", style="magenta")
        tbl.add_column("Source", justify="center", style="cyan")

        for i, r in enumerate(page_items, start=start + 1):
            type_icon = "📦" if r.download_type == DownloadType.DIRECT else "🧲"
            tbl.add_row(str(i), r.title[:70], r.size, type_icon, r.source)

        console.print(tbl)
        console.print("\n[dim]📦 = Direct Download | 🧲 = Torrent[/dim]")

        action = Prompt.ask(
            "\n[cyan]Action[/cyan] [[bold]n[/bold]]ext | [[bold]p[/bold]]rev | [bold]number[/bold] | [[bold]q[/bold]]uit",
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

                # Show detailed info
                info = Table.grid(padding=(0, 2))
                info.add_row("[bold cyan]Title:[/bold cyan]", item.title)
                info.add_row("[bold cyan]Size:[/bold cyan]", item.size)
                info.add_row(
                    "[bold cyan]Type:[/bold cyan]",
                    "📦 Direct Download"
                    if item.download_type == DownloadType.DIRECT
                    else "🧲 Torrent",
                )
                info.add_row("[bold cyan]Source:[/bold cyan]", item.source)

                if item.download_type == DownloadType.DIRECT:
                    info.add_row(
                        "[bold cyan]Authors:[/bold cyan]",
                        item.extra.get("authors", "N/A"),
                    )
                    info.add_row(
                        "[bold cyan]Extension:[/bold cyan]",
                        item.extra.get("extension", "N/A"),
                    )
                    info.add_row(
                        "[bold cyan]Publisher:[/bold cyan]",
                        item.extra.get("publisher", "N/A"),
                    )
                else:
                    info.add_row(
                        "[bold cyan]Seeders:[/bold cyan]",
                        f"{get_health_icon(item.seeders)} {item.seeders}",
                    )

                console.print(
                    Panel(
                        info,
                        title="[bold green]📋 Details[/bold green]",
                        border_style="green",
                    )
                )

                if Confirm.ask("\n[bold cyan]Download?[/bold cyan]"):
                    item_dict = {
                        "title": item.title,
                        "Title": item.title,
                        "Size": item.size,
                        "size": item.size,
                        "Seeders": item.seeders,
                        "Leechers": item.leechers,
                        "DownloadType": item.download_type,
                        "download_type": item.download_type.value,
                        "download_url": item.download_url,
                        "MagnetUri": item.download_url
                        if item.download_type != DownloadType.DIRECT
                        else None,
                        "Link": item.download_url,
                        "extra": item.extra,
                        "source": item.source,
                    }
                    download_with_progress(item_dict)

                    # Save results
                    results_dicts = []
                    for r in results:
                        r_dict = r.__dict__.copy()
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
    """🔍 Interactive browse and download interface."""
    browse_interactive()


@app.command()
def search(query: str, limit: int = 10) -> None:
    """🔎 Search across all indexers."""
    console.print(Rule(f"[bold cyan]🔍 Search: '{query}'[/bold cyan]"))

    with console.status("[bold green]Searching...", spinner="dots"):
        try:
            api = get_api_client()
            results = api.search(query, limit)
        except APIError as e:
            console.print(
                Panel(
                    f"API Error: {e}",
                    title="[bold red]✗ Error[/bold red]",
                    border_style="red",
                )
            )
            return

    if not results:
        console.print(
            Panel(
                "No results",
                title="[bold yellow]📭 Empty[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    # Convert and save
    results_dicts = []
    for r in results:
        r_dict = r.__dict__.copy()
        if "download_type" in r_dict and isinstance(
            r_dict["download_type"], DownloadType
        ):
            r_dict["download_type"] = r_dict["download_type"].value
        results_dicts.append(r_dict)
    save_json(LAST_RESULTS, results_dicts)

    tbl = Table(
        title=f"🔍 Results: {query}",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="blue",
    )
    tbl.add_column("#", style="dim", width=4)
    tbl.add_column("Title", style="white", no_wrap=False)
    tbl.add_column("Size", justify="right", style="green")
    tbl.add_column("Seeds", justify="center", style="yellow")
    tbl.add_column("Health", justify="center")

    for i, r in enumerate(results, 1):
        tbl.add_row(
            str(i), r.title[:80], r.size, str(r.seeders), get_health_icon(r.seeders)
        )

    console.print(tbl)
    console.print(f"\n[dim]💡 Use 'yarr download <number>' to download[/dim]")


@app.command()
def download(index: int) -> None:
    """⬇️ Download by index from last search."""
    results = load_json(LAST_RESULTS)
    if not 1 <= index <= len(results):
        console.print(
            Panel(
                f"Invalid index: {index}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )
        return

    item = results[index - 1]
    if "download_type" in item and isinstance(item["download_type"], str):
        item["DownloadType"] = (
            DownloadType.DIRECT
            if item["download_type"] == "direct"
            else DownloadType.TORRENT
        )

    download_with_progress(item)


@app.command("list")
def list_downloads(
    all: bool = typer.Option(False, "--all", "-a", help="Show all torrents"),
) -> None:
    """📋 List active/all torrents."""
    with console.status("[bold green]Loading...", spinner="dots"):
        qb = qb_client()
        torrents = qb.torrents_info() if all else qb.torrents_info(filter="downloading")

    title = "📋 All Torrents" if all else "📋 Active Downloads"

    if not torrents:
        console.print(
            Panel(
                "No torrents",
                title=f"[bold yellow]{title}[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    console.print(Rule(f"[bold cyan]{title}[/bold cyan]"))

    tbl = Table(box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    tbl.add_column("Name", style="white", no_wrap=False, max_width=50)
    tbl.add_column("Progress", justify="center", style="green")
    tbl.add_column("Status", justify="center", style="yellow")
    tbl.add_column("Size", justify="right", style="cyan")
    tbl.add_column("Ratio", justify="center", style="magenta")

    for t in torrents:
        progress_val = f"{t.progress * 100:.1f}%" if t.progress else "0%"
        size = f"{t.size / (1024**3):.2f} GB" if t.size else "N/A"
        ratio = f"{t.ratio:.2f}" if t.ratio else "N/A"
        tbl.add_row(safe_str(t.name)[:50], progress_val, safe_str(t.state), size, ratio)

    console.print(tbl)


@app.command()
def server_info() -> None:
    """🖥️ Display server and indexer status."""
    console.print(Rule("[bold cyan]🖥️ Server Information[/bold cyan]"))

    try:
        api = get_api_client()
        with console.status("[bold green]Fetching info...", spinner="dots"):
            health = api.health_check()
            stats = api.get_stats()
            indexers = api.get_indexers()

        # Server status
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
            else "⚠️"
            if health["status"] == "degraded"
            else "❌"
        )

        info = Table.grid(padding=(0, 2))
        info.add_row(
            f"[{status_color}]{status_icon} Status:[/{status_color}]",
            f"[{status_color}]{health['status'].upper()}[/{status_color}]",
        )
        info.add_row("[cyan]Uptime:[/cyan]", health.get("uptime", "N/A"))
        info.add_row("[cyan]Version:[/cyan]", stats.get("version", "N/A"))
        info.add_row("[cyan]Memory:[/cyan]", f"{stats.get('memory_mb', 0)} MB")
        info.add_row("[cyan]Goroutines:[/cyan]", str(stats.get("goroutines", 0)))
        info.add_row(
            "[cyan]Cache:[/cyan]",
            f"{'✓ Enabled' if health.get('cache_enabled') else '✗ Disabled'} ({stats.get('cache_size', 0)} entries)",
        )

        console.print(
            Panel(
                info,
                title="[bold]Server Status[/bold]",
                border_style=status_color,
                box=box.DOUBLE,
            )
        )

        # Indexers
        console.print()
        tbl = Table(
            title="📡 Indexers",
            box=box.ROUNDED,
            header_style="bold cyan",
            border_style="blue",
        )
        tbl.add_column("Name", style="white")
        tbl.add_column("Status", justify="center")
        tbl.add_column("Type", justify="center", style="magenta")
        tbl.add_column("Health", justify="center")

        indexer_types = {
            "YTS": "Movies",
            "1337x": "General",
            "Fitgirl": "Games",
            "DODI": "Games",
            "libgen": "Books",
            "annas": "Books",
            "Repacks": "Games",
        }

        healthy_count = sum(1 for idx in indexers if idx.get("healthy", False))

        for idx in indexers:
            name = idx.get("name", "Unknown")
            healthy = idx.get("healthy", False)
            status = "[green]✓ Online[/green]" if healthy else "[red]✗ Offline[/red]"
            health_icon = "🟢" if healthy else "🔴"
            tbl.add_row(name, status, indexer_types.get(name, "Other"), health_icon)

        console.print(tbl)

        summary = Text()
        summary.append("\n📊 Summary: ", style="bold cyan")
        summary.append(f"{healthy_count}/{len(indexers)} ", style="bold green")
        summary.append("indexers online", style="dim")
        console.print(summary)

    except APIError as e:
        console.print(
            Panel(
                f"Connection failed: {e}",
                title="[bold red]✗ Error[/bold red]",
                border_style="red",
            )
        )


@app.command()
def dashboard() -> None:
    """📊 Comprehensive dashboard view."""
    console.clear()
    console.print(Rule("[bold cyan]📊 Yarr Dashboard[/bold cyan]"))

    try:
        api = get_api_client()
        qb = qb_client()

        with console.status("[bold green]Loading...", spinner="dots"):
            health = api.health_check()
            stats = api.get_stats()
            torrents = qb.torrents_info()
            active = [t for t in torrents if t.state in ["downloading", "uploading"]]
            hist = load_json(HISTORY_PATH)
            recent = hist[-5:] if hist else []

        # Layout
        layout = Layout()
        layout.split_column(Layout(name="header", size=7), Layout(name="body"))
        layout["body"].split_row(Layout(name="left"), Layout(name="right"))

        # Header
        status_color = "green" if health["status"] == "healthy" else "yellow"
        header = Text()
        header.append("🖥️ Server: ", style="bold cyan")
        header.append(f"{health['status'].upper()}", style=f"bold {status_color}")
        header.append(f"\n⏱️ Uptime: {health.get('uptime', 'N/A')}", style="cyan")
        header.append(f" | 💾 {stats.get('memory_mb', 0)}MB", style="cyan")
        header.append(
            f" | 📡 {health.get('healthy_count')}/{health.get('total_indexers')}",
            style="cyan",
        )

        layout["header"].update(
            Panel(Align.center(header), border_style=status_color, box=box.HEAVY)
        )

        # Active downloads
        active_tbl = Table(title="🔄 Active", box=box.SIMPLE, header_style="bold cyan")
        active_tbl.add_column("Name", no_wrap=False, max_width=40)
        active_tbl.add_column("Progress", justify="center")

        if active:
            for t in active[:5]:
                progress = f"{t.progress * 100:.1f}%" if t.progress else "0%"
                active_tbl.add_row(t.name[:40], f"[green]{progress}[/green]")
        else:
            active_tbl.add_row("[dim]No active downloads[/dim]", "")

        layout["left"].update(Panel(active_tbl, border_style="blue"))

        # Recent history
        hist_tbl = Table(title="📜 Recent", box=box.SIMPLE, header_style="bold cyan")
        hist_tbl.add_column("Title", no_wrap=False, max_width=40)
        hist_tbl.add_column("Time", justify="right")

        if recent:
            for entry in reversed(recent):
                time_str = datetime.fromtimestamp(entry.get("time", 0)).strftime(
                    "%m/%d %H:%M"
                )
                hist_tbl.add_row(entry.get("title", "")[:40], time_str)
        else:
            hist_tbl.add_row("[dim]No history[/dim]", "")

        layout["right"].update(Panel(hist_tbl, border_style="blue"))

        console.print(layout)

        # Stats bar
        stats_bar = Text()
        stats_bar.append("\n📊 Total: ", style="bold")
        stats_bar.append(str(len(hist)), style="green")
        stats_bar.append(" | 📦 Active: ", style="bold")
        stats_bar.append(str(len(active)), style="yellow")
        stats_bar.append(" | 💾 Cache: ", style="bold")
        stats_bar.append(f"{stats.get('cache_size', 0)} entries", style="cyan")
        console.print(Align.center(stats_bar))

    except Exception as e:
        console.print(
            Panel(
                f"Failed: {e}", title="[bold red]✗ Error[/bold red]", border_style="red"
            )
        )


@app.command()
def history() -> None:
    """📜 Show download history."""
    hist = load_json(HISTORY_PATH)

    if not hist:
        console.print(
            Panel(
                "No history",
                title="[bold yellow]📭 Empty[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    console.print(Rule("[bold cyan]📜 Download History[/bold cyan]"))

    tbl = Table(box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    tbl.add_column("Time", style="green")
    tbl.add_column("Title", style="white", no_wrap=False, max_width=60)
    tbl.add_column("Type", justify="center", style="magenta")

    for e in reversed(hist[-50:]):
        time_str = datetime.fromtimestamp(e.get("time", 0)).strftime("%Y-%m-%d %H:%M")
        type_icon = "📦" if e.get("type") == "direct" else "🧲"
        tbl.add_row(time_str, safe_str(e.get("title"))[:60], type_icon)

    console.print(tbl)
    console.print(
        f"\n[dim]Showing last {min(50, len(hist))} of {len(hist)} downloads[/dim]"
    )


@app.command()
def config() -> None:
    """⚙️ Show current configuration."""
    console.print(Rule("[bold cyan]⚙️ Configuration[/bold cyan]"))

    cfg = load_json(CONFIG_PATH)

    tree = Tree("📋 Config", guide_style="cyan")

    for key, value in cfg.items():
        if isinstance(value, dict):
            branch = tree.add(f"[bold cyan]{key}[/bold cyan]")
            for sub_key, sub_value in value.items():
                if sub_key == "password":
                    sub_value = "***"
                branch.add(f"[yellow]{sub_key}:[/yellow] {sub_value}")
        else:
            tree.add(f"[bold cyan]{key}:[/bold cyan] {value}")

    console.print(Panel(tree, border_style="cyan", box=box.ROUNDED))


@app.command()
def quick() -> None:
    """⚡ Quick interactive search."""
    console.print(Rule("[bold cyan]⚡ Quick Search[/bold cyan]"))

    categories = {
        "1": ("movies", "🎬 Movies"),
        "2": ("books", "📚 Books"),
        "3": ("games", "🎮 Games"),
        "4": ("", "🌐 All"),
    }

    console.print("\n[bold cyan]Category:[/bold cyan]")
    for k, (_, label) in categories.items():
        console.print(f"  [{k}] {label}")

    choice = Prompt.ask(
        "\n[cyan]Select[/cyan]", choices=list(categories.keys()), default="4"
    )
    cat_value, cat_name = categories[choice]

    query = Prompt.ask(f"\n[cyan]Search {cat_name}[/cyan]")

    with console.status(f"[bold green]Searching...", spinner="dots"):
        try:
            api = get_api_client()
            if cat_value == "movies":
                results = api.search_movies(query, 20)
            elif cat_value == "books":
                results = api.search_books(query, 20)
            elif cat_value == "games":
                results = api.search_games(query, 20)
            else:
                results = api.search(query, 20)
        except APIError as e:
            console.print(
                Panel(
                    f"Error: {e}",
                    title="[bold red]✗ Failed[/bold red]",
                    border_style="red",
                )
            )
            return

    if not results:
        console.print(
            Panel(
                "No results",
                title="[bold yellow]📭 Empty[/bold yellow]",
                border_style="yellow",
            )
        )
        return

    results_dicts = [r.__dict__ for r in results]
    save_json(LAST_RESULTS, results_dicts)

    console.print(f"\n[bold green]Found {len(results)} results[/bold green]\n")

    for i, r in enumerate(results[:5], 1):
        type_icon = "📦" if r.is_direct_download() else "🧲"
        health = get_health_icon(r.seeders) if not r.is_direct_download() else ""
        console.print(f"[bold cyan]{i}.[/bold cyan] {r.title[:70]}")
        console.print(f"   {type_icon} {r.size} {health}")
        console.print()

    if len(results) > 5:
        console.print(f"[dim]... and {len(results) - 5} more[/dim]\n")

    if Confirm.ask("[cyan]Download first result?[/cyan]"):
        download_with_progress(results_dicts[0])


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """🏴‍☠️ Yarr - The Pirate's Terminal"""
    if ctx.invoked_subcommand is None:
        show_welcome_banner()

        # Show quick menu
        menu = Table.grid(padding=(0, 2))
        menu.add_row(
            "[bold cyan]1.[/bold cyan] browse", "[dim]Interactive search[/dim]"
        )
        menu.add_row("[bold cyan]2.[/bold cyan] quick", "[dim]Quick search[/dim]")
        menu.add_row(
            "[bold cyan]3.[/bold cyan] dashboard", "[dim]Status overview[/dim]"
        )
        menu.add_row("[bold cyan]4.[/bold cyan] list", "[dim]Active downloads[/dim]")
        menu.add_row("[bold cyan]5.[/bold cyan] history", "[dim]Download history[/dim]")

        console.print(
            Panel(
                menu,
                title="[bold]Quick Menu[/bold]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )
        console.print("\n[dim]Type 'yarr --help' for all commands[/dim]\n")


if __name__ == "__main__":
    # Background threads
    def health_monitor():
        while True:
            cfg = load_json(CONFIG_PATH)
            try:
                api = get_api_client()
                health = api.health_check()
                if health["status"] != "healthy":
                    subprocess.run(
                        ["notify-send", "Yarr", f"API status: {health['status']}"],
                        check=False,
                    )
            except:
                pass
            time.sleep(cfg.get("health_check_interval", 3600))

    threading.Thread(target=health_monitor, daemon=True).start()

    app()
