"""
Property data loader — ingests properties from JSON files.

Simple for now: loads a JSON array of property objects and validates
each against the Property pydantic model. Designed to be extensible
to CSV/BC Assessment database formats later.

Expected JSON format: a list of property dicts, each matching the
Property model schema (see sim/properties/models.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from sim.properties.models import Property


def load_properties_from_json(path: Union[str, Path]) -> list[Property]:
    """
    Load and validate properties from a JSON file.

    Parameters
    ----------
    path:
        Path to a JSON file containing a list of property dicts.

    Returns
    -------
    list[Property]
        Validated Property objects.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the JSON is not a list, or any item fails validation.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Property data file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError(f"Expected a JSON array, got {type(raw).__name__}")

    properties: list[Property] = []
    for i, item in enumerate(raw):
        try:
            prop = Property.model_validate(item)
            properties.append(prop)
        except Exception as exc:
            raise ValueError(f"Property at index {i} failed validation: {exc}") from exc

    return properties


def load_properties_from_dict(data: list[dict]) -> list[Property]:
    """
    Load and validate properties from a list of dicts (e.g., from an API).

    Parameters
    ----------
    data:
        List of property dicts.

    Returns
    -------
    list[Property]
    """
    properties: list[Property] = []
    for i, item in enumerate(data):
        try:
            properties.append(Property.model_validate(item))
        except Exception as exc:
            raise ValueError(f"Property at index {i} failed validation: {exc}") from exc
    return properties
