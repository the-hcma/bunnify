"""Cocoa-free helpers so the Ctrl-C quit path can be unit-tested off macOS."""

from __future__ import annotations

from collections.abc import Callable

WAKE_EVENT_SELECTOR = (
    "otherEventWithType_location_modifierFlags_timestamp_windowNumber"
    "_context_subtype_data1_data2_"
)


def post_application_wake_event(
    *,
    event_type: object,
    ns_app: object,
    other_event: Callable[..., object],
) -> None:
    """Post an application-defined event so ``NSApp.run()`` wakes after stop."""
    wake = other_event(
        event_type,
        (0.0, 0.0),
        0,
        0.0,
        0,
        None,
        0,
        0,
        0,
    )
    getattr(ns_app, "postEvent_atStart_")(wake, True)


def quit_ns_app(*, ns_app: object, post_wake: Callable[[], None]) -> None:
    """Stop the Cocoa run loop and post a wake event (SIGINT path)."""
    getattr(ns_app, "stop_")(None)
    post_wake()
