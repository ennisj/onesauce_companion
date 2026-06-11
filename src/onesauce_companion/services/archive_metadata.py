from __future__ import annotations

import copy
from typing import Mapping

from internetarchive import get_item, get_session

from onesauce_companion.models import ComponentSpec
from onesauce_companion.services.archive_org import USER_AGENT, ArchiveOrgCredentials, get_authenticated_config
from onesauce_companion.services.formatting import format_size_label


class ArchiveMetadataService:
    def __init__(
        self,
        auth_config: dict | None = None,
        authenticated_user: str | None = None,
        authenticated_email: str | None = None,
    ) -> None:
        self._auth_config = copy.deepcopy(auth_config) if auth_config is not None else None
        self._authenticated_user = authenticated_user
        self._authenticated_email = authenticated_email
        self._session = None
        self._item_sizes: dict[str, dict[str, int]] = {}

    def authenticate_with_archive_org(self, credentials: ArchiveOrgCredentials | None) -> str | None:
        if credentials is None:
            return None
        if self._authenticated_email == credentials.email and self._auth_config is not None:
            return self._authenticated_user
        self._auth_config, self._authenticated_user = get_authenticated_config(credentials)
        self._authenticated_email = credentials.email
        self._session = None
        self._item_sizes.clear()
        return self._authenticated_user

    def _get_session(self):
        if self._session is None:
            self._session = self._build_session()
        return self._session

    def size_for_spec(self, spec: ComponentSpec, credentials: ArchiveOrgCredentials | None = None) -> tuple[str, int | None]:
        if credentials is not None:
            try:
                self.authenticate_with_archive_org(credentials)
            except Exception:
                pass

        sizes = self._sizes_for_item(spec.archive_item)
        size_bytes = sizes.get(spec.filename)
        if size_bytes is None:
            return spec.size_display, spec.size_bytes
        return format_size_label(size_bytes), size_bytes

    def _sizes_for_item(self, archive_item: str) -> Mapping[str, int]:
        cached = self._item_sizes.get(archive_item)
        if cached is not None:
            return cached
        item = get_item(archive_item, archive_session=self._get_session())
        size_map: dict[str, int] = {}
        for file_metadata in item.files:
            name = file_metadata.get("name")
            size_value = file_metadata.get("size")
            if not isinstance(name, str) or not isinstance(size_value, (int, str)):
                continue
            try:
                size_map[name] = int(size_value)
            except ValueError:
                continue
        self._item_sizes[archive_item] = size_map
        return size_map

    def _build_session(self):
        session = get_session(config=self._auth_config)
        session.headers.update({"User-Agent": USER_AGENT})
        original_request = session.request

        def request_with_default_timeout(*args, **kwargs):
            kwargs.setdefault("timeout", 15)
            return original_request(*args, **kwargs)

        session.request = request_with_default_timeout  # type: ignore[assignment]
        return session

