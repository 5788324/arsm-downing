"""Application version metadata shared by UI, packaging, and diagnostics."""

APP_NAME = "ARSM Suite"
APP_VERSION = "1.0.1"
APP_USER_AGENT = f"{APP_NAME}/{APP_VERSION}"


def display_title() -> str:
    return f"{APP_NAME} {APP_VERSION}"
