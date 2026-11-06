"""Write the OpenAPI document to stdout or a file: `python -m aigentix.export_openapi out.json`."""

import json
import os
import sys

# Exporting the schema must not require a running database.
os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@localhost:5432/unused")

from aigentix.api.app import create_app


def main() -> None:
    document = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            fh.write(document)
    else:
        sys.stdout.write(document)


if __name__ == "__main__":
    main()
