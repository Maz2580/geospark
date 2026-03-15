"""Context builder — assemble optimal spatial context for LLM prompts."""
from __future__ import annotations

from typing import Any

from geospark.rag.chunker import SpatialChunker
from geospark.rag.retriever import SpatialRetriever


class ContextBuilder:
    """Builds optimal spatial context for LLM prompts.

    Takes a user query, retrieves relevant spatial data, chunks it
    to fit context windows, and formats it for the LLM.
    """

    def __init__(
        self,
        retriever: SpatialRetriever | None = None,
        chunker: SpatialChunker | None = None,
        max_context_tokens: int = 4000,
    ) -> None:
        self.retriever = retriever or SpatialRetriever()
        self.chunker = chunker or SpatialChunker(max_tokens=max_context_tokens)
        self.max_context_tokens = max_context_tokens

    def build_context(
        self,
        query: str | None = None,
        geometry: dict[str, Any] | None = None,
        radius_m: float = 10000,
        max_features: int = 20,
    ) -> str:
        """Build spatial context string for an LLM prompt.

        Args:
            query: User's text query.
            geometry: Focus geometry (search center).
            radius_m: Search radius.
            max_features: Max features to include.

        Returns:
            Formatted context string ready for LLM prompt injection.
        """
        # Retrieve relevant features
        results = self.retriever.retrieve(
            query=query,
            geometry=geometry,
            radius_m=radius_m,
            limit=max_features,
        )

        if not results:
            return "No relevant spatial data found for this query."

        # Build context sections
        sections = ["## Spatial Context\n"]

        # Summary
        sections.append(
            f"Found {len(results)} relevant spatial features "
            f"(search radius: {radius_m/1000:.1f} km).\n"
        )

        # Feature details
        for i, r in enumerate(results, 1):
            props = r.feature.get("properties", {})
            geom = r.feature.get("geometry", {})

            line = f"{i}. "
            if "name" in props:
                line += f"**{props['name']}** "
            if "category" in props:
                line += f"[{props['category']}] "
            if r.distance_m is not None:
                line += f"({r.distance_m:,.0f}m away) "
            if geom.get("type") == "Point":
                coords = geom.get("coordinates", [])
                if len(coords) == 2:
                    line += f"at [{coords[0]:.4f}, {coords[1]:.4f}]"

            sections.append(line)

            # Add extra properties (skip geometry, name, category)
            extra = {
                k: v
                for k, v in props.items()
                if k not in ("name", "category", "geometry")
            }
            if extra:
                sections.append(f"   Properties: {extra}")

        # Check if we need to chunk
        features = [r.feature for r in results]
        chunks = self.chunker.chunk_features(features)
        if len(chunks) > 1:
            sections.append(
                f"\n*Note: Data split into {len(chunks)} chunks due to size. "
                f"Showing chunk 1 of {len(chunks)}.*"
            )

        return "\n".join(sections)

    def build_prompt_with_context(
        self,
        user_query: str,
        geometry: dict[str, Any] | None = None,
        radius_m: float = 10000,
        system_prompt: str = "",
    ) -> list[dict[str, str]]:
        """Build a complete prompt with spatial context injected.

        Returns a list of messages ready for the LLM API.
        """
        context = self.build_context(
            query=user_query,
            geometry=geometry,
            radius_m=radius_m,
        )

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Inject spatial context as a system message
        messages.append(
            {
                "role": "system",
                "content": f"The following spatial data is relevant to the user's question:\n\n{context}",
            }
        )

        messages.append({"role": "user", "content": user_query})

        return messages
