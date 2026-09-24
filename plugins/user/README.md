# plugins/user/

Your own plugins go here. The backend auto-discovers any `Node` subclass
in this folder on startup — no registration step needed.

Generate a starting point with the CLI:

```bash
python -m sdk.cli create-plugin my_sensor --category Sensors --output reading:number
python -m sdk.cli create-plugin my_filter --category Processing --input in:number --output out:number
```

Then fill in the TODOs in the generated file and restart the backend.
