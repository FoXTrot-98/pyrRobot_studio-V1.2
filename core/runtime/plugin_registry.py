# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Plugin discovery.

Scans one or more directories for importable Python modules containing
Node subclasses (see sdk/pyrobot_plugin/node.py), and builds a registry
keyed by manifest.id. This is what powers:
  - GET /api/plugins  (palette the UI renders nodes from)
  - graph.add_node(plugin_id=...) resolving which class to instantiate

A plugin is "just a Python file with a Node subclass in it" — no
packaging/registration step required for local development. Installed
plugins (via pip, using an entry_points group) can be added later without
changing this interface.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Type

from sdk.pyrobot_plugin.node import Node
from sdk.pyrobot_plugin.manifest import PluginManifest

logger = logging.getLogger("pyrobot.plugin_registry")


@dataclass
class PluginEntry:
    manifest: PluginManifest
    node_class: Type[Node]
    source_path: Path


class PluginRegistry:
    def __init__(self):
        self._entries: dict[str, PluginEntry] = {}

    def scan_directory(self, directory: Path) -> list[str]:
        """Import every .py file under `directory` and register any Node
        subclasses found. Returns the list of plugin ids newly registered."""
        newly_registered = []
        if not directory.exists():
            logger.warning("plugin directory does not exist: %s", directory)
            return newly_registered

        for py_file in sorted(directory.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"pyrobot_plugins.{py_file.stem}_{abs(hash(str(py_file)))}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error("failed to import plugin file %s: %s", py_file, e)
                continue

            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is Node or not issubclass(obj, Node):
                    continue
                if obj.__module__ != module_name:
                    continue  # skip re-exported/imported classes, only register ones defined in this file
                manifest = getattr(obj, "manifest", None)
                if manifest is None:
                    logger.warning("Node subclass %s in %s has no manifest, skipping", obj.__name__, py_file)
                    continue
                if manifest.id in self._entries:
                    raise ValueError(f"Duplicate plugin id '{manifest.id}': {py_file} conflicts with {self._entries[manifest.id].source_path}")
                self._entries[manifest.id] = PluginEntry(manifest=manifest, node_class=obj, source_path=py_file)
                newly_registered.append(manifest.id)
                logger.info("registered plugin '%s' (%s) from %s", manifest.id, manifest.name, py_file.name)

        return newly_registered

    def get(self, plugin_id: str) -> PluginEntry:
        if plugin_id not in self._entries:
            raise KeyError(f"no plugin registered with id '{plugin_id}'")
        return self._entries[plugin_id]

    def list_manifests(self) -> list[dict]:
        return [entry.manifest.to_dict() for entry in self._entries.values()]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._entries
