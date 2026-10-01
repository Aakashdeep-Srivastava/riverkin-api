"""Export the FastAPI OpenAPI schema to ``openapi.json`` at the repo root.

The OpenAPI schema is the contract with the frontend (CLAUDE.md). Regenerate
and commit it whenever an /api/v1 shape changes::

    uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    schema = app.openapi()
    out_path = Path(__file__).resolve().parent.parent / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
