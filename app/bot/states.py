"""Finite-state machine states for the /add dialog."""

from __future__ import annotations

from vkbottle import BaseStateGroup


class AddSubscriptionStates(BaseStateGroup):
    """/add dialog steps."""

    WAITING_LINK = "waiting_link"
    WAITING_SERVER = "waiting_server"
    WAITING_MODE = "waiting_mode"
    WAITING_THRESHOLD = "waiting_threshold"
    WAITING_CONFIRM = "waiting_confirm"
