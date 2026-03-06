from onesauce_updater.services.versioning import parse_build_version, parse_version_from_filename


def test_parse_build_version() -> None:
    text = "OneSauce\nUpdated: 2024-10-08\nBuild v2.0b5\n"
    assert parse_build_version(text) == "v2.0b5"


def test_parse_version_from_filename() -> None:
    assert parse_version_from_filename("OneSauce v2.0b6.zip") == "v2.0b6"
