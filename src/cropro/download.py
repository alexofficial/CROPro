"""Generic dataset download helpers for CROPro CLI.

This module intentionally contains no dataset-specific URLs or presets. Dataset
specific download behavior can be provided through local dataset plugins.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError


def _download_file(url: str, destination: Path, *, overwrite: bool = False) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        print(f"  keep archive: {destination.name}")
        return destination

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"Invalid URL {url!r}. Provide a full http(s) URL, e.g. "
            "https://.../dataset.zip"
        )
    if parsed.netloc in {"host", "example.com", "localhost"}:
        raise ValueError(
            f"URL {url!r} looks like a placeholder. Replace it with a real "
            "download URL from your dataset host."
        )

    print(f"  download: {url}")
    try:
        opener = urllib.request.build_opener()
        with opener.open(url, timeout=60) as response, destination.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except HTTPError as exc:
        raise ValueError(
            f"Failed to download {url!r}: HTTP {exc.code} {exc.reason}. "
            "Check the URL and your access permissions."
        ) from exc
    except URLError as exc:
        raise ValueError(
            f"Failed to download {url!r}: {exc.reason}. "
            "This usually means the URL/domain is wrong or network/DNS is unavailable."
        ) from exc
    print(f"  saved: {destination}")
    return destination


def _extract_zip(archive: Path, output_dir: Path, *, overwrite: bool = False) -> int:
    """Extract zip archive, skipping existing files unless overwrite=True."""
    archive = Path(archive)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()

    extracted = 0
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            target = (output_dir / member).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"Archive member escapes output dir: {member!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                continue
            with zf.open(member) as src, target.open("wb") as dst:
                dst.write(src.read())
            extracted += 1
    return extracted


@dataclass(slots=True)
class DownloadConfig:
    dataset_root: Path
    archives_root: Path
    images_root: Path
    overwrite: bool = False


def download_from_urls(
    config: DownloadConfig,
    *,
    urls: list[str],
) -> None:
    """Download one or more archive URLs and extract them into ``images_root``."""
    if not urls:
        raise ValueError("Download requires one or more --url values.")

    config.archives_root.mkdir(parents=True, exist_ok=True)
    config.images_root.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls, start=1):
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name or f"dataset_{i}.zip"
        if not name.endswith(".zip"):
            name = f"{name}.zip"
        archive_path = config.archives_root / name
        _download_file(url, archive_path, overwrite=config.overwrite)
        count = _extract_zip(archive_path, config.images_root, overwrite=config.overwrite)
        print(f"  extracted files: {count}")

    print(f"Dataset files are ready under {config.dataset_root}")
