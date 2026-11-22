"""Test guard: tests must not depend on AWS or Nova Act environment variables.

Reading any `AWS_*` or `NOVA_ACT_*` variable fails the test, so a code path that quietly
reaches for real credentials is caught. A test that exercises that logic on purpose (for
example log redaction) opts out with `@pytest.mark.allow_secret_env`, then sets fake values
through `monkeypatch.setenv`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, MutableMapping
from typing import Any

import pytest

FORBIDDEN_PREFIXES = ("AWS_", "NOVA_ACT_")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "allow_secret_env: test may read AWS_* and NOVA_ACT_* variables (fake values only)",
    )


class GuardedEnviron(MutableMapping[str, str]):
    """Copy of os.environ without AWS/Nova Act variables, which raises if they are read."""

    def __init__(self, source: Any) -> None:
        self._data = {
            k: v for k, v in source.items() if not k.upper().startswith(FORBIDDEN_PREFIXES)
        }

    @staticmethod
    def _check(key: str) -> None:
        if key.upper().startswith(FORBIDDEN_PREFIXES):
            raise AssertionError(f"test read forbidden environment variable {key!r}")

    def __getitem__(self, key: str) -> str:
        self._check(key)
        return self._data[key]

    def __setitem__(self, key: str, value: str) -> None:
        self._data[key] = value

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            self._check(key)
        return key in self._data

    def copy(self) -> dict[str, str]:
        return dict(self._data)


@pytest.fixture(autouse=True)
def _forbid_cloud_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("allow_secret_env"):
        for name in list(os.environ):
            if name.upper().startswith(FORBIDDEN_PREFIXES):
                monkeypatch.delenv(name)
        return
    monkeypatch.setattr(os, "environ", GuardedEnviron(os.environ))
