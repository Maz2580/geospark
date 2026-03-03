# Custom GeoSpark Tools

Place your custom tools here. Each tool should:

1. Subclass `geospark.tools.base.BaseTool`
2. Set `name`, `description`, and `supported_operations`
3. Implement the `execute()` method

Example:

```python
from geospark.tools.base import BaseTool
from geospark.protocol.schema import SpatialQuery, SpatialResult

class MyCustomTool(BaseTool):
    name = "my_tool"
    description = "Does something spatial"
    supported_operations = ["my_operation"]

    def execute(self, query: SpatialQuery) -> SpatialResult:
        # Your implementation here
        return SpatialResult(...)
```

Register your tool:

```python
from geospark import Engine

engine = Engine()
engine.tool_registry.register_custom_tool(MyCustomTool())
```
