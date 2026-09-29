"""A chat session: the sidebar row, who owns it, and the turns to restore."""

from common.schemas.session import SidebarSession
from common.session.id_validation import (
    GUEST_USER_ID_PREFIX,
    safe_thread_id,
    safe_user_id,
)
from common.session.sidebar_sessions import (
    list_user_sessions,
    record_session_activity,
    remove_sidebar_session,
    transfer_sidebar_session,
)
from common.session.transcript import restore_turns_from_checkpoint

__all__ = [
    "GUEST_USER_ID_PREFIX",
    "SidebarSession",
    "remove_sidebar_session",
    "record_session_activity",
    "safe_thread_id",
    "safe_user_id",
    "list_user_sessions",
    "restore_turns_from_checkpoint",
    "transfer_sidebar_session",
]
