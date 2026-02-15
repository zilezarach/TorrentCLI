#!/usr/bin/env python3
"""
Go Torrent API Client
A client for interacting with the custom Go torrent API that supports
both magnet links and direct downloads (like LibGen and Anna's Archive).
"""

import requests
import time
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

    def __init__(self, base_url: str = "http://127.0.0.1:9117", timeout: int = 180):
        """
        Initialize the Go API client

        Args:
            base_url: Base URL of the Go API server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        # Improve session settings for stability
        self.session.headers.update(
            {
                "User-Agent": "TorrentCLI/2.0",
                "Accept": "application/json",
                "Connection": "keep-alive",
            }
        )
        # Configure retry adapter
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy, pool_connections=10, pool_maxsize=20
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _make_request(
        self, method: str, path: str, max_retries: int = 3, **kwargs
    ) -> requests.Response:
        """Internal helper to make HTTP requests with consistent error handling and retry logic"""
        url = f"{self.base_url}{path}"
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except requests.HTTPError as e:
                if e.response.status_code == 404:
                    raise APIError(f"Endpoint not found: {path}")
                elif e.response.status_code >= 500:
                    if attempt < max_retries - 1:
                        time.sleep(2**attempt)
                        continue
                    raise APIError(f"Server error: {e.response.status_code}")
                else:
                    raise APIError(f"HTTP {e.response.status_code}: {str(e)}")
            except (
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                ConnectionResetError,
                BrokenPipeError,
            ) as e:
                last_error = e
                if attempt < max_retries - 1:
                    # Wait before retry (exponential backoff)
                    time.sleep(2**attempt)
                    # Recreate session on connection error
                    self.session.close()
                    self.session = requests.Session()
                    self.session.headers.update(
                        {
                            "User-Agent": "TorrentCLI/2.0",
                            "Accept": "application/json",
                            "Connection": "keep-alive",
                        }
                    )
                    continue
                raise APIError(
                    f"Connection failed after {max_retries} attempts. Make sure the API server is running at {self.base_url}. Error: {str(e)}"
                )
            except requests.Timeout:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise APIError(
                    f"Request timed out after {self.timeout} seconds and {max_retries} retries"
                )
            except requests.RequestException as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                raise APIError(f"Request failed after {max_retries} attempts: {str(e)}")

        # If we get here, all retries failed
        if last_error:
            raise APIError(
                f"Request failed after {max_retries} attempts: {str(last_error)}"
            )
        raise APIError(f"Request failed after {max_retries} attempts")

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

        response = self._make_request(
            "GET", "/api/v1/search", params=params, timeout=180
        )
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

    def search_movies(self, query: str, limit: int = 10) -> List[SearchResult]:
        """Search for movies specifically"""
        params = {"query": query, "limit": limit}
        response = self._make_request(
            "GET", "/api/v1/movies/search", params=params, timeout=180
        )
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
        self, query: str, limit: int = 10, source: str = "both"
    ) -> List[SearchResult]:
        """Search for books (uses unified search by default)"""
        if source == "both":
            endpoint = "/api/v1/books/search"
            params = {"query": query, "limit": limit}
        else:
            endpoint = "/api/v1/books/search/source"
            params = {"query": query, "limit": limit, "source": source}

        response = self._make_request("GET", endpoint, params=params, timeout=180)
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
        """Search for game repacks (FitGirl, DODI)"""
        params = {"query": query, "limit": limit}
        response = self._make_request(
            "GET", "/api/v1/games/repacks/search", params=params, timeout=180
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

    def get_latest_games(self, limit: int = 20) -> List[SearchResult]:
        """Get latest game repacks"""
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
        """Get download URL for a book by MD5"""
        params = {"md5": md5}

        if source.lower() not in ("auto", ""):
            params["source"] = source.lower()

        if source_hint:
            params["source_hint"] = source_hint.lower()

        endpoint = "/api/v1/books/download"
        response = self._make_request("GET", endpoint, params=params, timeout=120)
        return response.json()

    def get_indexers(self) -> List[Dict[str, Any]]:
        """Get list of available indexers and their status"""
        response = self._make_request("GET", "/api/v1/indexers")
        data = response.json()
        return data.get("indexers", [])

    def health_check(self) -> Dict[str, Any]:
        """Check API health status"""
        response = self._make_request("GET", "/api/v1/health")
        return response.json()

    def get_stats(self) -> Dict[str, Any]:
        """Get API statistics"""
        response = self._make_request("GET", "/api/v1/stats")
        return response.json()

    def download_direct_file(
        self,
        url: str,
        destination: str,
        chunk_size: int = 8192,
        progress_callback: Optional[callable] = None,
    ) -> str:
        """Download a direct file (for LibGen books, etc.)"""
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

    def __del__(self):
        """Clean up session on deletion"""
        if hasattr(self, "session"):
            self.session.close()


class APIError(Exception):
    """Custom exception for API errors"""

    pass
