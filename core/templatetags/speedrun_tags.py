"""Template filters for presenting Speedrun.com data."""

import math

from django import template

register = template.Library()


@register.filter(name="run_time")
def run_time(value):
    """Format a duration in seconds for display.

    Durations of an hour or more use ``H:MM:SS`` (``1:35:14``). Shorter runs
    use ``M:SS.mmm`` (``16:32.120``). Invalid or missing values become an em
    dash so templates never crash.
    """
    if value is None or value == "":
        return "\u2014"
    try:
        total = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    if not math.isfinite(total) or total < 0:
        return "\u2014"

    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    seconds = total % 60

    if hours:
        return f"{hours}:{minutes:02d}:{int(seconds):02d}"
    return f"{minutes}:{seconds:06.3f}"
