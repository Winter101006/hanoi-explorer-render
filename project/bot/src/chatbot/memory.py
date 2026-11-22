"""Bounded process-local memory. Per-session turns are serialized."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from threading import RLock
from time import monotonic

from .schemas import ConversationState


class ConversationMemory:
    def __init__(self, ttl_seconds=3600, max_sessions=1000, history_turns=12,
                 max_content_chars=2000, clock=monotonic):
        if min(ttl_seconds, max_sessions, history_turns, max_content_chars) <= 0:
            raise ValueError('Memory limits must be positive')
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.history_turns = history_turns
        self.max_content_chars = max_content_chars
        self._clock = clock
        self._entries = OrderedDict()
        self._lock = RLock()
        self._turn_locks = [RLock() for _ in range(64)]

    @contextmanager
    def turn(self, session_id):
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
            raise ValueError('Invalid session ID')
        with self._turn_locks[hash(session_id) % len(self._turn_locks)]:
            yield

    def bounded(self, state):
        history = tuple(replace(turn, content=turn.content[:self.max_content_chars])
                        for turn in state.history[-self.history_turns:])
        return deepcopy(replace(state, history=history))

    def _expire(self):
        now = self._clock()
        for key, (expires, _) in list(self._entries.items()):
            if expires <= now:
                del self._entries[key]

    def get(self, session_id) -> ConversationState:
        with self.turn(session_id), self._lock:
            self._expire()
            entry = self._entries.get(session_id)
            return deepcopy(entry[1]) if entry else ConversationState()

    def save(self, session_id, state: ConversationState) -> None:
        with self.turn(session_id), self._lock:
            self._expire()
            self._entries[session_id] = (self._clock() + self.ttl_seconds, self.bounded(state))
            self._entries.move_to_end(session_id)
            while len(self._entries) > self.max_sessions:
                self._entries.popitem(last=False)

    def clear(self, session_id) -> None:
        with self.turn(session_id), self._lock:
            self._entries.pop(session_id, None)
