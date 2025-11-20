# Scriptorium

Scriptorium is a comprehensive toolchain for converting documents to structured formats and publishing them to the Nostr network as bookstr publications. It supports multiple input formats, converts them to AsciiDoc, and publishes hierarchical book structures to Nostr relays using NKBIP-01 and NKBIP-08 standards.

It contains a VS Code extension, for reading published kind 30040 documents. You can also install the Asciidoctor extension in your IDE and view the Asciidoc as publications, before publishing as events.

## Overview

Scriptorium consists of two main components:

1. **Document Converter**: Converts various document formats (PDF, TXT, HTML, LaTeX, Markdown, RTF, DOCX, ODT, EPUB) to AsciiDoc using Pandoc. *(This part is under construction.)*
2. **Nostr Bookstr Publisher**: Publishes structured book content to Nostr relays as hierarchical events (NKBIP-01/NKBIP-08 compliant)

## Features

- **Multi-format Support**: Convert from PDF, TXT, HTML, LaTeX, Markdown, RTF, DOCX, ODT, and EPUB to AsciiDoc
- **Nostr Publishing**: Publish books and publications to Nostr relays with full NKBIP-01 and NKBIP-08 compliance
- **Hierarchical Structure**: Automatically parses and organizes content into Collections → Books → Chapters → Verses/Sections
- **Book Wikilinks**: Support for NKBIP-08 tags enabling book wikilink resolution (e.g., `[[book::bible | genesis 2:4 | kjv]]`)
- **VS Code Extension**: GUI interface for non-CLI users
- **Quality Control**: Built-in QC tools to verify publication completeness
- **Publication Management**: Broadcast, delete, and read publications from relays

## Quick Start

### Prerequisites

- Python 3.8+
- Node.js 18+ (for VS Code extension)
- Pandoc (for document conversion)

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/silberengel/scriptorium.git
   cd scriptorium
   ```

2. Set up Python virtual environment:
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/pip install -r uploader/publisher/requirements.txt
   ```

3. (Optional) Install VS Code extension:
   ```bash
   cd .vscode-extension
   npm install
   npm run compile
   ```

### Basic Usage

1. **Prepare your source file** in `uploader/input_data/{collection_slug}/publication.html`

2. **Initialize metadata**:
   ```bash
   python -m uploader.publisher.cli init-metadata \
     --input uploader/input_data/{collection_slug}/publication.html \
     --has-collection
   ```

3. **Edit** `uploader/input_data/{collection_slug}/@metadata.yml` with your publication details

4. **Generate events**:
   ```bash
   python -m uploader.publisher.cli generate \
     --input uploader/input_data/{collection_slug}/publication.html \
     --source-type HTML \
     --promote-default-structure
   ```

5. **Publish to relay**:
   ```bash
   export SCRIPTORIUM_KEY='your_nsec_or_hex_key'
   python -m uploader.publisher.cli publish
   ```

## Documentation

### Main Documentation

- **[Publisher README](uploader/publisher/README.md)**: Comprehensive guide to the Nostr bookstr publisher
  - Step-by-step workflow
  - Metadata configuration
  - NKBIP-01 and NKBIP-08 tag specifications
  - Command reference
  - Script documentation

### VS Code Extension

The VS Code extension provides a GUI interface for all publisher functions. See `.vscode-extension/README.md` for extension-specific documentation.

**Features:**
- Initialize metadata with wizard
- Generate events with progress tracking
- Publish to relays
- Quality control checks
- Read/view publications from relays
- Input file management
- All-in-one workflow

**Installation:**
- Install from VSIX: `code --install-extension .vscode-extension/scriptorium-publisher-0.1.0.vsix`
- Or build from source: `cd .vscode-extension && npm install && npm run compile`

## Project Structure

```
Scriptorium/
├── uploader/
│   ├── publisher/          # Nostr bookstr publisher
│   │   ├── README.md       # Main publisher documentation
│   │   ├── cli.py          # Command-line interface
│   │   ├── scripts/        # Utility scripts
│   │   │   ├── broadcast_publication.py
│   │   │   ├── delete_publication.py
│   │   │   └── read_publication.py
│   │   └── ...
│   └── input_data/         # Input source files
├── .vscode-extension/       # VS Code extension
│   ├── README.md           # Extension documentation
│   └── ...
├── app/                     # Core application logic
├── docs/                    # Additional documentation
└── README.md               # This file
```

## Commands

### CLI Commands

- `init-metadata`: Generate `@metadata.yml` from source file
- `generate`: Convert source to AsciiDoc and generate Nostr events
- `publish`: Publish events to configured relay
- `qc`: Quality control - verify events on relay
- `all`: Run generate → publish → qc in sequence

See `uploader/publisher/README.md` for detailed command documentation.

### Utility Scripts

- `read_publication`: Read and display a publication from a relay
- `broadcast_publication`: Broadcast an entire publication to another relay
- `delete_publication`: Delete an entire publication from a relay

All scripts support multiple event reference formats:
- `nevent` (bech32 encoded event reference)
- `naddr` (bech32 encoded address: kind:pubkey:d-tag)
- `hex event ID` (64 hex characters)

## Environment Variables

- `SCRIPTORIUM_KEY`: Nostr secret key (nsec bech32 or 64-hex, auto-normalized)
- `SCRIPTORIUM_RELAY`: Relay URL (default: `wss://thecitadel.nostr1.com`)
- `SCRIPTORIUM_SOURCE`: Default source type (default: `HTML`)
- `SCRIPTORIUM_OUT`: Output directory (default: `uploader/publisher/out`)

## Standards Compliance

Scriptorium publishes events compliant with:

- **NKBIP-01**: Nostr bookstr publication standard for metadata and structure
- **NKBIP-08**: Book wikilink standard for searchable book references
- **NIP-54**: Tag normalization rules (lowercase, hyphenated)

## Features in Detail

### Document Conversion

Scriptorium uses Pandoc to convert documents. Supported formats:
- PDF, TXT, HTML, LaTeX, Markdown, RTF, DOCX, ODT, EPUB

All formats are normalized to AsciiDoc for consistent processing.

### Publication Structure

Publications are organized hierarchically:
- **Collection** (kind 30040): Top-level index
- **Book/Title** (kind 30040): Individual books within a collection
- **Chapter** (kind 30040): Chapters within a book
- **Section/Verse** (kind 30041): Content events

### Tag System

**NKBIP-01 Tags:**
- `title`, `author`, `published_on`, `published_by`, `summary`, `type`
- `auto-update`, `source`, `image`
- `p` and `E` (for derivative works)
- Custom tags via `additional_tags`

**NKBIP-08 Tags** (when `use_bookstr: true`):
- `C`: Collection identifier
- `T`: Title/book identifier
- `c`: Chapter identifier
- `s`: Section/verse identifier
- `v`: Version identifier (e.g., "KJV", "DRB")

### Quality Control

The QC system:
- Queries the relay for all published events
- Compares with generated events
- Reports missing events
- Optionally republishes missing events

### Error Handling

- Graceful KeyboardInterrupt handling (Ctrl+C)
- Progress bars for long-running operations
- Automatic fallback to default relay if event not found
- Comprehensive error messages

## License

MIT License - see LICENSE files in respective directories.

## Links

- **Publisher Documentation**: [uploader/publisher/README.md](uploader/publisher/README.md)
- **VS Code Extension**: [.vscode-extension/README.md](.vscode-extension/README.md)
- **Pandoc**: https://pandoc.org/
- **Nostr**: https://nostr.com/
- **NKBIP-01**: Nostr bookstr publication standard
- **NKBIP-08**: Book wikilink standard

## Support

For issues and questions:
- Check the [Publisher README](uploader/publisher/README.md) for detailed documentation
- Contact the developer: [Silberengel](https://jumble.imwald.eu/users/npub1l5sga6xg72phsz5422ykujprejwud075ggrr3z2hwyrfgr7eylqstegx9z)

