"""Named selectors for Muse.

Keep every literal string used to find a control in this file. When Meta ships
a new build, this is the only file that usually needs editing. Run
``python -m muse_auto inspect --instance <name> --tree`` to see the real labels.
"""

from __future__ import annotations

from muse_auto.ui.selector import Selector

# -- generic -----------------------------------------------------------------

ANY_EDIT = Selector(editable=True)

CONTINUE = Selector(
    label_contains=("continue", "next", "done", "agree and continue"),
)

CONTINUE_EXACT = Selector(
    label_contains=("continue", "next", "done"),
)

CLOSE_OR_SKIP = Selector(
    label_contains=(
        "not now",
        "no thanks",
        "maybe later",
        "later",
        "skip",
        "cancel",
        "close",
        "dismiss",
    )
)

CLOSE_ICON = Selector(
    desc_contains=("close", "dismiss", "cancel"),
)

PERMISSION_DENY = Selector(
    label_contains=(
        "don't allow",
        "dont allow",
        "deny",
        "not now",
        "no thanks",
        "don't allow notifications",
    )
)

# -- sign-up -----------------------------------------------------------------

EMAIL_ENTRY = Selector(
    label_contains=(
        "continue with email",
        "sign up with email",
        "use email",
        "sign up with phone or email",
        "email or phone",
    )
)

EMAIL_FIELD = Selector(editable=True)

CODE_FIELD = Selector(editable=True)

BIRTHDAY_FIELD = Selector(
    editable=True,
    label_contains=("birthday", "date of birth", "mm", "dd", "yyyy", "year"),
)

SOCIAL_INSTAGRAM = Selector(
    label_contains=(
        "continue with instagram",
        "continue with your instagram",
        "use instagram",
        "use your instagram",
        "instagram or facebook account",
        "instagram or facebook profile",
        "instagram or facebook",
        "instagram account",
    ),
)

SOCIAL_FACEBOOK = Selector(
    label_contains=(
        "continue with facebook",
        "continue with your facebook",
        "use facebook",
        "use your facebook",
        "instagram or facebook account",
        "instagram or facebook profile",
        "instagram or facebook",
        "facebook account",
    ),
)

# -- post-sign-up ------------------------------------------------------------

SETTINGS_BUTTON = Selector(
    label_contains=("settings",),
)

SETTINGS_MENU = Selector(
    label_contains=("settings", "settings & privacy", "settings and privacy"),
)

INVITE_ENTRY = Selector(
    label_contains=(
        "invite code",
        "referral code",
        "redeem code",
        "promo code",
        "enter code",
        "invite",
    )
)

REDEEM_BUTTON = Selector(
    label_contains=("redeem", "apply", "submit", "claim"),
)

TOKEN_BALANCE = Selector(
    label_contains=("tokens", "token balance", "credits"),
)


def all_named() -> dict[str, Selector]:
    return {
        name: value
        for name, value in globals().items()
        if isinstance(value, Selector) and name.isupper()
    }
