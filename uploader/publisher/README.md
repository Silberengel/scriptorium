Publisher (Nostr Bookstr)
=========================

Welcome
-------
Welcome to the Scriptorium uploader for Nostr bookstr publications. This guide walks you through preparing sources, generating metadata, producing events, publishing, and QC.

Setup (virtual environment)
---------------------------
- Create and use a project-local venv (recommended):
  - `python3 -m venv .venv`
  - `.venv/bin/python -m pip install --upgrade pip`
  - `.venv/bin/pip install -r uploader/publisher/requirements.txt`
- Activate (optional): `source .venv/bin/activate`
- Set env var for publishing (when needed):
  - `export SCRIPTORIUM_KEY='your_nsec_or_hex_key'`
- You can also run commands without activating by prefixing with `.venv/bin/python`.

Step-by-step workflow
---------------------
1) Prepare input folder
   - Create a folder: `uploader/input_data/{collection_slug}/`
   - Add your source file as `publication.html` (or `publication.adoc`)

2) Clean/normalize the source (HTML → normalized AsciiDoc)
   - HTML: invisible chars stripped, basic headings/paragraphs mapped
   - Command:
     - HTML: `python -m uploader.publisher.cli generate --input uploader/input_data/{collection_slug}/publication.html --source-type HTML --has-collection`
     - AsciiDoc: `python -m uploader.publisher.cli generate --input uploader/input_data/{collection_slug}/publication.adoc --source-type ADOC --has-collection`
   - Optional flags:
     - `--ascii-only`  Transliterate to plain ASCII and drop non-ASCII
     - `--unwrap-lines`  Merge hard-wrapped lines within paragraphs
     - `--unwrap-level N`  Only unwrap inside verses at heading level N and deeper (default: 4)
     - `--promote-default-structure`  Promote 'X Chapter N' and 'N:N.' into headings, add 'Preamble'
     - `--chapter-pattern REGEX`  Custom regex for chapter detection
     - `--verse-pattern REGEX`  Custom regex for verse detection
     - `--chapter-level N` / `--verse-level N`  Custom heading levels
     - `--no-preamble`  Do not insert preamble under detected chapters
   - Note:
     - For DRM-Bible sources, avoid `--unwrap-lines`. Paragraphs are already normalized during HTML→AsciiDoc conversion, and unwrapping can interfere with verse promotion (N:N) by moving markers off line starts.
   - Outputs:
     - `uploader/publisher/out/adoc/normalized-publication.adoc` (for review)
   - Note: This step also produces temporary events; final events will be regenerated after metadata is confirmed.

3) Create a metadata draft
   - Generate `@metadata.yml` next to the source:
     - `python -m uploader.publisher.cli init-metadata --input uploader/input_data/{collection_slug}/publication.html --has-collection`
   - This writes: `uploader/input_data/{collection_slug}/@metadata.yml`

4) Edit metadata and mappings
   - Open `@metadata.yml` and review:
     - Required fields: `title`, `author`
     - Optional NKBIP-01 metadata fields:
       - `published_on`: Publication date (e.g., "2003-05-13" or "1899")
       - `published_by`: Publication source (e.g., "public domain")
       - `summary`: Publication description
       - `type`: Publication type (default: "book", can be "bible", "illustrated", "magazine", "documentation", "academic", "blog", etc.)
       - `auto_update`: Auto-update behavior ("yes", "ask", or "no", default: "ask")
       - `source`: Source URL for the publication
       - `image`: Image URL for the publication cover
       - `derivative_author`: Pubkey of original author (for derivative works)
       - `derivative_event`: Event ID of original event (for derivative works)
       - `derivative_relay`: Relay URL for original event (optional, for derivative works)
       - `derivative_pubkey`: Pubkey for original event (optional, defaults to derivative_author if not specified)
     - `language`, `collection_id`, `has_collection`
     
   - **NKBIP-08 Book Wikilinks Configuration** (`use_bookstr: true`):
     - `use_bookstr: true|false` (enables NKBIP-08 tags for book wikilink searchability)
     - `version`: Translation/version identifier (e.g., "DRB" for Douay-Rheims Bible, "KJV" for King James Version)
       - For Bibles, use standard abbreviations: KJV, NKJV, NIV, ESV, NASB, NLT, MSG, CEV, NRSV, RSV, ASV, YLT, WEB, GNV, DRB, etc.
       - The version tag is normalized and added to all events (kind 30040 and 30041) when `use_bookstr: true`
     - NKBIP-08 tags added to events (hierarchical - each level includes parent tags):
       - `C`: Collection identifier (normalized, lowercase, hyphenated)
       - `T`: Title/book identifier (normalized, lowercase, hyphenated)
       - `c`: Chapter identifier (normalized, lowercase, hyphenated)
       - `s`: Section/verse identifier (normalized, lowercase, hyphenated) - only on content events (30041)
       - `v`: Version identifier (normalized, lowercase, hyphenated) - added to all events if specified
     - Tag hierarchy:
       - Collection root (30040): `C`, `T`, `v` (if version specified)
       - Book/Title events (30040): `C`, `T`, `v` (if version specified)
       - Chapter events (30040): `C`, `T`, `c`, `v` (if version specified)
       - Section/Verse events (30041): `C`, `T`, `c`, `s`, `v` (if version specified)
     - The `type` tag is a formatting hint for clients (default: "book", can be "bible", "magazine", etc.) and is separate from NKBIP-08 tags
     - These tags enable the wikistr bookstr macro to search and reference specific verses, chapters, and books using wikilinks like `[[book::bible | genesis 2:4 | kjv]]`
     
   - Optional mappings (choose either or both):
     - Inline list:
       ```
       wikistr_mappings:
         - display: Josue
           canonical: Joshua
         - display: 1 Kings
           canonical: 1 Samuel
       ```
     - External file (YAML list with the same shape):
       ```
       book_title_mapping_file: book_title_map.yml
       ```
       If using `book_title_mapping_file`, create that YAML with a list of `{display, canonical}` pairs.
       The canonical names should match what wikistr expects (e.g., "Song of Solomon" not "Song of Songs").
     
   - Optional additional NKBIP-01 tags (e.g., for ISBN, topics):
     ```
     additional_tags:
       - ["i", "isbn:9780765382030"]
       - ["t", "fables"]
       - ["t", "classical"]
     ```
     Note: For cover images and source URLs, use the `image` and `source` fields directly in metadata rather than `additional_tags`.

5) Generate final artifacts (AsciiDoc → indexes + events)
   - Re-run generate to apply metadata/mappings:
     - `python -m uploader.publisher.cli generate --input uploader/input_data/{collection_slug}/publication.html --source-type HTML --promote-default-structure [--ascii-only]`
     - Events are generated with NKBIP-01 and NKBIP-08 compliant tags:
     - **Collection root (kind 30040)**: 
       - NKBIP-01: `title`, `author`, `published_on`, `published_by`, `summary`, `type`, `auto-update`, `source`, `image` (if specified), `p` and `E` (for derivative works), plus any `additional_tags`
       - NKBIP-08: `C` (collection), `T` (title), `v` (version if specified)
     - **Book/Title events (kind 30040)**:
       - NKBIP-01: `type`, `auto-update`
       - NKBIP-08: `C` (collection), `T` (title/book), `v` (version if specified)
       - Note: T-level events only contain c-level (chapter) events. Any 30041 sections directly under a T-level event are placed under a "Preamble" 30040 chapter event.
     - **Chapter events (kind 30040)**:
       - NKBIP-01: `type`, `auto-update`
       - NKBIP-08: `C` (collection), `T` (title/book, inherited), `c` (chapter), `v` (version if specified)
     - **Section/Verse content (kind 30041)**:
       - NKBIP-01: `type`
       - NKBIP-08: `C` (collection), `T` (title/book), `c` (chapter), `s` (section/verse), `v` (version if specified)
     - All index events (kind 30040) include `a` tags referencing their child events in format `["a", "<kind:pubkey:dtag>", "<relay hint>", "<event id>"]` (added during publishing)
     - NKBIP-08 tags enable book wikilink resolution (e.g., `[[book::bible | genesis 2:4 | kjv]]`)
     - All tag values are normalized using NIP-54 rules (lowercase, non-alphanumeric to hyphens, quotes removed, multiple hyphens collapsed)
   - Outputs:
     - `uploader/publisher/out/events/events.ndjson` (serialized events ready for publishing)
     - `uploader/publisher/out/cache/event_index.json` (quick index)
     - `uploader/publisher/out/adoc/normalized-publication.adoc`

6) Publish to relay
   - Set env: `SCRIPTORIUM_KEY` (nsec... or 64-hex; normalized automatically)
   - Optional env: `SCRIPTORIUM_RELAY` (default `wss://thecitadel.nostr1.com`)
   - Command:
     - `python -m uploader.publisher.cli publish`
   - The publisher verifies that the first event is present on the relay after publishing.
     Only reports success if verification passes.

7) QC and republish missing
   - Command:
     - `python -m uploader.publisher.cli qc`
   - Queries the relay for all events and compares with generated events
   - Reports which events are missing
   - To republish missing events:
     - `python -m uploader.publisher.cli qc --republish`

8) All-in-one (optional)
   - `python -m uploader.publisher.cli all --input uploader/input_data/{collection_slug}/publication.html --source-type HTML`
   - Runs generate → publish → qc in sequence.

9) Broadcast publication to another relay
   - `python -m uploader.publisher.scripts.broadcast_publication <nevent> <relay_url> [--key SCRIPTORIUM_KEY]`
   - Takes the nevent of the top-level 30040 event
   - Recursively fetches all child events via a-tags
   - Publishes all events to the specified relay (ws:// or wss://)
   - Example: `python -m uploader.publisher.scripts.broadcast_publication nevent1qqs... wss://relay.example.com`

10) Delete publication from a relay
   - `python -m uploader.publisher.scripts.delete_publication <nevent> <relay_url> [--key SCRIPTORIUM_KEY]`
   - Takes the nevent of the top-level 30040 event
   - Recursively fetches all child events via a-tags
   - Creates deletion events (kind 5) for all events
   - Requires confirmation by typing "DELETE"
   - Example: `python -m uploader.publisher.scripts.delete_publication nevent1qqs... wss://relay.example.com`

Commands
--------
- init-metadata: infer and create @metadata.yml next to your source
- generate: convert source → AsciiDoc and generate NKBIP-01 and NKBIP-08 compliant events
- publish: publish events to relay with verification (adds `a` tags to index events)
- qc: verify presence on relay and republish missing events (use `--republish` to auto-republish)
- all: run generate → publish → qc in sequence

Scripts
-------
- broadcast_publication: broadcast an entire publication to a relay (takes nevent)
- delete_publication: delete an entire publication from a relay (takes nevent)

Environment
-----------
- SCRIPTORIUM_KEY: nsec... (bech32) or hex (64 chars). Will be normalized to lowercase hex.
- SCRIPTORIUM_RELAY: default wss://thecitadel.nostr1.com
- SCRIPTORIUM_SOURCE: default HTML
- SCRIPTORIUM_OUT: default uploader/publisher/out

Example
-------
- Prepare input folder: uploader/input_data/DRM-Bible/
- Put publication.html (or publication.adoc)
- Generate metadata draft:
  python -m uploader.publisher.cli init-metadata --input uploader/input_data/DRM-Bible/publication.html --has-collection
- Generate artifacts:
  python -m uploader.publisher.cli generate --input uploader/input_data/DRM-Bible/publication.html --source-type HTML


