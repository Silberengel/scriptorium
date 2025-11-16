Publisher (Nostr Bookstr)
=========================

Commands
--------
- init-metadata: infer and create @metadata.yml next to your source
- generate: convert source → AsciiDoc and prepare artifacts
- publish: publish events to relay (to be implemented next)
- qc: verify presence on relay and republish missing (to be implemented next)
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
- Put publication.html (or publication.adoc), optional cover-image.jpg
- Generate metadata draft:
  python -m uploader.publisher.cli init-metadata --input uploader/input_data/DRM-Bible/publication.html --has-collection
- Generate artifacts:
  python -m uploader.publisher.cli generate --input uploader/input_data/DRM-Bible/publication.html --source-type HTML


