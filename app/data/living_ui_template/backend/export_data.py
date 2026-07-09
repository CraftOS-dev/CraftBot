"""
Data export (SYSTEM-MANAGED — do not edit)

Dumps every table (schema entities + app state) to a timestamped JSON file
under <project>/exports/. Wired as the universal `export` op in
config/operations.json — `livingui <project> run export` — so every Living
UI ships data portability out of the box.

Run manually: python export_data.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main() -> int:
    from sqlalchemy import select

    import models  # noqa: F401 — registers system + engine models on Base
    from database import engine
    from system_models import Base

    out_dir = Path(__file__).parent.parent / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"export_{stamp}.json"

    dump = {"exportedAt": datetime.now().isoformat(), "tables": {}}
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in conn.execute(select(table)).fetchall()]
            for row in rows:
                for key, value in row.items():
                    if isinstance(value, datetime):
                        row[key] = value.isoformat()
            dump["tables"][table.name] = rows

    out_file.write_text(
        json.dumps(dump, indent=2, default=str), encoding="utf-8"
    )
    total = sum(len(r) for r in dump["tables"].values())
    print(f"Exported {total} rows across {len(dump['tables'])} tables -> {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
