"""Stable target identity shared by execution and approval presentation."""


def housekeeping_target(message_id: str, label_id: str | None) -> str:
    """Identify exactly the message and optional label being changed."""
    return message_id if label_id is None else f"{message_id}:{label_id}"
