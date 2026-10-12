"""The brief: the recap of the conversation the user confirmed at Start. Code reads it; no model writes it here.

The conversation will propose it later; until then the Start request carries it whole. The caps are defaults:
an idea under 20 characters is not an idea, over 2,000 is the thread itself; two to four angles each under 80
characters is what a person types into a search box.
"""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Angle = Annotated[str, StringConstraints(min_length=1, max_length=79)]


class Category(BaseModel):
    name: str
    # One line: what to search the documents for, never whether a rule applies.
    what_to_look_for: str


class Brief(BaseModel):
    idea: str = Field(min_length=20, max_length=2_000)
    place: str = Field(min_length=1, max_length=80)
    # Search phrases as a person would type them, the market not the idea; no place, code adds it.
    a_angles: list[Angle] = Field(min_length=2, max_length=4)
    # Empty until the compliance ticket; the shape is fixed now so the row never changes.
    b_categories: list[Category] = []
    c_notes: str = ""
