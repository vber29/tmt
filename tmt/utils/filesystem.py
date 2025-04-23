"""
Utility functions for filesystem operations.
"""

import os
import shutil
import subprocess

import tmt.log
from tmt._compat.pathlib import Path


def _copy_tree_reflinks(
    src: Path,
    dst: Path,
    logger: 'tmt.log.Logger',
    workdir_root: Path,  # Keep signature consistent, even if not used here
) -> bool:
    """
    Attempt to copy directory using reflinks.

    Returns True on success, False on failure.
    """
    try:
        logger.debug(f"Attempting reflink copy from '{src}' to '{dst}'")

        # Create destination directory if it doesn't exist
        # Check if src exists first
        if not src.exists():
            logger.debug(f"Source directory '{src}' does not exist, skipping reflink copy")
            return False  # Indicate failure as source doesn't exist

        dst.mkdir(parents=True, exist_ok=True)

        # Use cp with --reflink=auto which falls back to regular copy if reflinks not supported
        # The '/./' at the end of the source path tells cp to copy the *contents* of the directory
        # rather than creating a new subdirectory in the destination
        subprocess.run(
            ['cp', '-a', '--reflink=auto', f"{src}/./", str(dst)],
            check=True,
            stderr=subprocess.PIPE,
        )
        logger.debug("Directory copied using reflink")
        return True
    except subprocess.CalledProcessError as error:
        # Specific error for command failure
        logger.debug(f"Reflink copy command failed: {error}, falling back")
        return False
    except Exception as error:
        # Broad exception for unexpected issues or mock testing
        logger.debug(f"Reflink copy failed (unexpected error): {error}, falling back")
        return False


def _copy_tree_basic(
    src: Path,
    dst: Path,
    logger: 'tmt.log.Logger',
    workdir_root: Path,
) -> bool:
    """
    Perform a basic recursive copy of a directory tree.

    Handles files, directories, and symlinks using standard shutil operations.
    Returns True on successful completion.
    """
    logger.debug(f"Performing basic copy from '{src}' to '{dst}'")

    if not dst.exists():
        dst.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        logger.debug(f"Source directory '{src}' does not exist, skipping basic copy")
        return True

    copied_count = 0
    try:
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
    except Exception as e:
        logger.warning(f"Basic copy failed during processing: {e}")
        return False

    logger.debug(f"Directory copied using basic copy: {copied_count} items processed.")
    return True


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
                         used for the hardlink cache.
    """
    logger.debug(f"Copying directory tree from '{src}' to '{dst}'")

    # 1. Try reflink copy
    if _copy_tree_reflinks(src, dst, logger, workdir_root):
        logger.debug("Copy finished using reflink strategy.")
        return

    # 2. Fallback to basic copy
    logger.debug("Falling back to basic copy strategy. (no reflink support in filesystem?)")
    if _copy_tree_basic(src, dst, logger, workdir_root):
        logger.debug("Copy finished using basic copy strategy.")
        return

    logger.warning(f"All copy strategies failed for '{src}' to '{dst}'.")
