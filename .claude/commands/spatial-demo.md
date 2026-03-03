# Create Spatial Demo

Build a compelling visual demo showing GeoSpark's spatial reasoning vs raw LLM.

## Instructions

1. Create a Jupyter notebook at `examples/<demo_name>.ipynb` or a Python script at `examples/<demo_name>.py`
2. The demo should show a side-by-side comparison:
   - **Without GeoSpark**: Send a spatial question to an LLM directly, show it fails/hallucinates
   - **With GeoSpark**: Same question routed through GeoSpark engine, show accurate grounded result
3. Include visual outputs:
   - Use `folium` for interactive maps
   - Use `matplotlib` for charts/comparisons
   - Show the GSP query and result JSON
4. Good demo topics:
   - Topological reasoning (does A contain B?)
   - Distance queries (what's within 5km?)
   - Change detection (what changed between 2020-2025?)
   - Geocoding accuracy
   - CRS confusion examples
5. Run demos with: `.venv/Scripts/python.exe examples/<demo_name>.py`

## The goal: Create something visually compelling enough to go viral on Twitter/HN
