"""Dataset download helpers for CROPro CLI.

This module provides a small downloader so users who installed CROPro from PyPI
can fetch supported datasets without relying on repository shell scripts.
"""

from __future__ import annotations

import subprocess
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError

PROSTATE158_DEFAULT_URLS = [
    "https://zenodo.org/api/records/6481141/files/prostate158_train.zip/content"
]


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
        with urllib.request.urlopen(url) as response, destination.open("wb") as out:
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


def _git_clone_or_pull(repo_url: str, destination: Path) -> None:
    destination = Path(destination)
    git_dir = destination / ".git"
    if git_dir.is_dir():
        print(f"  update labels repo: {destination}")
        subprocess.run(["git", "-C", str(destination), "pull", "--ff-only"], check=True)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"  clone labels repo: {repo_url} -> {destination}")
    subprocess.run(["git", "clone", repo_url, str(destination)], check=True)


@dataclass(slots=True)
class DownloadConfig:
    dataset: str
    dataset_root: Path
    archives_root: Path
    images_root: Path
    labels_root: Path | None
    overwrite: bool = False


def download_picai(
    config: DownloadConfig,
    *,
    folds: list[str],
    skip_labels: bool,
) -> None:
    """Download PI-CAI public image folds and optional labels."""
    config.archives_root.mkdir(parents=True, exist_ok=True)
    config.images_root.mkdir(parents=True, exist_ok=True)

    for fold in folds:
        archive_name = f"picai_public_images_fold{fold}.zip"
        url = (
            "https://zenodo.org/api/records/6624726/files/"
            f"{archive_name}/content"
        )
        archive_path = config.archives_root / archive_name
        print(f"Downloading PI-CAI fold {fold}...")
        _download_file(url, archive_path, overwrite=config.overwrite)
        count = _extract_zip(archive_path, config.images_root, overwrite=config.overwrite)
        print(f"  extracted files: {count}")

    if not skip_labels and config.labels_root is not None:
        _git_clone_or_pull("https://github.com/DIAGNijmegen/picai_labels", config.labels_root)

    print(f"PI-CAI data is ready under {config.dataset_root}")


def download_prostate158(
    config: DownloadConfig,
    *,
    urls: list[str],
) -> None:
    """Download Prostate158 archives.

    If no URLs are provided, CROPro uses the default Zenodo record URL for
    Prostate158 training data (10.5281/zenodo.6481141).
    """
    if not urls:
        urls = list(PROSTATE158_DEFAULT_URLS)
        print("No --url provided for Prostate158. Using built-in Zenodo URL:")
        for u in urls:
            print(f"  - {u}")

    config.archives_root.mkdir(parents=True, exist_ok=True)
    config.images_root.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls, start=1):
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name or f"prostate158_{i}.zip"
        if not name.endswith(".zip"):
            name = f"{name}.zip"
        archive_path = config.archives_root / name
        print(f"Downloading Prostate158 archive {i}...")
        _download_file(url, archive_path, overwrite=config.overwrite)
        count = _extract_zip(archive_path, config.images_root, overwrite=config.overwrite)
        print(f"  extracted files: {count}")

    print(f"Prostate158 data is ready under {config.dataset_root}")


def download_custom(
    config: DownloadConfig,
    *,
    urls: list[str],
) -> None:
    if not urls:
        raise ValueError("Custom download requires one or more --url values.")

    config.archives_root.mkdir(parents=True, exist_ok=True)
    config.images_root.mkdir(parents=True, exist_ok=True)

    for i, url in enumerate(urls, start=1):
        parsed = urllib.parse.urlparse(url)
        name = Path(parsed.path).name or f"archive_{i}.zip"
        if not name.endswith(".zip"):
            name = f"{name}.zip"
        archive_path = config.archives_root / name
        _download_file(url, archive_path, overwrite=config.overwrite)
        count = _extract_zip(archive_path, config.images_root, overwrite=config.overwrite)
        print(f"  extracted files: {count}")

    print(f"Custom dataset files are ready under {config.dataset_root}")
