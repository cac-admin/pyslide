# -*- coding: utf-8 -*-
""" Packaging for slide formats that keep pixel data in a companion folder.

A ``.vsi`` file is only a small header: the pyramid levels live in a sibling
directory. Uploading the ``.vsi`` alone produces a slide the server cannot
read, so it is zipped together with that directory first.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from ._errors import VsiPackageError


__all__ = [
    "companion_candidates",
    "companion_dir",
    "require_companion",
    "zip_vsi_package",
    "prepare_upload_path",
]


def companion_candidates(vsi_path):
    """ Return the companion directory names used for a ``.vsi`` file.

    Both layouts seen next to ``slide.vsi`` are supported, preferring the
    leading-underscore export layout:

    * ``_slide_/``
    * ``slide_/``
    """
    vsi = Path(vsi_path).resolve()
    parent = vsi.parent
    stem = vsi.stem

    out = []
    for name in (f"_{stem}_", f"{stem}_"):
        candidate = parent / name
        if candidate not in out:
            out.append(candidate)
    return out


def companion_dir(vsi_path):
    """ Preferred companion directory for a ``.vsi`` file; may not exist."""
    return companion_candidates(vsi_path)[0]


def _has_files(directory):
    """ True when ``directory`` contains at least one file at any depth."""
    for _root, _dirs, files in os.walk(directory):
        if files:
            return True
    return False


def require_companion(vsi_path):
    """ Return the companion directory of a ``.vsi`` file.

    Returns
    -------
    pathlib.Path
        The directory that was found.

    Raises
    ------
    VsiPackageError
        The file is not a ``.vsi``, or no non-empty companion exists.
    """
    vsi = Path(vsi_path).resolve()
    if vsi.suffix.lower() != ".vsi":
        raise VsiPackageError(f"not a .vsi file: {vsi}")

    candidates = companion_candidates(vsi)
    empty = []
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if not _has_files(candidate):
            empty.append(candidate)
            continue
        return candidate

    if empty:
        listed = "\n".join(f"  empty:    {path}" for path in empty)
        raise VsiPackageError(
            f".vsi companion folder has no files in it.\n"
            f"  slide:    {vsi}\n"
            f"{listed}\n"
            f"The pyramid data inside that folder is the actual image."
        )

    listed = "\n".join(f"  expected: {path}" for path in candidates)
    raise VsiPackageError(
        f".vsi slides need their companion folder next to the file.\n"
        f"  slide:    {vsi}\n"
        f"{listed}\n"
        f"Move the companion folder beside the slide, or upload a zip that "
        f"contains both."
    )


def zip_vsi_package(vsi_path, dest_zip=None):
    """ Zip a ``.vsi`` file together with its companion folder.

    The archive keeps both at its root, so the server sees the same layout the
    format expects::

        slide.vsi
        _slide_/...

    Entries are stored without compression: slide pyramids are large and
    already compressed, so deflating them costs minutes and saves little.

    Parameters
    ----------
    vsi_path : str or path-like
        The ``.vsi`` file to package.
    dest_zip : str or path-like, optional
        Destination archive. A temporary file is created when omitted.

    Returns
    -------
    pathlib.Path
        Path of the archive written.
    """
    vsi = Path(vsi_path).resolve()
    companion = require_companion(vsi)
    parent = vsi.parent

    if dest_zip is None:
        handle, name = tempfile.mkstemp(prefix="pyslide_vsi_", suffix=".zip")
        os.close(handle)
        dest = Path(name)
    else:
        dest = Path(dest_zip)
        dest.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.write(vsi, arcname=vsi.name)
        for root, _dirs, files in os.walk(companion):
            for name in files:
                full = Path(root) / name
                archive.write(full, arcname=full.relative_to(parent).as_posix())

    return dest


def prepare_upload_path(image_path):
    """ Return the file to upload for ``image_path``.

    Ordinary slides upload as-is. A ``.vsi`` is packaged into a temporary zip
    that the caller is responsible for deleting.

    Returns
    -------
    upload_path : pathlib.Path
        File to hand to the upload call.
    cleanup_paths : list of pathlib.Path
        Temporary files to remove once the upload finishes.
    """
    path = Path(image_path).resolve()
    if path.suffix.lower() != ".vsi":
        return path, []

    archive = zip_vsi_package(path)
    return archive, [archive]
