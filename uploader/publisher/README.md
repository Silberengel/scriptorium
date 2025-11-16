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
     - `--unwrap-level N`  Only unwrap inside sections at heading level N and deeper (default: 4)
     - `--promote-default-structure`  Promote 'X Chapter N' and 'N:N.' into headings, add 'Preamble'
     - `--chapter-pattern REGEX`  Custom regex for chapter detection
     - `--section-pattern REGEX`  Custom regex for section detection
     - `--chapter-level N` / `--section-level N`  Custom heading levels
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
     - Required fields: `title`, `author`, `publisher`
     - Optional NKBIP-01 metadata fields:
       - `published_on`: Publication date (e.g., "2003-05-13" or "1899")
       - `published_by`: Publication source (e.g., "public domain")
       - `summary`: Publication description
       - `version`: Publication version (e.g., "KJV", "DRM", "3rd edition")
       - `type`: Publication type (default: "book", can be "bible", "illustrated", "magazine", etc.)
     - `language`, `collection_id`, `has_collection`
     - `use_bookstr: true|false` (enables bookstr macro tags: `type`, `book`, `chapter`, `verse`, `version`)
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
     - Optional additional NKBIP-01 tags (e.g., for cover image, ISBN, topics):
       ```
       additional_tags:
         - ["image", "https://example.com/cover.jpg"]
         - ["i", "isbn:9780765382030"]
         - ["t", "fables"]
         - ["t", "classical"]
         - ["source", "https://booksonline.org/"]
       ```
       Note: Cover images must be hosted on a media server accessible to clients. Add the URL via the `image` tag in `additional_tags`.

5) Generate final artifacts (AsciiDoc → indexes + events)
   - Re-run generate to apply metadata/mappings:
     - `python -m uploader.publisher.cli generate --input uploader/input_data/{collection_slug}/publication.html --source-type HTML [--promote-default-structure] [--ascii-only] [--unwrap-lines] [--unwrap-level N]`
   - Events are generated with NKBIP-01 compliant tags:
     - Collection root (kind 30040): `title`, `author`, `publisher`, `published_on`, `published_by`, `summary`, `type`, plus any `additional_tags`
     - Book/Chapter indexes (kind 30040): `type`, `book`, `chapter` (if applicable), `version` (if `use_bookstr: true`)
     - Section content (kind 30041): `type`, `book`, `chapter`, `verse` (if applicable), `version` (if `use_bookstr: true`)
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
   - Reads back by `kind + d + author`, verifies presence/content; republishes missing (placeholder for now).

8) All-in-one (optional)
   - `python -m uploader.publisher.cli all --input uploader/input_data/{collection_slug}/publication.html --source-type HTML`
   - Runs generate → publish → qc in sequence.

Commands
--------
- init-metadata: infer and create @metadata.yml next to your source
- generate: convert source → AsciiDoc and generate NKBIP-01 compliant bookstr events
- publish: publish events to relay with verification
- qc: verify presence on relay and republish missing (placeholder)
- all: run generate → publish → qc

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


