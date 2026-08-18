# -*- coding: utf-8 -*-
""" Packaging of ``.vsi`` slides and their companion folders."""

from __future__ import annotations

import zipfile

import pytest


@pytest.fixture
def vsi_slide(tmp_path):
    """ A ``.vsi`` file with a populated companion folder next to it."""
    slide = tmp_path / "slide.vsi"
    slide.write_bytes(b"vsi-header")
    companion = tmp_path / "_slide_"
    (companion / "stack").mkdir(parents=True)
    (companion / "frame_0.ets").write_bytes(b"level-0")
    (companion / "stack" / "frame_1.ets").write_bytes(b"level-1")
    return slide


def test_ordinary_slides_upload_untouched(tmp_path):
    from pyslide.remote import _vsi as vsi

    slide = tmp_path / "slide.tif"
    slide.write_bytes(b"tiff")

    upload_path, cleanup = vsi.prepare_upload_path(slide)

    assert upload_path == slide.resolve()
    assert cleanup == []


def test_companion_folder_is_found_in_either_layout(tmp_path):
    from pyslide.remote import _vsi as vsi

    slide = tmp_path / "slide.vsi"
    slide.write_bytes(b"vsi")
    companion = tmp_path / "slide_"
    companion.mkdir()
    (companion / "frame_0.ets").write_bytes(b"data")

    assert vsi.require_companion(slide) == companion.resolve()


def test_missing_companion_folder_names_what_it_looked_for(tmp_path):
    from pyslide.remote import _vsi as vsi
    from pyslide.remote._errors import VsiPackageError

    slide = tmp_path / "slide.vsi"
    slide.write_bytes(b"vsi")

    with pytest.raises(VsiPackageError) as excinfo:
        vsi.prepare_upload_path(slide)

    message = str(excinfo.value)
    assert "_slide_" in message and "slide_" in message


def test_empty_companion_folder_is_rejected(tmp_path):
    from pyslide.remote import _vsi as vsi
    from pyslide.remote._errors import VsiPackageError

    slide = tmp_path / "slide.vsi"
    slide.write_bytes(b"vsi")
    (tmp_path / "_slide_").mkdir()

    with pytest.raises(VsiPackageError, match="no files in it"):
        vsi.require_companion(slide)


def test_zip_keeps_the_slide_and_companion_at_the_root(vsi_slide):
    from pyslide.remote import _vsi as vsi

    archive_path, cleanup = vsi.prepare_upload_path(vsi_slide)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = sorted(archive.namelist())
            assert names == [
                "_slide_/frame_0.ets",
                "_slide_/stack/frame_1.ets",
                "slide.vsi",
            ]
            assert archive.read("_slide_/stack/frame_1.ets") == b"level-1"
            # Slide pyramids are already compressed; storing avoids re-deflating
            # multi-gigabyte payloads for nothing.
            assert all(
                info.compress_type == zipfile.ZIP_STORED
                for info in archive.infolist()
            )
    finally:
        for path in cleanup:
            path.unlink(missing_ok=True)


def test_a_non_vsi_file_cannot_be_required_as_one(tmp_path):
    from pyslide.remote import _vsi as vsi
    from pyslide.remote._errors import VsiPackageError

    slide = tmp_path / "slide.tif"
    slide.write_bytes(b"tiff")

    with pytest.raises(VsiPackageError, match="not a .vsi file"):
        vsi.require_companion(slide)
