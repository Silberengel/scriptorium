# Scriptorium Publisher VS Code Extension

A GUI extension for the Scriptorium publisher tool, making it easy to publish books and publications to Nostr without using the command line.

## Features

- **Initialize Metadata**: Generate `@metadata.yml` from your source files
- **Generate Events**: Convert HTML/AsciiDoc to Nostr events
- **Publish**: Publish events to your Nostr relay
- **Quality Control**: Verify events are present on the relay
- **Broadcast/Delete**: Manage entire publications

## Installation

1. Open VS Code
2. Go to Extensions (Ctrl+Shift+X)
3. Click "..." menu → "Install from VSIX..."
4. Select the `.vsix` file (build it first with `vsce package`)

Or install from source:
1. `cd .vscode-extension`
2. `npm install`
3. Press F5 to run in Extension Development Host

## Usage

### Command Palette

Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac) and type "Scriptorium" to see all commands.

### GUI Panel

1. Open the Command Palette
2. Run "Scriptorium: Open Publisher Panel"
3. Use the buttons to perform actions

### Explorer Context Menu

Right-click on `.html` or `.adoc` files in the explorer to see Scriptorium options.

### Settings

Configure in VS Code settings:
- `scriptorium.relayUrl`: Default relay URL
- `scriptorium.secretKey`: Your Nostr secret key (optional, can use env var)
- `scriptorium.outputDir`: Output directory for events
- `scriptorium.sourceType`: Default source type (HTML/ADOC/etc.)

## Requirements

- Python 3.8+
- The Scriptorium publisher package installed in your workspace
- Nostr secret key (nsec or hex)

## Building

```bash
cd .vscode-extension
npm install
npm run compile
vsce package  # Requires vsce: npm install -g @vscode/vsce
```

## Development

1. `npm install`
2. Press F5 to launch Extension Development Host
3. Make changes and reload (Ctrl+R in Extension Development Host)

