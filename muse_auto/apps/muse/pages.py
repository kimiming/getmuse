"""Muse page recognition.

Recognition is intentionally text-first. Resource IDs in Meta apps change
between builds, while the English labels are comparatively stable. Each page
rule is ordered from most specific to least specific; a page is the first rule
that matches.

This module never clicks anything. It is pure and unit-testable from a saved
dump.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from muse_auto.ui.parser import UiTree


class Page(str, Enum):
    UNKNOWN = "unknown"
    PERMISSION = "permission"
    SYSTEM_SHEET = "system_sheet"
    ERROR = "error"
    LOADING = "loading"
    ACCOUNT_CHOOSER = "account_chooser"
    OTP = "otp"
    BIRTHDAY = "birthday"
    ONBOARDING = "onboarding"
    AGE_GATE = "age_gate"
    EMAIL = "email"
    INVITE = "invite"
    SETTINGS = "settings"
    HOME = "home"
    WELCOME = "welcome"


@dataclass(frozen=True)
class PageMatch:
    page: Page
    reason: str = ""
    edit_count: int = 0

    @property
    def known(self) -> bool:
        return self.page is not Page.UNKNOWN


class MusePages:
    """Pure page detector for Muse."""

    PERMISSION_PACKAGES = (
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.lbe.security.miui",
    )
    SYSTEM_SHEET_PACKAGES = (
        "com.android.credentialmanager",
        "com.google.android.gms",
    )
    SYSTEM_SHEET_MARKERS = (
        "sign in with google",
        "use your account for",
        "close sheet",
    )
    ACCOUNT_CHOOSER_MARKERS = (
        "choose an account to continue",
        "we found a meta account",
        "create new account",
        "create a new account",
    )
    ERROR_MARKERS = (
        "no connection",
        "couldn't connect",
        "could not connect",
        "check your connection",
        "network error",
        "unable to connect",
        "something went wrong",
        "connection lost",
    )
    LOADING_MARKERS = (
        "loading",
        "getting ready",
        "please wait",
        "setting up",
        "just a moment",
    )

    # Text fragments that strongly identify each screen.
    OTP_MARKERS = (
        "verification code",
        "enter the code",
        "enter your code",
        "enter code",
        "6-digit code",
        "6 digit code",
        "check your email",
        "we sent a code",
        "we sent your code",
        "sent your code",
        "we've sent a code",
        "code sent",
        "code was sent",
        "resend code",
        "remember this device",
        "email verification",
        "confirm your email",
    )
    BIRTHDAY_MARKERS = (
        "birthday",
        "date of birth",
        "birth date",
        "what's your birthday",
        "whats your birthday",
        "year of birth",
    )
    ONBOARDING_MARKERS = (
        "a few things to know",
        "can take actions for you",
        "works around the clock",
        "stay in control",
    )
    AGE_MARKERS = (
        "verify your age",
        "confirm your age",
        "age verification",
        "add a card",
        "add payment",
        "payment method",
        "government id",
        "upload your id",
        "continue with instagram or facebook",
        "continue with instagram or facebook account",
    )
    EMAIL_MARKERS = (
        "email",
        "phone number",
        "mobile number",
        "sign up with email",
        "continue with email",
    )
    SETTINGS_MARKERS = (
        "accounts center",
        "settings & privacy",
        "settings and privacy",
        "help & support",
        "legal info",
        "terms of service",
        "invite code",
        "referral code",
        "redeem code",
        "log out",
        "sign out",
    )
    HOME_MARKERS = (
        "ask muse",
        "message muse",
        "new chat",
        "start a chat",
        "how can i help",
        "what can i help",
        "what's on your mind",
        "whats on your mind",
        "personal agent",
        "what's your name",
    )
    WELCOME_MARKERS = (
        "get started",
        "continue with email",
        "sign up",
        "create an account",
        "welcome to muse",
        "log in",
        "already have an account",
    )

    @classmethod
    def detect(cls, tree: UiTree, top_package: str = "") -> PageMatch:
        labels = [value.casefold() for value in tree.visible_texts(limit=300)]
        joined = " | ".join(labels)
        edits = [node for node in tree.nodes if node.editable and node.visible]
        edit_count = len(edits)

        def has(*needles: str) -> bool:
            return any(needle.casefold() in joined for needle in needles)

        if top_package in cls.PERMISSION_PACKAGES or (
            "don't allow" in joined
            and ("while using the app" in joined or "allow" in joined)
            and top_package
            and "muse" not in top_package
        ):
            return PageMatch(Page.PERMISSION, f"package={top_package}", edit_count)

        if top_package in cls.SYSTEM_SHEET_PACKAGES or (
            "close sheet" in joined and "google" in joined
        ):
            return PageMatch(Page.SYSTEM_SHEET, f"system sheet package={top_package}", edit_count)

        if has(*cls.ERROR_MARKERS):
            return PageMatch(Page.ERROR, "network/error copy", edit_count)

        if has(*cls.LOADING_MARKERS) and edit_count == 0:
            return PageMatch(Page.LOADING, "loading copy", edit_count)

        if has(*cls.ACCOUNT_CHOOSER_MARKERS) and "account" in joined:
            return PageMatch(Page.ACCOUNT_CHOOSER, "account chooser copy", edit_count)

        if has(*cls.OTP_MARKERS) and edit_count >= 1:
            return PageMatch(Page.OTP, "code label + input", edit_count)

        # This onboarding sheet has "messages"/"Settings" copy that must not be
        # mistaken for the age-gate payment form.
        if has(*cls.ONBOARDING_MARKERS):
            return PageMatch(Page.ONBOARDING, "a few things to know", edit_count)

        if has(*cls.BIRTHDAY_MARKERS):
            return PageMatch(Page.BIRTHDAY, "birthday label", edit_count)

        if has(*cls.AGE_MARKERS) and (
            has("age", "card", "verify", "identity", "payment")
        ):
            return PageMatch(Page.AGE_GATE, "age/payment label", edit_count)

        if edit_count >= 1 and has(*cls.EMAIL_MARKERS):
            return PageMatch(Page.EMAIL, "email label + input", edit_count)

        if has("invite code", "referral code", "redeem code", "promo code"):
            return PageMatch(Page.INVITE, "invite copy", edit_count)

        if has(*cls.SETTINGS_MARKERS):
            return PageMatch(Page.SETTINGS, "settings copy", edit_count)

        if has(*cls.HOME_MARKERS) or (edit_count >= 1 and has("message", "chat")):
            return PageMatch(Page.HOME, "composer/home copy", edit_count)

        if has(*cls.WELCOME_MARKERS):
            return PageMatch(Page.WELCOME, "welcome copy", edit_count)

        return PageMatch(Page.UNKNOWN, tree.summary(limit=120), edit_count)

    @classmethod
    def describe(cls, match: PageMatch) -> str:
        return f"{match.page.value}（{match.reason}）"
