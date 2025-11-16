#!/usr/bin/env python3
import sys
import re
from pathlib import Path

# Non-greedy, dotall, case-insensitive <h1 ...>...</h1>
H1_BLOCK = re.compile(r'(?is)<h1\b[^>]*?>.*?</h1>')


def main(path_str: str) -> None:
    p = Path(path_str)
    src = p.read_text(encoding='utf-8', errors='ignore')

    matches = list(H1_BLOCK.finditer(src))
    if len(matches) <= 1:
        print("Zero or one <h1> blocks; nothing to remove.")
        return

    out_parts = []
    last = 0
    kept_first = False
    for m in matches:
        if not kept_first:
            kept_first = True
            continue  # keep the first <h1>...</h1> intact
        out_parts.append(src[last:m.start()])
        last = m.end()
    out_parts.append(src[last:])

    backup = p.with_suffix(p.suffix + '.bak')
    backup.write_text(src, encoding='utf-8')
    p.write_text(''.join(out_parts), encoding='utf-8')
    print(f"Removed {len(matches)-1} <h1> blocks.\nUpdated: {p}\nBackup:  {backup}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: remove_h1_blocks_after_first.py /absolute/path/to/publication.html")
        sys.exit(1)
    main(sys.argv[1])


