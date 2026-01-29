#!/home/zil/production/torrent_cli/venv/bin/python3
"""
Go Torrent API Client
A client for interacting with the custom Go torrent API that supports
both magnet links and direct downloads (like LibGen and Anna's Archive).
"""

import requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class DownloadType(Enum):
    """Type of download available"""

    MAGNET = "magnet"
    DIRECT = "direct"
    TORRENT = "torrent"


class Category(Enum):
    """Search categories"""

    MOVIES = "movies"
    TV = "tv"
    BOOKS = "books"
    GAMES = "games"
    MUSIC = "music"
    SOFTWARE = "software"
    ANIME = "anime"
    ALL = ""


@dataclass
class SearchResult:
    """Represents a search result from the Go API"""

    title: str
    download_url: str  # Can be magnet URI or direct download URL
    download_type: DownloadType
    info_hash: str
    size: str
    size_bytes: int
    seeders: int
    leechers: int
    category: str
    source: str
    publish_date: str
    extra: Dict[str, Any]

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "SearchResult":
        """Create SearchResult from API response data"""
        # Get extra data first
        extra = data.get("extra", {})

        # Determine download type - check both locations
        download_type_str = extra.get("download_type") or data.get(
            "download_type", "torrent"
        )

        if download_type_str == "direct":
            download_type = DownloadType.DIRECT
        elif download_type_str == "magnet":
            download_type = DownloadType.MAGNET
        else:
            download_type = DownloadType.TORRENT

        # Get download URL - for direct downloads, use the mirror from extra
        if download_type == DownloadType.DIRECT:
            download_url = (
                extra.get("mirror", "")
                or data.get("magnet_uri", "")
                or data.get("link", "")
            )
        else:
            download_url = data.get("magnet_uri", "") or data.get("link", "")

        return cls(
            title=data.get("title", ""),
            download_url=download_url,
            download_type=download_type,
            info_hash=data.get("info_hash", ""),
            size=data.get("size", ""),
            size_bytes=data.get("size_bytes", 0),
            seeders=data.get("seeders", 0),
            leechers=data.get("leechers", 0),
            category=data.get("category", ""),
            source=data.get("source", ""),
            publish_date=data.get("publish_date", ""),
            extra=extra,
        )

    def is_direct_download(self) -> bool:
        """Check if this is a direct download (not a torrent)"""
        return self.download_type == DownloadType.DIRECT

    def get_metadata(self) -> Dict[str, str]:
        """Get extra metadata (useful for LibGen books)"""
        return self.extra


class GoTorrentAPI:
    """Client for the Go torrent API"""

    def __init__(self, base_url: str = "http://127.0.0.1:9117", timeout: int = 30):
        """
        Initialize the Go API client

        Args:
            base_url: Base URL of the Go API server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "TorrentCLI/2.0", "Accept": "application/json"}
        )

    def _make_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Internal helper to make HTTP requests with consistent error handling"""
        url = f"{self.base_url}{path}"
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                raise APIError(f"Endpoint not found: {path}")
            elif e.response.status_code >= 500:
                raise APIError(f"Server error: {e.response.status_code}")
            else:
                raise APIError(f"HTTP {e.response.status_code}: {str(e)}")
        except requests.ConnectionError:
            raise APIError(
                f"Could not connect to API at {self.base_url}. Make sure the server is running."
            )
        except requests.Timeout:
            raise APIError(f"Request timed out after {self.timeout} seconds")
        except requests.RequestException as e:
            raise APIError(f"Request failed: {str(e)}")

    def search(
        self, query: str, limit: int = 25, category: Optional[str] = None
    ) -> List[SearchResult]:
        """
        Search across all indexers

        Args:
            query: Search query
            limit: Maximum number of results
            category: Optional category filter (e.g., "movies", "books")

        Returns:
            List of SearchResult objects
        """
        params = {"query": query, "limit": limit}
        if category:
            params["category"] = category

        response = self._make_request("GET", "/api/v1/search", params=params)
        data = response.json()

        results = []
        for item in data.get("results", []):
            try:
                results.append(SearchResult.from_api_response(item))
            except Exception as e:
                # Skip malformed results but continue
                print(f"Warning: Skipped malformed result: {e}")
                continue

        return results

    def search_movies(self, query: str, limit: int = 25) -> List[SearchResult]:
        """
        Search for movies specifically

        Args:
            query: Movie search query
            limit: Maximum number of results

        Returns:
            List of SearchResult objects
        """
        params = {"query": query, "limit": limit}
        response = self._make_request("GET", "/api/v1/movies/search", params=params)
        data = response.json()
        results = []
        for item in data.get("results", []):
            try:
                results.append(SearchResult.from_api_response(item))
            except Exception as e:
                print(f"Warning: Skipped malformed movie result: {e}")
                continue
        return results

    def search_books(
        self, query: str, limit: int = 25, source: str = "both"
    ) -> List[SearchResult]:
        """
        Search for books (uses unified search by default)

        Args:
            query: Book search query
            limit: Maximum number of results
            source: "both" (default), "libgen", or "annas"

        Returns:
            List of SearchResult objects with direct download links
        """
        if source == "both":
            endpoint = "/api/v1/books/search"
            params = {"query": query, "limit": limit}
        else:
            endpoint = "/api/v1/books/search/source"
            params = {"query": query, "limit": limit, "source": source}

        response = self._make_request("GET", endpoint, params=params)
        data = response.json()

        results = []
        for item in data.get("results", []):
            try:
                results.append(SearchResult.from_api_response(item))
            except Exception as e:
                print(f"Warning: Skipped malformed book result: {e}")
                continue

        return results

    def search_games(self, query: str, limit: int = 20) -> List[SearchResult]:
        """
        Search for game repacks (FitGirl, DODI)

        Args:
            query: Game search query
            limit: Maximum number of results

        Returns:
            List of SearchResult objects
        """
        params = {"query": query, "limit": limit}
        response = self._make_request(
            "GET", "/api/v1/games/repacks/search", params=params
        )
        data = response.json()

        results = []
        for item in data.get("results", []):
            try:
                results.append(SearchResult.from_api_response(item))
            except Exception as e:
                print(f"Warning: Skipped malformed game result: {e}")
                continue

        return results

    def get_latest_games(self, limit: int = 30) -> List[SearchResult]:
        """
        Get latest game repacks

        Args:
            limit: Maximum number of results

        Returns:
            List of SearchResult objects
        """
        params = {"limit": limit}
        response = self._make_request(
            "GET", "/api/v1/games/repacks/latest", params=params
        )
        data = response.json()

        results = []
        for item in data.get("results", []):
            try:
                results.append(SearchResult.from_api_response(item))
            except Exception as e:
                print(f"Warning: Skipped malformed game result: {e}")
                continue
        return results

    def get_download_url(
        self, md5: str, source: str = "auto", source_hint: str = ""
    ) -> Dict[str, Any]:
        params = {"md5": md5}

        if source.lower() not in ("auto", ""):
            params["source"] = source.lower()

        if source_hint:
            params["source_hint"] = source_hint.lower()  # e.g. "annasarchive"

        endpoint = "/api/v1/books/download"

        response = self._make_request("GET", endpoint, params=params, timeout=120)
        return response.json()

    def get_indexers(self) -> List[Dict[str, Any]]:
        """
        Get list of available indexers and their status

        Returns:
            List of indexer info dictionaries
        """
        response = self._make_request("GET", "/api/v1/indexers")
        data = response.json()
        return data.get("indexers", [])

    def health_check(self) -> Dict[str, Any]:
        """
        Check API health status

        Returns:
            Health status dictionary
        """
        response = self._make_request("GET", "/api/v1/health")
        return response.json()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get API statistics

        Returns:
            Statistics dictionary
        """
        response = self._make_request("GET", "/api/v1/stats")
        return response.json()

    def download_direct_file(
        self,
        url: str,
        destination: str,
        chunk_size: int = 8192,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """
        Download a direct file (for LibGen books, etc.)

        Args:
            url: Direct download URL
            destination: Destination file path
            chunk_size: Download chunk size in bytes
            progress_callback: Optional callback for progress updates (bytes_downloaded, total_bytes)

        Returns:
            Path to downloaded file
        """
        try:
            response = self.session.get(url, stream=True, timeout=self.timeout)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

            return destination
        except requests.RequestException as e:
            raise APIError(f"Direct download failed: {str(e)}")


class APIError(Exception):
    """Custom exception for API errors"""

    pass


# Compatibility wrapper to maintain existing interface
class GoAPIWrapper:
    """Wrapper to provide Jackett-like interface for existing code"""

    def __init__(self, api_url: str = "http://127.0.0.1:9117"):
        self.client = GoTorrentAPI(api_url)

    def fetch(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch results in Jackett-compatible format

        Args:
            query: Search query
            limit: Result limit

        Returns:
            List of result dictionaries compatible with original code
        """
        results = self.client.search(query, limit)

        # Convert to Jackett-like format
        jackett_format = []
        for result in results:
            item = {
                "Title": result.title,
                "Size": result.size,
                "Seeders": result.seeders,
                "Leechers": result.leechers,
                "CategoryDesc": result.category,
                "PublishDate": result.publish_date,
                "InfoHash": result.info_hash,
                # Special handling for direct vs magnet
                "MagnetUri": result.download_url
                if not result.is_direct_download()
                else None,
                "Link": result.download_url
                if result.is_direct_download()
                else result.download_url,
                # Add extra metadata
                "Extra": result.extra,
                "IsDirectDownload": result.is_direct_download(),
                "Source": result.source,
                "DownloadType": result.download_type.value,  # Convert enum to string
            }
            jackett_format.append(item)

        return jackett_format


# Example usage
if __name__ == "__main__":
    # Initialize API client
    api = GoTorrentAPI("http://127.0.0.1:9117")

    try:
        # Health check
        print("🏥 Checking API health...")
        health = api.health_check()
        print(f"Status: {health.get('status')}")
        print(
            f"Healthy indexers: {health.get('healthy_count')}/{health.get('total_indexers')}"
        )
        print()

        # Search for books (unified - both LibGen and Anna's Archive)
        print("📚 Searching for books (unified search)...")
        book_results = api.search_books("golang programming", limit=5)
        print(f"Found {len(book_results)} books\n")

        for i, result in enumerate(book_results, 1):
            print(f"{i}. 📖 {result.title[:70]}")
            print(f"   Size: {result.size} | Source: {result.source}")
            print(f"   Direct Download: {result.is_direct_download()}")
            if result.is_direct_download():
                print(f"   Authors: {result.extra.get('authors', 'N/A')}")
                print(f"   Extension: {result.extra.get('extension', 'N/A')}")
                # Show MD5 for download
                if result.info_hash:
                    print(f"   MD5: {result.info_hash}")
            print()

        # Search for movies
        print("\n🎬 Searching for movies...")
        movie_results = api.search_movies("Inception", limit=5)
        print(f"Found {len(movie_results)} movies\n")

        for i, result in enumerate(movie_results, 1):
            print(f"{i}. 🎥 {result.title[:70]}")
            print(
                f"   Size: {result.size} | Seeders: {result.seeders} | Source: {result.source}"
            )
            print()

        # Search for games
        print("\n🎮 Searching for games...")
        game_results = api.search_games("cyberpunk", limit=3)
        print(f"Found {len(game_results)} games\n")

        for i, result in enumerate(game_results, 1):
            print(f"{i}. 🎮 {result.title[:70]}")
            print(f"   Size: {result.size} | Source: {result.source}")
            print()

        # Get latest games
        print("\n🆕 Getting latest game repacks...")
        latest_games = api.get_latest_games(limit=3)
        print(f"Found {len(latest_games)} latest games\n")

        for i, result in enumerate(latest_games, 1):
            print(f"{i}. 🎮 {result.title[:70]}")
            print(f"   Size: {result.size} | Source: {result.source}")
            print()

        # Demonstrate download URL fetching for a book
        if book_results and book_results[0].info_hash:
            print("\n📥 Testing download URL fetch...")
            md5 = book_results[0].info_hash
            try:
                download_info = api.get_download_url(md5)
                print(
                    f"Download URL: {download_info.get('download_url', 'N/A')[:80]}..."
                )
                print(f"Source used: {download_info.get('source', 'N/A')}")
                print(f"Cached: {download_info.get('cached', False)}")
            except APIError as e:
                print(f"Note: {e}")

    except APIError as e:
        print(f"\n❌ API Error: {e}")
        print("\nMake sure the Go Torrent API is running:")
        print("  cd zil_tor-api")
        print("  docker-compose up -d")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
