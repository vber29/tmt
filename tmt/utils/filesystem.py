"""
Utility functions for filesystem operations.
"""

import os
import shutil

import tmt.log
from tmt._compat.pathlib import Path
from tmt.utils import Command, GeneralError, RunError


def _copy_tree_reflinks(
    src: Path,
    dst: Path,
    logger: 'tmt.log.Logger',
    workdir_root: Path,  # Keep signature consistent, even if not used here
) -> bool:
    """
    Attempt to copy directory using reflinks.
    """
    logger.debug(f"Attempting reflink copy from '{src}' to '{dst}'")

    try:
        # Use cp with --reflink=auto which falls back to regular copy if reflinks not supported
        # The '/./' at the end of the source path tells cp to copy the *contents* of the directory
        # rather than creating a new subdirectory in the destination
        Command('cp', '-a', '--reflink=auto', f"{src}/./", str(dst)).run(
            cwd=None, logger=logger, join=True, silent=True
        )
        return True
    except RunError as error:
        # Specific error for command failure (e.g. reflink not supported)
        logger.debug(f"Reflink copy command failed: {error}, falling back")
        return False
    # Let other exceptions (e.g. permissions, disk full) propagate


def _copy_tree_basic(
    src: Path,
    dst: Path,
    logger: 'tmt.log.Logger',
    workdir_root: Path,
) -> None:
    """
    Perform a basic recursive copy of a directory tree.

    Handles files, directories, and symlinks using standard shutil operations.
    Raises exceptions on failure.
    """
    logger.debug(f"Performing basic copy from '{src}' to '{dst}'")

    copied_count = 0
    for item in src.rglob('*'):
        relative_path = item.relative_to(src)
        dst_item = dst / relative_path

        if item.is_dir():
            dst_item.mkdir(parents=True, exist_ok=True)
            shutil.copystat(item, dst_item)
        elif item.is_file():
            dst_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dst_item)  # copy2 preserves metadata
            copied_count += 1
        elif item.is_symlink():
            if dst_item.exists() or dst_item.is_symlink():
                dst_item.unlink()
            link_target = os.readlink(item)
            os.symlink(link_target, dst_item)
            copied_count += 1  # Count symlinks as copied items

    logger.debug(f"Directory copied using basic copy: {copied_count} items processed.")


def copy_tree(
    src: Path,
    dst: Path,
    logger: 'tmt.log.Logger',
    workdir_root: Path,
) -> None:
    """
    Copy directory efficiently, trying different strategies.

    Attempts strategies in order:
    1. Reflinks (copy-on-write) if supported by the filesystem.
    2. Basic recursive copy as a fallback.

    Symlinks are always preserved.

    :param src: Source directory path
    :param dst: Destination directory path
    :param logger: Logger to use for debug messages
    :param workdir_root: The root directory for tmt's working files (e.g., /var/tmp/tmt),
    :raises GeneralError: when copying fails.
    """
    logger.debug(f"Copying directory tree from '{src}' to '{dst}'")

    # Create destination directory if it doesn't exist.
    # Let underlying operations fail if src doesn't exist to match shutil.copytree behaviour.
    dst.mkdir(parents=True, exist_ok=True)

    # 1. Try reflink copy
    if _copy_tree_reflinks(src, dst, logger, workdir_root):
        logger.debug("Copy finished using reflink strategy.")
        return

    # 2. Fallback to basic copy
    logger.debug("Falling back to basic copy strategy. (no reflink support in filesystem?)")
    try:
        _copy_tree_basic(src, dst, logger, workdir_root)
        logger.debug("Copy finished using basic copy strategy.")
    except Exception as error:
        raise GeneralError(f"Failed to copy directory tree from '{src}' to '{dst}'.") from error
