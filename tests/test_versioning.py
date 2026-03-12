from onesauce_companion.services.versioning import (
    parse_build_version,
    parse_version_from_filename,
    read_version_from_named_subfolders,
)


def test_parse_build_version() -> None:
    text = "OneSauce\nUpdated: 2024-10-08\nBuild v2.0b5\n"
    assert parse_build_version(text) == "v2.0b5"


def test_parse_version_from_filename() -> None:
    assert parse_version_from_filename("OneSauce v2.0b6.zip") == "v2.0b6"



def test_read_version_from_named_subfolders(tmp_path):
    (tmp_path / "Amiga_2023 10 11 Sys Spec_v2.0b2").mkdir()
    (tmp_path / "Amiga_2023 10 11 Sys Spec_v2.0b3").mkdir()
    (tmp_path / "Other Packv2.0b9").mkdir()
    (tmp_path / "Amiga_2023 10 11 Sys Spec_v2.0b2" / "file.txt").write_text("x")
    (tmp_path / "Amiga_2023 10 11 Sys Spec_v2.0b3" / "file.txt").write_text("x")

    assert read_version_from_named_subfolders(tmp_path, "Amiga") == "v2.0b3"


def test_read_version_from_named_subfolders_ignores_non_matching_names(tmp_path):
    (tmp_path / "Amiga CD32 Sys Specv2.0b2").mkdir()

    assert read_version_from_named_subfolders(tmp_path, "Amiga Sys Spec") is None


def test_read_version_from_named_subfolders_requires_non_empty_directory(tmp_path):
    (tmp_path / "Amiga_2023 10 11 Sys Spec_v2.0b3").mkdir()

    assert read_version_from_named_subfolders(tmp_path, "Amiga") is None
