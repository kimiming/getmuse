"""Random identity values for new accounts."""

from __future__ import annotations

import datetime as dt
import random

FIRST_NAMES = (
    "Alex",
    "Avery",
    "Blake",
    "Cameron",
    "Casey",
    "Chris",
    "Daniel",
    "Drew",
    "Ethan",
    "Evan",
    "Jamie",
    "Jordan",
    "Kai",
    "Kevin",
    "Leo",
    "Logan",
    "Marcus",
    "Mason",
    "Nathan",
    "Noah",
    "Owen",
    "Parker",
    "Quinn",
    "Ryan",
    "Sam",
    "Taylor",
    "Tristan",
    "Victor",
    "Wyatt",
    "Zoe",
)

LAST_NAMES = (
    "Adams",
    "Baker",
    "Bennett",
    "Brooks",
    "Carter",
    "Clark",
    "Collins",
    "Cooper",
    "Davis",
    "Edwards",
    "Ellis",
    "Evans",
    "Foster",
    "Garcia",
    "Gray",
    "Green",
    "Hall",
    "Harris",
    "Hayes",
    "Hughes",
    "Jackson",
    "James",
    "Johnson",
    "Kelly",
    "Lewis",
    "Martin",
    "Miller",
    "Mitchell",
    "Moore",
    "Nelson",
    "Parker",
    "Reed",
    "Roberts",
    "Ross",
    "Russell",
    "Scott",
    "Stewart",
    "Taylor",
    "Turner",
    "Walker",
    "Ward",
    "Watson",
    "White",
    "Wilson",
    "Wright",
    "Young",
)


def birthday(min_age: int = 22, max_age: int = 38, *, today: dt.date | None = None) -> dt.date:
    """Return a date that is comfortably older than 18."""
    today = today or dt.date.today()
    age = random.randint(min_age, max_age)
    year = today.year - age
    month = random.randint(1, 12)
    max_day = 28
    if month in {1, 3, 5, 7, 8, 10, 12}:
        max_day = 31
    elif month in {4, 6, 9, 11}:
        max_day = 30
    elif year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        max_day = 29
    return dt.date(year, month, random.randint(1, max_day))


def display_name() -> str:
    return random.choice(FIRST_NAMES)


def random_name_pairs(count: int = 20) -> list[tuple[str, str]]:
    """Return ``count`` random first/last pairs."""
    first, last = random_names(count)
    return list(zip(first, last))


def random_names(count: int = 20) -> tuple[list[str], list[str]]:
    count = max(1, int(count))
    first = random.sample(FIRST_NAMES, min(count, len(FIRST_NAMES)))
    last = random.sample(LAST_NAMES, min(count, len(LAST_NAMES)))
    while len(first) < count:
        first.append(random.choice(FIRST_NAMES))
    while len(last) < count:
        last.append(random.choice(LAST_NAMES))
    return first, last


def names_text(count: int = 20) -> tuple[str, str]:
    """Comma-separated pools for GUI script parameters."""
    first, last = random_names(count)
    return ", ".join(first), ", ".join(last)
