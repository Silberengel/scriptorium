def normalize_adoc(adoc_text: str, *, language: str = "en") -> str:
    """
    Pass-through normalizer that ensures a minimal header exists.
    """
    text = adoc_text.lstrip()
    if not text.startswith(":doctype:"):
        header = f":doctype: article\n:lang: {language}\n\n"
        return header + text
    return adoc_text


