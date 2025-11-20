# Scriptorium Publisher VS Code Extension

A GUI extension for the Scriptorium publisher tool, making it easy to publish books and publications to Nostr without using the command line.

## Features

- **Initialize Metadata**: Generate `@metadata.yml` from your source files with a wizard
- **Generate Events**: Convert HTML/AsciiDoc to Nostr events with progress tracking
- **Publish**: Publish events to your Nostr relay with verification
- **Quality Control**: Verify events are present on the relay and republish missing ones
- **Read Publications**: Fetch and display publications from relays
- **Broadcast/Delete**: Manage entire publications across relays
- **Input File Management**: Add files, open folders, and manage input directory
- **All-in-One Workflow**: Run generate → publish → qc in sequence

## Installation

### From VSIX Package

1. Build the extension:
   ```bash
   cd .vscode-extension
   npm install
   npm run compile
   vsce package  # Requires: npm install -g @vscode/vsce
   ```

2. Install in VS Code:
   - Open VS Code
   - Go to Extensions (Ctrl+Shift+X / Cmd+Shift+X)
   - Click "..." menu → "Install from VSIX..."
   - Select `scriptorium-publisher-0.1.0.vsix`

### From Source

1. Open the project in VS Code
2. Go to `.vscode-extension` directory
3. Run `npm install`
4. Press F5 to launch Extension Development Host

## Usage

### Command Palette

Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac) and type "Scriptorium" to see all commands:

- **Scriptorium: Initialize Metadata** - Generate `@metadata.yml` from source
- **Scriptorium: Generate Events** - Convert source to Nostr events
- **Scriptorium: Publish to Relay** - Publish events to relay
- **Scriptorium: Quality Control** - Verify events on relay
- **Scriptorium: All (Generate → Publish → QC)** - Run complete workflow
- **Scriptorium: Broadcast Publication** - Broadcast to another relay
- **Scriptorium: Delete Publication** - Delete from a relay
- **Scriptorium: Read Publication** - Read and display from relay
- **Scriptorium: Open Publisher Panel** - Open the main GUI panel
- **Scriptorium: Open Settings** - Open extension settings

### GUI Panel

1. Open the Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
2. Run "Scriptorium: Open Publisher Panel"
3. Use the buttons to:
   - Initialize metadata
   - Generate events
   - Publish to relay
   - Run QC checks
   - Manage input files
   - Read publications

### Explorer Context Menu

Right-click on `.html` or `.adoc` files in the explorer to see Scriptorium options.

### Settings

Configure in VS Code settings (File → Preferences → Settings, search "scriptorium"):

- **`scriptorium.relayUrl`**: Default relay URL (default: `wss://thecitadel.nostr1.com`)
- **`scriptorium.secretKey`**: Your Nostr secret key (nsec or hex, optional - can use `SCRIPTORIUM_KEY` env var)
- **`scriptorium.outputDir`**: Output directory for events (default: `uploader/publisher/out`)
- **`scriptorium.sourceType`**: Default source type (HTML/ADOC/MARKDOWN/RTF/EPUB, default: `HTML`)
- **`scriptorium.inputDir`**: Input directory for source files (default: `uploader/input_data`)

### Input File Management

The extension provides GUI tools to manage your input files:

- **Add File**: Copy files to the input directory
- **Open Folder**: Open the input directory in file explorer
- **Browse Input Directory**: Select a different input directory
- **Refresh**: Refresh the file list

### Reading Publications

The extension includes a publication reader that can:

- Fetch publications from relays using:
  - `nevent` (bech32 encoded event reference)
  - `naddr` (bech32 encoded address)
  - `hex event ID` (64 hex characters)
  - `kind:pubkey:d-tag` (colon-separated format)
- Recursively fetch all child events via a-tags
- Display publication metadata and content
- Stream updates as events are found

## Requirements

- **Python 3.8+**: The extension uses the Python publisher scripts
- **Scriptorium Publisher**: The publisher package must be installed in your workspace
- **Virtual Environment**: The extension will use `.venv/bin/python3` if available
- **Nostr Secret Key**: Required for publishing (nsec or hex format)

## Workflow

### Typical Workflow

1. **Prepare Source File**:
   - Place your source file (HTML/AsciiDoc) in the input directory
   - Use the GUI to add files or manage the input directory

2. **Initialize Metadata**:
   - Run "Scriptorium: Initialize Metadata" from Command Palette
   - Or use the GUI panel button
   - Edit `@metadata.yml` if needed

3. **Generate Events**:
   - Run "Scriptorium: Generate Events" from Command Palette
   - Or use the GUI panel button
   - Review the generated events in the output directory

4. **Publish**:
   - Ensure `SCRIPTORIUM_KEY` is set (or configure in settings)
   - Run "Scriptorium: Publish to Relay" from Command Palette
   - Or use the GUI panel button
   - Monitor progress in the output panel

5. **Quality Control**:
   - Run "Scriptorium: Quality Control" to verify events
   - Use `--republish` option to republish missing events

### All-in-One Workflow

Use "Scriptorium: All (Generate → Publish → QC)" to run the complete workflow in one command.

## Building

```bash
cd .vscode-extension
npm install
npm run compile
vsce package  # Requires: npm install -g @vscode/vsce
```

## Development

1. Install dependencies:
   ```bash
   cd .vscode-extension
   npm install
   ```

2. Make changes to TypeScript files in `src/`

3. Compile:
   ```bash
   npm run compile
   ```

4. Test:
   - Press F5 to launch Extension Development Host
   - Or install the VSIX package in a separate VS Code instance

5. Reload extension:
   - Press Ctrl+R (Cmd+R on Mac) in Extension Development Host
   - Or restart VS Code

## Troubleshooting

### Python Not Found

The extension looks for Python in this order:
1. `.venv/bin/python3` (if virtual environment exists)
2. `python3` (system)
3. `python` (system)

If Python is not found, ensure it's in your PATH or create a virtual environment in the workspace root.

### Module Not Found Errors

If you see "ModuleNotFoundError", ensure dependencies are installed:
```bash
pip install -r uploader/publisher/requirements.txt
```

Or if using a virtual environment:
```bash
.venv/bin/pip install -r uploader/publisher/requirements.txt
```

### Extension Not Loading

- Check the Output panel (View → Output → Select "Scriptorium Publisher")
- Ensure Python is available
- Check that the publisher package is in the workspace

## Related Documentation

- **Main README**: [../README.md](../README.md)
- **Publisher Documentation**: [../uploader/publisher/README.md](../uploader/publisher/README.md)

## License

MIT License - see [LICENSE](LICENSE) file.
