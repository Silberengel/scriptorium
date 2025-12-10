"""
Text normalization functions for cleaning and standardizing text content.
"""
import re
import unicodedata


def strip_invisible_text(text: str) -> str:
    """
    Remove a broad set of invisible/control characters and normalize spaces.
    - Removes all codepoints in Unicode category 'C*' except tab/newline
    - Converts NBSP and NNBSP to regular spaces
    - Removes ZWJ/ZWNJ and similar joiners
    - Collapses repeated spaces
    """
    if not text:
        return text
    # Map common space variants to regular space
    text = (
        text.replace("\u00A0", " ")  # NBSP
        .replace("\u202F", " ")      # NNBSP
        .replace("\u2007", " ")      # figure space
    )
    cleaned_chars = []
    for ch in text:
        if ch in ("\t", "\n", "\r"):
            cleaned_chars.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C"):  # Control/Other (Cc, Cf, Cs, Co, Cn)
            # drop control/invisible chars
            continue
        cleaned_chars.append(ch)
    cleaned = "".join(cleaned_chars)
    # Remove zero-width joiners explicitly (in case categorized differently)
    cleaned = cleaned.replace("\u200B", "").replace("\u200C", "").replace("\u200D", "").replace("\ufeff", "")
    # Collapse runs of spaces
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    # Trim trailing spaces on lines
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    return cleaned


def normalize_ambiguous_unicode(text: str) -> str:
    """
    Replace ambiguous unicode characters (that look like ASCII) with their ASCII equivalents.
    This includes full-width characters, Cyrillic lookalikes, and other confusables.
    """
    if not text:
        return text
    
    # Mapping of ambiguous unicode characters to ASCII equivalents
    ambiguous_map = {
        # Full-width ASCII (U+FF00-U+FF5E)
        '\uff01': '!', '\uff02': '"', '\uff03': '#', '\uff04': '$', '\uff05': '%',
        '\uff06': '&', '\uff07': "'", '\uff08': '(', '\uff09': ')', '\uff0a': '*',
        '\uff0b': '+', '\uff0c': ',', '\uff0d': '-', '\uff0e': '.', '\uff0f': '/',
        '\uff10': '0', '\uff11': '1', '\uff12': '2', '\uff13': '3', '\uff14': '4',
        '\uff15': '5', '\uff16': '6', '\uff17': '7', '\uff18': '8', '\uff19': '9',
        '\uff1a': ':', '\uff1b': ';', '\uff1c': '<', '\uff1d': '=', '\uff1e': '>',
        '\uff1f': '?', '\uff20': '@', '\uff21': 'A', '\uff22': 'B', '\uff23': 'C',
        '\uff24': 'D', '\uff25': 'E', '\uff26': 'F', '\uff27': 'G', '\uff28': 'H',
        '\uff29': 'I', '\uff2a': 'J', '\uff2b': 'K', '\uff2c': 'L', '\uff2d': 'M',
        '\uff2e': 'N', '\uff2f': 'O', '\uff30': 'P', '\uff31': 'Q', '\uff32': 'R',
        '\uff33': 'S', '\uff34': 'T', '\uff35': 'U', '\uff36': 'V', '\uff37': 'W',
        '\uff38': 'X', '\uff39': 'Y', '\uff3a': 'Z', '\uff3b': '[', '\uff3c': '\\',
        '\uff3d': ']', '\uff3e': '^', '\uff3f': '_', '\uff40': '`', '\uff41': 'a',
        '\uff42': 'b', '\uff43': 'c', '\uff44': 'd', '\uff45': 'e', '\uff46': 'f',
        '\uff47': 'g', '\uff48': 'h', '\uff49': 'i', '\uff4a': 'j', '\uff4b': 'k',
        '\uff4c': 'l', '\uff4d': 'm', '\uff4e': 'n', '\uff4f': 'o', '\uff50': 'p',
        '\uff51': 'q', '\uff52': 'r', '\uff53': 's', '\uff54': 't', '\uff55': 'u',
        '\uff56': 'v', '\uff57': 'w', '\uff58': 'x', '\uff59': 'y', '\uff5a': 'z',
        '\uff5b': '{', '\uff5c': '|', '\uff5d': '}', '\uff5e': '~',
        # Cyrillic lookalikes (common ones that look like Latin)
        '\u0430': 'a', '\u0432': 'B', '\u0435': 'e', '\u043e': 'o', '\u0440': 'p',
        '\u0441': 'c', '\u0443': 'y', '\u0445': 'x', '\u0410': 'A', '\u0412': 'B',
        '\u0415': 'E', '\u041e': 'O', '\u0420': 'P', '\u0421': 'C', '\u0423': 'Y',
        '\u0425': 'X', '\u043c': 'm', '\u043d': 'n', '\u0438': 'i', '\u0442': 't',
        '\u044a': 'b', '\u044c': 'b',
    }
    
    result = []
    for char in text:
        result.append(ambiguous_map.get(char, char))
    return ''.join(result)


def to_ascii_text(text: str) -> str:
    """
    Best-effort transliteration to ASCII.
    - Unicode NFKD decomposition
    - Drop non-ASCII codepoints
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normalize_headings(text: str) -> str:
    """
    Normalize heading format to ensure valid AsciiDoc syntax.
    - Ensures headings have proper format: one or more '=' followed by a space and text
    - Note: Ambiguous unicode characters should already be normalized by normalize_ambiguous_unicode
    """
    if not text:
        return text
    out = []
    # Match heading lines: optional whitespace, one or more =, optional space, heading text
    heading_re = re.compile(r"^(\s*)(=+)(\s*)(.*)$")
    
    for line in text.splitlines():
        m = heading_re.match(line)
        if m:
            indent = m.group(1)
            equals = m.group(2)
            space_after = m.group(3)
            heading_text = m.group(4)
            
            # Count equals to preserve heading level
            equals_count = len(equals)
            
            # Ensure at least one space after equals if there's heading text
            if heading_text.strip():
                if not space_after or space_after == '':
                    space_after = ' '
                # Reconstruct heading with proper spacing
                out.append(f"{indent}{'=' * equals_count}{space_after}{heading_text}")
            else:
                # Empty heading - keep as is (might be intentional)
                out.append(line)
        else:
            out.append(line)
    return "\n".join(out) + "\n"

