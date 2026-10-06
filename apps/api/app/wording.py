"""Words as people say them, for text that was stored in a coded form."""

import re


def plain_title(title: str) -> str:
    """A work order title as an owner would read it: "Tyre (steer_left)" becomes "Tyre (steer left)"; older requests stored the raw position."""
    return re.sub(r"\(([a-z]+(?:_[a-z]+)+)\)", lambda m: f"({m.group(1).replace('_', ' ')})", title)
