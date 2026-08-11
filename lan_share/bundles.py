from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
import zipfile


HISTORICAL_SOURCE_NOTE = (
    "历史交付未在本地记录原始下载来源链接。\n"
    "新入库任务会在这里保存实际来源页面 URL。\n"
)


@dataclass(frozen=True)
class DeliveryFiles:
    directory_name: str
    package: Path
    icon: Path
    developer: Path
    source: Path | None


def create_delivery_bundle(files: DeliveryFiles, temporary_root: Path) -> Path:
    """Create a disposable, flat ZIP containing one complete delivery."""
    temporary_root.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="find-apk-delivery-",
        suffix=".zip",
        dir=temporary_root,
    )
    os.close(descriptor)
    output = Path(temporary_name)

    try:
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            archive.write(files.package, arcname=files.package.name)
            archive.write(files.icon, arcname="icon.webp")
            archive.write(files.developer, arcname="developer.txt")
            if files.source is not None:
                archive.write(files.source, arcname="source.txt")
            else:
                archive.writestr("source.txt", HISTORICAL_SOURCE_NOTE)
        return output
    except Exception:
        output.unlink(missing_ok=True)
        raise


def remove_delivery_directory(directory: Path, downloads_root: Path) -> bool:
    """Permanently remove one resolved delivery directory inside downloads."""
    if directory.is_symlink():
        raise ValueError(f"refusing symlink delivery directory: {directory}")

    root = downloads_root.resolve(strict=False)
    target = directory.resolve(strict=False)
    if target == root:
        raise ValueError("refusing to remove the downloads root")
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError(
            f"delivery directory is outside downloads root: {target}"
        ) from error

    if not target.exists():
        return False
    if not target.is_dir():
        raise ValueError(f"delivery path is not a directory: {target}")
    shutil.rmtree(target)
    return True
