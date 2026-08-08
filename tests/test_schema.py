from __future__ import annotations

import json
import unittest

from clinic_shift_scheduler.schema import SCHEMA_VERSION, load_v1_schema


class SchemaTests(unittest.TestCase):
    def test_bundled_v1_schema_is_valid_json_and_versioned(self) -> None:
        schema = load_v1_schema()

        self.assertEqual(SCHEMA_VERSION, "v1")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "v1")
        self.assertEqual(schema["properties"]["periods"]["maxItems"], 3)
        json.dumps(schema)


if __name__ == "__main__":
    unittest.main()

