"""Where a pass stopped, read from its saved row alone. No stack: `pass_state` reads the row it is given."""

import pytest

from activities.research import pass_state
from db.passes import PassRow


# Empty lists stand for saved columns: `pass_state` reads only which columns are still null, never what they hold.
@pytest.mark.parametrize(
    ("row", "state"),
    [
        (None, "absent"),
        (PassRow(pages=[], candidates=None, verdicts=None, rows_found=None, reason=None), "pages"),
        (PassRow(pages=[], candidates=[], verdicts=None, rows_found=None, reason=None), "candidates"),
        (PassRow(pages=[], candidates=[], verdicts=[], rows_found=0, reason=None), "done"),
    ],
)
def test_pass_state(row, state) -> None:
    """The next step is read from which columns are still empty: no row, then pages, then candidates, then done."""
    assert pass_state(row) == state
