# Zoom MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets Claude (or any other MCP client) **read, create and edit
the patches of a Zoom G1 FOUR / G1X FOUR multi-effects pedal** over USB. Ask Claude for a sound —
*"an AC/DC-style crunch with a touch of delay in slot 12"* — and it builds the patch and saves it to your pedal.

> Unofficial project, not affiliated with ZOOM Corporation. The protocol was reverse-engineered.
> Use at your own risk: the server makes automatic backups, but there is no warranty.

---

## Compatibility

| | Status |
|---|---|
| **G1X FOUR**, firmware 2.00 | ✅ Tested (read, write, preview) |
| **G1 FOUR** | 🟡 Should work (same family and protocol, model ID 0x6E). Untested |
| B1 FOUR / B1X FOUR / B2 FOUR | ❔ Similar protocol according to the community. Read-only unless verified |
| MS-50G/60B/70CDR, G3n/G5n, G6, MS Plus… | ❌ Different protocol |
| **Windows** | ✅ Tested. Uses the native MIDI API, no extra dependencies |
| **macOS / Linux** | 🟡 Implemented with `python-rtmidi`, not tested yet |

If the server detects an unverified model, **writing is disabled** and only reading is allowed.

## Requirements

- Python 3.10 or newer (on macOS/Linux prefer 3.12 or 3.13, so `python-rtmidi` installs without compiling)
- The pedal connected over USB
- **Zoom Guitar Lab closed** while using the server: only one program can use the MIDI port at a time
- Internet access the first time, to download Zoom's official effect list

## Installation

### 1. Get the project and install the dependencies

```bash
git clone https://github.com/jesus2419/ZoomMcpServer.git
cd ZoomMcpServer
python -m venv .venv
```

Activate the environment: `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on macOS/Linux. Then:

```bash
pip install -r requirements.txt
```

### 2. Set up your pedal (once)

Connect the pedal, close Guitar Lab and run:

```bash
python zoom_mcp/setup_pedal.py
```

This **writes nothing to the pedal**. It:

1. Detects the model, firmware and number of patches.
2. Makes a **full backup** of your patches in `zoom_mcp/backups/`.
3. Reads the effects installed on *your* pedal, with their internal IDs.
4. Downloads Zoom's official effect list to get each parameter and its range.
5. Builds the catalog `zoom_mcp/data/effects.json` and validates it by decoding all of your patches.

If you later add or remove effects with Guitar Lab, run `python zoom_mcp/setup_pedal.py --refresh`.

### 3. Register the server with Claude

Use **absolute paths**: the Python from your virtual environment and the project's `server.py`.

**Claude Code:**

```bash
claude mcp add zoom-pedal --scope user -- "C:\path\ZoomMcpServer\.venv\Scripts\python.exe" "C:\path\ZoomMcpServer\zoom_mcp\server.py"
```

On macOS/Linux the Python is at `.venv/bin/python`. Check that it connects with `claude mcp get zoom-pedal`.

**Claude Desktop:** edit `claude_desktop_config.json`. It lives in `%APPDATA%\Claude\` on Windows and in
`~/Library/Application Support/Claude/` on macOS.

```json
{
  "mcpServers": {
    "zoom-pedal": {
      "command": "C:\\path\\ZoomMcpServer\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\ZoomMcpServer\\zoom_mcp\\server.py"]
    }
  }
}
```

Restart Claude and open a new conversation: tools are loaded when a session starts.

## Usage

Just talk to Claude. For example:

- *"What patches do I have?"*
- *"Show me what's in patch 12"*
- *"Let me hear a clean surf tone with chorus and spring reverb, without saving it"*
- *"Save it to slot 20 as SurfClean"*
- *"Turn up the amp gain on patch 5 and switch off the delay"*
- *"Restore patch 20 to how it was before"*

The server's tool descriptions and responses are in Spanish; Claude handles them in any language.

### Tools

| Tool | What it does |
|---|---|
| `device_info` | Model, firmware, number of patches and catalog status |
| `list_effects` | Installed effects with parameters and ranges (filter by category) |
| `list_patches` | Every patch with its effect chain |
| `read_patch` / `read_current_patch` | Details of a stored patch / of the one currently playing |
| `preview_patch` | Loads a sound so you can hear it **without saving** |
| `create_patch` | Creates a patch and saves it to a slot |
| `update_patch` | Changes parameters, effects, on/off state or name of a patch |
| `copy_patch` | Copies a patch to another slot |
| `select_patch` | Switches the pedal to a patch |
| `backup_all` / `list_backups` / `restore_backup` | Backups |

### Safety and backups

- **Before every write**, the previous content of the slot is saved to `zoom_mcp/backups/slotNN-<date>.json`.
- `setup_pedal.py` and `backup_all` save full backups (`all-<date>.json`).
- To undo, ask Claude to *"restore patch N"* or use `restore_backup`.
- Backups and `data/` are in `.gitignore`: they hold your personal patches and generated data.

## Known limitations

- **Claude can't hear the sound.** It chooses effects and values from musical knowledge; fine-tuning by ear is up to you.
- Tempo-synced times are shown as `SYNC0`, `SYNC1`…: the number is the index of the note value, whose exact
  value is not documented.
- When saving, the pedal resets a few internal bytes in the PPRM block. Effects and name are not affected.
- If an effect is missing from the official list, its parameters are exposed as `P1`, `P2`… with raw values.

## Troubleshooting

| Problem | Fix |
|---|---|
| `No se encontró la pedalera Zoom` (pedal not found) | Check the USB cable and **close Guitar Lab**. If your MIDI port name doesn't contain "ZOOM", set `ZOOM_MIDI_PORT` to part of its name |
| `Falta el catálogo de efectos` (effect catalog missing) | Run `python zoom_mcp/setup_pedal.py` and restart Claude |
| `Escritura desactivada: … no está verificado` (writing disabled, unverified model) | Your model hasn't been tested. See *Adding support for another model* |
| `pip` fails installing `python-rtmidi` | Use Python 3.12/3.13, or install your system's build tools |
| You want rtmidi on Windows | Set `ZOOM_MIDI_BACKEND=rtmidi` |

## Tests

```bash
python tests/mcp_client_test.py
```

Starts the server over MCP and calls read-only tools.

```bash
python tests/smoke_test.py --write 49
```

Creates and edits a patch in slot 49, then restores it.

## How it works (protocol)

Verified on a G1X FOUR with firmware 2.00. Every message is SysEx `F0 52 00 6E … F7`, with data packed 8→7 bits:
one byte holding the high bits (bit 6 = first byte) followed by 7 data bytes.

| Command | Function |
|---|---|
| `F0 7E 00 06 01 F7` | Universal MIDI identity request: model and firmware |
| `44` → `43` | Number of patches, patch size and patches per bank |
| `50` / `51` | Enter / leave edit mode |
| `29` → `28` | Read the current patch (requires edit mode) |
| `28 <data>` | Write the current patch, without saving |
| `09 00 <bank> <patch> 00` → `08 …` | Read a patch from memory |
| `08 00 <bank> <patch> <len lo> <len hi> <data> <crc32 in 5 bytes>` | Save a patch to memory |
| `60 25/26/27` | List files on the pedal |
| `60 20/22/21` | Read a file from the pedal |

Patch layout: `PTCF` with the name (10 bytes at 0x1A) and the effect IDs (from 0x24), followed by the chunks
`TXJ1` and `TXE1` (descriptions), `EDTB` and `PPRM`. Each effect takes 24 bytes in `EDTB`, little-endian:

- bit 0: on/off
- bits 1–28: effect ID
- from bit 30: parameters, the first 5 are 12 bits wide and the rest 8 bits

Raw values are the index from the bottom of the range. EQ gains use 0.5 dB steps.

Effect IDs and names come from the header of each `.ZD2` file on the pedal. Parameters and ranges come from Zoom's
official list, with hand-verified corrections in [`overrides.py`](zoom_mcp/overrides.py).

### Repository layout

```
zoom_mcp/
  server.py        MCP server (tools)
  setup_pedal.py   initial setup: backup + catalog
  catalog.py       catalog building and validation
  overrides.py     hand-verified parameter definitions
  zoompatch.py     patch format and value conversion
  zoomdev.py       pedal SysEx commands
  zfiles.py        reading files from the pedal
  midi.py          picks the MIDI backend · winmidi.py (Windows) · rtmidi_port.py (macOS/Linux)
  data/            generated by setup_pedal.py (not committed)
  backups/         your backups (not committed)
tests/
```

### Adding support for another model

1. Run `python zoom_mcp/setup_pedal.py --force` (read-only) and check that validation reports 0 errors.
2. If your model has a different effect list, pass it with `--fxlist-url <URL of Zoom's "FX list" PDF>`.
3. Test writing on a slot you don't care about. To do so, add your model ID to `VERIFIED_MODELS` in
   `zoomdev.py` and run `tests/smoke_test.py --write <slot>`.
4. If everything works, open a PR with the model and firmware you tested.

## Credits

- File and patch commands based on [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2).
- Effect parameters from ZOOM's official *Effect Types and Parameters* document. It is downloaded at setup time
  and is not redistributed.

ZOOM, G1 FOUR, G1X FOUR and Guitar Lab are trademarks of ZOOM Corporation. Amplifier and effect model names
belong to their respective owners.

## License

[MIT](LICENSE)
