# Add LLM Integration

Create a new LLM provider integration for GeoSpark.

## Instructions

1. Read `geospark/integrations/` to understand the integration pattern
2. Read `geospark/tools/registry.py` to see how tools expose their schemas
3. The integration must:
   - Convert GeoSpark tools into the LLM provider's function/tool calling format
   - Handle the LLM's response and route tool calls back to GeoSpark engine
   - Support streaming responses where the provider supports it
4. Create integration at `geospark/integrations/<provider>_tools.py`
5. Write tests at `tests/integrations/test_<provider>.py`
6. Update `geospark/integrations/__init__.py`

## Supported Patterns
- **OpenAI**: function_call / tools format
- **Anthropic**: tool_use content blocks
- **MCP**: Model Context Protocol server
- **Ollama**: OpenAI-compatible with local models
- **Generic**: Any OpenAI-compatible API endpoint

## Key Rule
NEVER hard-code API keys. Always read from environment variables or config.
