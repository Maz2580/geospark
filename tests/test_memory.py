"""Tests for the GeoSpark memory module."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from geospark.memory.session_store import Session, SessionStore
from geospark.memory.spatial_memory import SpatialMemory, SpatialMemoryEntry


class TestSession:
    """Tests for Session model."""

    def test_create_session(self) -> None:
        session = Session()
        assert session.id
        assert session.title == ""
        assert session.messages == []

    def test_add_message(self) -> None:
        session = Session()
        msg = session.add_message("user", "What is near the Eiffel Tower?")
        assert msg.role == "user"
        assert msg.content == "What is near the Eiffel Tower?"
        assert session.message_count == 1

    def test_auto_title(self) -> None:
        session = Session()
        session.add_message("user", "Find hospitals near Valencia flood zone")
        assert session.title == "Find hospitals near Valencia flood zone"

    def test_add_tool_result(self) -> None:
        session = Session()
        session.add_tool_result("geocode", {"lat": 48.86, "lon": 2.35})
        assert len(session.tool_history) == 1
        assert session.tool_history[0]["tool"] == "geocode"

    def test_to_context_messages(self) -> None:
        session = Session()
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")
        ctx = session.to_context_messages()
        assert len(ctx) == 2
        assert ctx[0] == {"role": "user", "content": "Hello"}
        assert ctx[1] == {"role": "assistant", "content": "Hi there!"}


class TestSessionStore:
    """Tests for SessionStore persistence."""

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(storage_dir=tmp)
            session = Session()
            session.add_message("user", "Test message")
            store.save(session)

            loaded = store.load(session.id)
            assert loaded is not None
            assert loaded.id == session.id
            assert loaded.message_count == 1

    def test_list_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(storage_dir=tmp)
            for i in range(3):
                s = Session()
                s.add_message("user", f"Session {i}")
                store.save(s)

            sessions = store.list_sessions()
            assert len(sessions) == 3

    def test_get_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(storage_dir=tmp)
            s1 = Session()
            s1.add_message("user", "First session")
            store.save(s1)

            s2 = Session()
            s2.add_message("user", "Second session")
            store.save(s2)

            latest = store.get_latest()
            assert latest is not None

    def test_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(storage_dir=tmp)
            session = Session()
            store.save(session)
            assert store.delete(session.id) is True
            assert store.load(session.id) is None

    def test_load_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(storage_dir=tmp)
            assert store.load("nonexistent") is None


class TestSpatialMemoryEntry:
    """Tests for SpatialMemoryEntry model."""

    def test_create_entry(self) -> None:
        entry = SpatialMemoryEntry(content="User prefers EPSG:32631")
        assert entry.id
        assert entry.scope == "project"
        assert entry.memory_type == "spatial_knowledge"

    def test_matches_query_exact(self) -> None:
        entry = SpatialMemoryEntry(content="User prefers EPSG:32631 for French locations")
        score = entry.matches_query("EPSG:32631")
        assert score > 0.8

    def test_matches_query_word_overlap(self) -> None:
        entry = SpatialMemoryEntry(content="Farm boundary is in the Valencia region")
        score = entry.matches_query("Valencia farm")
        assert 0.0 < score <= 0.8

    def test_matches_query_no_match(self) -> None:
        entry = SpatialMemoryEntry(content="User prefers EPSG:32631")
        score = entry.matches_query("Tokyo temperature")
        assert score == 0.0


class TestSpatialMemory:
    """Tests for SpatialMemory store."""

    def test_remember_and_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = SpatialMemory(storage_dir=tmp)
            memory.remember("User usually works with EPSG:32631 for Paris area")
            results = memory.recall("EPSG:32631")
            assert len(results) >= 1
            assert "EPSG:32631" in results[0].content

    def test_remember_with_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = SpatialMemory(storage_dir=tmp)
            entry = memory.remember(
                "User's farm boundary",
                geometry={"type": "Point", "coordinates": [2.35, 48.86]},
                tags=["farm", "aoi"],
            )
            assert entry.geometry is not None
            assert entry.tags == ["farm", "aoi"]

    def test_forget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = SpatialMemory(storage_dir=tmp)
            entry = memory.remember("Temporary data")
            assert memory.count == 1
            assert memory.forget(entry.id) is True
            assert memory.count == 0

    def test_clear_by_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = SpatialMemory(storage_dir=tmp)
            memory.remember("Session data", scope="session")
            memory.remember("Project data", scope="project")
            removed = memory.clear(scope="session")
            assert removed == 1
            assert memory.count == 1

    def test_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory1 = SpatialMemory(storage_dir=tmp)
            memory1.remember("Persistent knowledge")

            # Reload from disk
            memory2 = SpatialMemory(storage_dir=tmp)
            assert memory2.count == 1
            assert memory2.recall("Persistent")[0].content == "Persistent knowledge"

    def test_list_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = SpatialMemory(storage_dir=tmp)
            memory.remember("Entry 1", scope="project")
            memory.remember("Entry 2", scope="global")
            memory.remember("Entry 3", scope="project")

            all_entries = memory.list_all()
            assert len(all_entries) == 3

            project_only = memory.list_all(scope="project")
            assert len(project_only) == 2
