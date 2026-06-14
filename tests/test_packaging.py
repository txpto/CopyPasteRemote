import os

import pytest

from cpr_client import packaging


def test_pack_unpack_files_and_folders(tmp_path):
    src = tmp_path / "src"
    (src / "docs" / "deep").mkdir(parents=True)
    (src / "docs" / "readme.txt").write_text("readme", encoding="utf-8")
    (src / "docs" / "deep" / "x.bin").write_bytes(b"\x00\x01\x02\x03")
    (src / "top.txt").write_text("top file", encoding="utf-8")

    paths = [str(src / "docs"), str(src / "top.txt")]
    zip_path, entries, total = packaging.pack_paths(paths, dest_dir=str(tmp_path))
    try:
        assert os.path.isfile(zip_path)
        names = {e.name: e for e in entries}
        assert names["docs"].is_dir is True
        assert names["top.txt"].is_dir is False
        assert total > 0

        dest = tmp_path / "out"
        top = packaging.unpack_zip(zip_path, str(dest))
        top_names = {os.path.basename(p) for p in top}
        assert top_names == {"docs", "top.txt"}
        assert (dest / "docs" / "readme.txt").read_text(encoding="utf-8") == "readme"
        assert (dest / "docs" / "deep" / "x.bin").read_bytes() == b"\x00\x01\x02\x03"
        assert (dest / "top.txt").read_text(encoding="utf-8") == "top file"
    finally:
        packaging._safe_remove(zip_path)


def test_empty_folder_survives(tmp_path):
    src = tmp_path / "emptyroot"
    (src / "empty").mkdir(parents=True)
    zip_path, entries, total = packaging.pack_paths([str(src)], dest_dir=str(tmp_path))
    try:
        dest = tmp_path / "out"
        packaging.unpack_zip(zip_path, str(dest))
        assert (dest / "emptyroot" / "empty").is_dir()
    finally:
        packaging._safe_remove(zip_path)


def test_missing_path_raises(tmp_path):
    with pytest.raises(packaging.PackagingError):
        packaging.pack_paths([str(tmp_path / "nope")])


def test_zip_slip_guard(tmp_path):
    import zipfile

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(str(evil), "w") as zf:
        zf.writestr("../escape.txt", "nope")
    with pytest.raises(packaging.PackagingError):
        packaging.unpack_zip(str(evil), str(tmp_path / "dest"))
