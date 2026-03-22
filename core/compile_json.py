"""JSON export — structured output per schema v2.0."""

import json
from datetime import datetime, timezone
from pathlib import Path


def export_json(query_results: dict, output_dir: str = "precis") -> str:
    """Export query results as structured JSON. Returns output file path."""
    Path(output_dir).mkdir(exist_ok=True)

    plant_name = (
        query_results["query"].get("resolved_binomial")
        or query_results["query"]["input_string"]
    )
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in plant_name).strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_name}_{timestamp}.json"
    output_path = Path(output_dir) / filename

    output = {
        "schema_version": "2.0",
        "query": {
            **query_results["query"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "compilation_metadata": query_results["compilation_metadata"],
        "results": query_results["results"],
    }

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(output_path)
