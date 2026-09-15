from types import SimpleNamespace

from ui.app_base import AppController


def test_escape_is_routed_only_to_the_visible_view() -> None:
    calls = []
    controller = object.__new__(AppController)
    controller.current_view = 1
    controller.views = {
        0: SimpleNamespace(handle_escape=lambda: calls.append("hidden")),
        1: SimpleNamespace(handle_escape=lambda: calls.append("visible")),
    }

    controller._on_keyboard_event(SimpleNamespace(key="Enter"))
    controller._on_keyboard_event(SimpleNamespace(key="Escape"))

    assert calls == ["visible"]
