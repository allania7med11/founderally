"""The verify step's name match, alone. No stack: `name_in_text` reads two strings."""

import pytest

from activities.names import name_in_text


@pytest.mark.parametrize(
    ("name", "text", "found"),
    [
        ("Chats Café", "Chats Café, La Marsa. Coffee and cake among our twelve cats.", True),
        ("Chats Café", "CHATS CAFE, La Marsa", True),  # case and accents ignored
        ("Le Chat Noir", "Le Chat Noir on avenue Habib Bourguiba", True),
        ("Paws & Beans", "Paws & Beans, Lac 2. Pet-friendly terrace.", True),  # a symbol inside the name
        ("Chat", "Chats Café, La Marsa", False),  # whole words only: "Chat" is a part of "Chats"
        ("Kitty Corner", "Le Chat Noir on avenue Habib Bourguiba", False),
        ("", "Chats Café, La Marsa. Open daily.", False),  # a blank name is never verified
    ],
)
def test_name_in_text(name, text, found) -> None:
    assert name_in_text(name, text) is found
