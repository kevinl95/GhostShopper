"""Load and validate the YAML config. Every invalid field is reported (Requirement 17.5)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ghostshopper.config.models import Config


class ConfigError(Exception):
    """The config file is unreadable or invalid. `errors` has one line per problem."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors))


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a mapping key that appears twice."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            try:
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        None,
                        None,
                        f"duplicate key {key!r}",
                        key_node.start_mark,
                    )
                seen.add(key)
            except TypeError:
                pass  # unhashable key; the base class reports it
        return super().construct_mapping(node, deep)


def _format_loc(loc: tuple[int | str, ...]) -> str:
    parts = [str(p) for p in loc if p != "[key]"]
    path = ".".join(parts) or "<root>"
    return f"{path} (key)" if loc and loc[-1] == "[key]" else path


def parse_config(data: Mapping[str, Any] | Any) -> Config:
    """Validate an already-parsed mapping."""
    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        errors = [f"{_format_loc(e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(errors) from None


def load_config(path: str | Path) -> Config:
    """Read a YAML file with `yaml.safe_load` semantics and validate it."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError([f"cannot read {path}: {exc.strerror or exc}"]) from None
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (SafeLoader subclass)
    except yaml.YAMLError as exc:
        raise ConfigError([f"invalid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise ConfigError(["<root>: the file must contain a mapping"])
    return parse_config(data)


def dump_config(config: Config) -> str:
    """Render a config back to YAML. Decimals are written as strings, so a reload is equal."""
    return yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False)
