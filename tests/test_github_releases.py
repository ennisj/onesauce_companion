from __future__ import annotations

from onesauce_companion.services import github_releases


def test_fetch_latest_release_tag_reads_github_payload(monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"tag_name": "v0.1.2"}

    monkeypatch.setattr(github_releases.requests, "get", lambda *args, **kwargs: FakeResponse())

    assert github_releases.fetch_latest_release_tag() == "v0.1.2"


def test_is_newer_release_available_detects_higher_version() -> None:
    assert github_releases.is_newer_release_available("v0.1.1", "v0.1.2")


def test_is_newer_release_available_handles_release_codenames() -> None:
    assert github_releases.is_newer_release_available("v0.1.1 (Cherry)", "v0.1.2-cherry")


def test_is_newer_release_available_ignores_equal_or_older_versions() -> None:
    assert not github_releases.is_newer_release_available("v0.1.1", "v0.1.1")
    assert not github_releases.is_newer_release_available("v0.1.1", "v0.1.0")
