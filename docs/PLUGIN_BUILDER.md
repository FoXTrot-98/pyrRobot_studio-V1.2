# Build plugins in Studio

Click **Plugin Builder** in the toolbar while the local graph is stopped.

1. Choose **Processing** or **Sensor source**, then enter a unique slug and display name. Generated IDs use `user.<slug>`.
2. Add input/output ports. Choose an existing versioned message schema to validate payloads, or an untyped payload for early experiments. Expand the schema to inspect its fields and units. Add parameters with defaults and numeric limits.
3. Enter sample JSON and select **Generate Python**. The processing template copies each input payload to its outputs. The sensor template emits the sample every 100 ms. These are working examples, not automatically generated hardware drivers.
4. Edit the Python source as needed. Form changes require regeneration, which asks before replacing code edits. Parameter values are accessible with `self.get_param('name')`. Publish with `self.emit('output', payload)`.
5. Acknowledge that you trust the code, then **Test plugin**. The test starts the node in a child Python process, injects the same sample into each input, collects outputs/logging, and stops the node. Inspect the report for schema errors or exceptions. The eight-second timeout includes importing, starting and stopping; **Cancel test** terminates the worker early.
6. **Export package** downloads a version 2 JSON package containing the form, Python and sample data. Import restores all three, including whether form changes have been regenerated into Python. Older version 1 packages still import Python/sample only. Dependencies are not bundled or automatically installed.
7. **Install tested plugin** writes the exact successfully tested source under `plugins/user/`. Stop the graph before installation. Existing filenames and registered IDs are never overwritten. Restart the backend and reload Studio to discover it in the palette.

Changes to Python disable installation until it passes another test. A successful test confirms only the supplied sample and short lifecycle: it is not hardware qualification or proof of correctness for all inputs.

The current draft is saved automatically in this browser and restored when you reopen the builder, including unfinished form/code edits. Trust acknowledgements and test results are never restored: review and test again before installing. Use **New draft** to replace the working draft, or export separate packages to keep multiple plugins. Browser storage is local to its origin; clearing browser data removes the draft. Do not put passwords or secrets in plugin source or parameter defaults. Test results show errors, output messages and logs separately, with the full report available below.

## Trust and isolation

Testing does not import the draft into the Studio backend process. It runs with the same OS account in a disposable subprocess, using an in-memory capture bus rather than the live robot graph. Nevertheless, Python can access files, networks and hardware directly. This is **not a security sandbox**. Only test trusted code. The worker timeout/cancel terminates the worker itself, not arbitrary subprocesses that custom code may spawn. Do not use the builder to run untrusted downloaded Python.

Installation does not execute the draft in the backend. Normal plugin discovery imports it after backend restart. Files are installed without overwriting existing files; renaming IDs creates new plugins rather than updating old ones.

This initial builder supports sensor/processing templates, port and parameter forms, source editing, schema validation through tests, captured Python logging, sample injection, cancellation, source-package import/export and installation. It does not provide actuator safety qualification, automatic vendor-protocol generation, dependency installation, a debugger, or AI generation.

## Verification

`python tests/run_all.py` includes generator validation, sensor and processing execution, typed payload rejection, duplicate installation protection and test timeout/cancellation. `python tests/browser_plugin_builder.py` checks the GUI workflow using Playwright and Edge. The worker requires the same Python environment as Studio.
