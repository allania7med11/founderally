"""Name matching for the verify step: is a competitor's name in the text of its page."""

import re
import unicodedata


def plain(text: str) -> str:
    """Lower case, accents removed: "Café" and "CAFE" both become "cafe"."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.casefold()


def name_in_text(name: str, text: str) -> bool:
    """Whole words only, case and accents ignored: "Chats Café" is in "CHATS CAFE, La Marsa"; "Chat" is not in
    "Chats". A blank name is never on a page: an empty pattern would match anywhere."""
    if not name.strip():
        return False
    plain_name = re.escape(plain(name))
    whole_name = r"(?<!\w)" + plain_name + r"(?!\w)"
    plain_text = plain(text)
    return re.search(whole_name, plain_text) is not None
