# SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
# SPDX-License-Identifier: Apache-2.0

"""
Example plugin: subscribes to any upstream port and counts/logs messages.
Used to prove that graph edges (output port of node A -> input port of
node B) actually route messages, not just single-node pub/sub.
"""

from sdk.pyrobot_plugin import Node, PluginManifest, PortSpec, PortDataType


class LoggerNode(Node):
    manifest = PluginManifest(
        id="pyrobot.examples.logger",
        name="Logger",
        category="Processing (Examples)",
        description="Counts and logs every message received on its input port.",
        inputs=[PortSpec("in", PortDataType.ANY)],
        outputs=[],
    )

    def on_start(self) -> None:
        self.count = 0
        self.last_payload = None

    def on_message(self, port: str, message) -> None:
        self.count += 1
        self.last_payload = message.payload
        self.log.debug("received #%d on '%s': %s", self.count, port, message.payload)
