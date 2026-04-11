"""Tiered context storage — filesystem-like hierarchy with L0/L1/L2 loading."""
from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geospark.context.geo_context import ContextRelation, ContextTier, GeoContext

_URI_PATTERN = re.compile(r"^geospark://([^/]+)/(.+)$")


def parse_uri(uri: str) -> tuple[str, str]:
    """Parse a geospark:// URI into (category, path).

    Raises ValueError on malformed URI.
    """
    match = _URI_PATTERN.match(uri)
    if not match:
        raise ValueError(f"Invalid GeoSpark URI: {uri}. Expected geospark://<category>/<path>")
    return match.group(1), match.group(2)


def build_uri(category: str, name: str, subpath: str = "") -> str:
    """Build a geospark:// URI from parts."""
    if subpath:
        return f"geospark://{category}/{name}/{subpath}"
    return f"geospark://{category}/{name}"


class ContextStore:
    """Tiered filesystem-like storage for geospatial contexts.

    Layout on disk:

        <storage_dir>/
        ├── missions/
        │   ├── melbourne_flood_2024/
        │   │   ├── _ctx.json              (GeoContext metadata + L0 abstract)
        │   │   ├── _relations.json        (typed links to other contexts)
        │   │   └── analysis/
        │   │       └── 2026-04-09/
        │   │           └── _ctx.json
        │   └── _archive/
        │       └── old_mission_2023/
        ├── datasets/
        └── analysis_history/

    Each context lives in its own directory named by its URI path, with
    `_ctx.json` holding the full serialized GeoContext. Archived contexts
    are moved to `_archive/` subdirs (preserved but filtered from default
    queries).
    """

    CTX_FILE = "_ctx.json"
    RELATIONS_FILE = "_relations.json"
    ARCHIVE_DIR = "_archive"

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path.home() / ".geospark" / "contexts"
        self._root = Path(storage_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # -------------------------------------------------------------------
    # Path helpers
    # -------------------------------------------------------------------

    def _uri_to_dir(self, uri: str) -> Path:
        """Convert a URI to a filesystem path under the storage root."""
        category, path = parse_uri(uri)
        return self._root / category / path

    def _archive_dir_for(self, uri: str) -> Path:
        """Return the archive location for a given URI."""
        category, path = parse_uri(uri)
        return self._root / category / self.ARCHIVE_DIR / path

    # -------------------------------------------------------------------
    # Save / Load
    # -------------------------------------------------------------------

    def save(self, context: GeoContext) -> Path:
        """Save a context to disk. Creates parent directories as needed."""
        dir_path = self._uri_to_dir(context.uri)
        dir_path.mkdir(parents=True, exist_ok=True)
        context.updated_at = datetime.now(timezone.utc)
        ctx_path = dir_path / self.CTX_FILE
        ctx_path.write_text(
            context.model_dump_json(indent=2), encoding="utf-8"
        )
        return ctx_path

    def load(self, uri: str, touch: bool = True) -> GeoContext | None:
        """Load a context by URI. If touch=True, updates access count."""
        dir_path = self._uri_to_dir(uri)
        ctx_path = dir_path / self.CTX_FILE
        if not ctx_path.exists():
            # Also check archive
            archive_path = self._archive_dir_for(uri) / self.CTX_FILE
            if archive_path.exists():
                ctx_path = archive_path
            else:
                return None

        try:
            data = json.loads(ctx_path.read_text(encoding="utf-8"))
            ctx = GeoContext.model_validate(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

        if touch and not ctx.is_archived:
            ctx.touch()
            # Persist access count (best-effort)
            with contextlib.suppress(OSError):
                ctx_path.write_text(
                    ctx.model_dump_json(indent=2), encoding="utf-8"
                )
        return ctx

    def exists(self, uri: str) -> bool:
        """Check if a context exists (including archived)."""
        dir_path = self._uri_to_dir(uri)
        if (dir_path / self.CTX_FILE).exists():
            return True
        return (self._archive_dir_for(uri) / self.CTX_FILE).exists()

    def delete(self, uri: str) -> bool:
        """Permanently delete a context. Returns True if found and removed."""
        dir_path = self._uri_to_dir(uri)
        ctx_path = dir_path / self.CTX_FILE
        found = False
        if ctx_path.exists():
            ctx_path.unlink()
            found = True
        relations_path = dir_path / self.RELATIONS_FILE
        if relations_path.exists():
            relations_path.unlink()
        # Remove empty dir
        try:
            if dir_path.exists() and not any(dir_path.iterdir()):
                dir_path.rmdir()
        except OSError:
            pass
        return found

    # -------------------------------------------------------------------
    # Listing and discovery
    # -------------------------------------------------------------------

    def list_all(
        self,
        category: str | None = None,
        include_archived: bool = False,
    ) -> list[GeoContext]:
        """List all stored contexts, optionally filtered by category."""
        results: list[GeoContext] = []
        search_roots = (
            [self._root / category] if category else [p for p in self._root.iterdir() if p.is_dir()]
        )

        for search_root in search_roots:
            if not search_root.exists():
                continue
            for ctx_path in search_root.rglob(self.CTX_FILE):
                # Skip archived unless requested
                if not include_archived and self.ARCHIVE_DIR in ctx_path.parts:
                    continue
                try:
                    data = json.loads(ctx_path.read_text(encoding="utf-8"))
                    ctx = GeoContext.model_validate(data)
                    results.append(ctx)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue

        return results

    def list_categories(self) -> list[str]:
        """List top-level categories (missions, datasets, etc.)."""
        return sorted(
            p.name for p in self._root.iterdir()
            if p.is_dir() and p.name != self.ARCHIVE_DIR and not p.name.startswith(".")
        )

    def list_children(self, parent_uri: str) -> list[GeoContext]:
        """List direct children of a parent context."""
        parent_dir = self._uri_to_dir(parent_uri)
        if not parent_dir.exists():
            return []

        children: list[GeoContext] = []
        for item in parent_dir.iterdir():
            if not item.is_dir() or item.name == self.ARCHIVE_DIR:
                continue
            ctx_file = item / self.CTX_FILE
            if ctx_file.exists():
                try:
                    data = json.loads(ctx_file.read_text(encoding="utf-8"))
                    children.append(GeoContext.model_validate(data))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
            # Recurse into grandchildren that may contain _ctx.json
            else:
                for sub_ctx in item.rglob(self.CTX_FILE):
                    if self.ARCHIVE_DIR in sub_ctx.parts:
                        continue
                    # Only direct children: check depth
                    rel = sub_ctx.relative_to(parent_dir)
                    if len(rel.parts) <= 3:  # e.g., sub/sub/_ctx.json
                        try:
                            data = json.loads(sub_ctx.read_text(encoding="utf-8"))
                            children.append(GeoContext.model_validate(data))
                        except (json.JSONDecodeError, KeyError, ValueError):
                            continue
        return children

    # -------------------------------------------------------------------
    # Archive / unarchive
    # -------------------------------------------------------------------

    def archive(self, uri: str) -> bool:
        """Move a context to the archive. Returns True if archived."""
        ctx = self.load(uri, touch=False)
        if ctx is None or ctx.is_archived:
            return False

        # Mark as archived and save to archive location
        ctx.is_archived = True
        archive_dir = self._archive_dir_for(uri)
        archive_dir.mkdir(parents=True, exist_ok=True)
        (archive_dir / self.CTX_FILE).write_text(
            ctx.model_dump_json(indent=2), encoding="utf-8"
        )

        # Remove original
        original_dir = self._uri_to_dir(uri)
        original_path = original_dir / self.CTX_FILE
        if original_path.exists():
            original_path.unlink()
            try:
                if not any(original_dir.iterdir()):
                    original_dir.rmdir()
            except OSError:
                pass
        return True

    def unarchive(self, uri: str) -> bool:
        """Restore a context from the archive."""
        archive_path = self._archive_dir_for(uri) / self.CTX_FILE
        if not archive_path.exists():
            return False

        try:
            data = json.loads(archive_path.read_text(encoding="utf-8"))
            ctx = GeoContext.model_validate(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

        ctx.is_archived = False
        self.save(ctx)
        archive_path.unlink()
        # Clean up empty archive dir
        try:
            archive_dir = archive_path.parent
            if not any(archive_dir.iterdir()):
                archive_dir.rmdir()
        except OSError:
            pass
        return True

    # -------------------------------------------------------------------
    # Relations (typed links between contexts)
    # -------------------------------------------------------------------

    def add_relation(
        self,
        source_uri: str,
        target_uri: str,
        relation_type: str = "related",
        metadata: dict[str, Any] | None = None,
    ) -> ContextRelation:
        """Add a typed relation between two contexts."""
        rel = ContextRelation(
            source_uri=source_uri,
            target_uri=target_uri,
            relation_type=relation_type,
            metadata=metadata or {},
        )
        # Store on the source context's directory
        dir_path = self._uri_to_dir(source_uri)
        dir_path.mkdir(parents=True, exist_ok=True)
        rel_path = dir_path / self.RELATIONS_FILE

        existing = self._load_relations(rel_path)
        existing.append(rel)
        rel_path.write_text(
            json.dumps([r.model_dump(mode="json") for r in existing], indent=2, default=str),
            encoding="utf-8",
        )
        return rel

    def get_relations(self, uri: str) -> list[ContextRelation]:
        """Get all relations originating from a context."""
        dir_path = self._uri_to_dir(uri)
        return self._load_relations(dir_path / self.RELATIONS_FILE)

    def _load_relations(self, rel_path: Path) -> list[ContextRelation]:
        """Load relations from a file, or empty list if missing."""
        if not rel_path.exists():
            return []
        try:
            data = json.loads(rel_path.read_text(encoding="utf-8"))
            return [ContextRelation.model_validate(r) for r in data]
        except (json.JSONDecodeError, KeyError, ValueError):
            return []

    # -------------------------------------------------------------------
    # Tier-aware loading
    # -------------------------------------------------------------------

    def load_tier(self, uri: str, tier: ContextTier) -> Any:
        """Load only a specific tier of a context's content.

        L0 returns the abstract string, L1 returns the overview dict,
        L2 returns the full_data dict. Useful for prompt-time memory saving.
        """
        ctx = self.load(uri, touch=True)
        if ctx is None:
            return None
        return ctx.get_tier(tier)

    # -------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------

    def count(self, include_archived: bool = False) -> int:
        """Count total contexts in the store."""
        return len(self.list_all(include_archived=include_archived))

    def clear(self, category: str | None = None) -> int:
        """Remove contexts. If category is None, clears everything.

        Returns the number of contexts removed.
        """
        contexts = self.list_all(category=category, include_archived=True)
        count = 0
        for ctx in contexts:
            if self.delete(ctx.uri):
                count += 1
        return count
