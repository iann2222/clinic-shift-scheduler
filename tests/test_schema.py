from __future__ import annotations

import json
import unittest

from clinic_shift_scheduler.input_contracts import (
    CANONICAL_TOP_LEVEL_FIELDS,
    CONFIG_CANDIDATE_FIELDS,
    CONFIG_DIAGNOSTIC_TIME_FIELDS,
    CONFIG_ROOT_FIELDS,
    CONFIG_SETTINGS_FIELDS,
    EMPLOYEE_FIELDS,
    WEEKLY_TOP_LEVEL_FIELDS,
)
from clinic_shift_scheduler.schema import (
    APP_CONFIG_SCHEMA_VERSION,
    SCHEMA_VERSION,
    WEEKLY_AUTHORING_SCHEMA_VERSION,
    load_app_config_schema,
    load_v1_schema,
    load_weekly_authoring_schema,
)


class SchemaTests(unittest.TestCase):
    def test_bundled_v1_schema_is_valid_json_and_versioned(self) -> None:
        schema = load_v1_schema()

        self.assertEqual(SCHEMA_VERSION, "v1")
        self.assertEqual(schema["properties"]["schema_version"]["const"], "v1")
        self.assertEqual(schema["properties"]["periods"]["maxItems"], 3)
        self.assertEqual(set(schema["properties"]), CANONICAL_TOP_LEVEL_FIELDS)
        self.assertEqual(
            set(schema["$defs"]["employee"]["properties"]),
            EMPLOYEE_FIELDS,
        )
        json.dumps(schema)

    def test_user_document_schemas_are_bundled_and_versioned(self) -> None:
        weekly = load_weekly_authoring_schema()
        config = load_app_config_schema()

        self.assertEqual(WEEKLY_AUTHORING_SCHEMA_VERSION, "weekly-v1")
        self.assertEqual(
            weekly["properties"]["authoring_version"]["const"],
            WEEKLY_AUTHORING_SCHEMA_VERSION,
        )
        self.assertEqual(APP_CONFIG_SCHEMA_VERSION, "1")
        self.assertEqual(
            config["$defs"]["settings"]["properties"]["設定版本"]["const"],
            APP_CONFIG_SCHEMA_VERSION,
        )
        self.assertFalse(weekly["additionalProperties"])
        self.assertFalse(config["additionalProperties"])
        self.assertEqual(set(weekly["properties"]), WEEKLY_TOP_LEVEL_FIELDS)
        self.assertEqual(
            set(weekly["$defs"]["employee"]["properties"]),
            EMPLOYEE_FIELDS,
        )
        self.assertEqual(set(config["properties"]), CONFIG_ROOT_FIELDS)
        self.assertEqual(
            set(config["$defs"]["settings"]["properties"]),
            CONFIG_SETTINGS_FIELDS,
        )
        self.assertEqual(
            set(config["$defs"]["candidate"]["properties"]),
            CONFIG_CANDIDATE_FIELDS,
        )
        self.assertEqual(
            set(config["$defs"]["diagnosticTime"]["properties"]),
            CONFIG_DIAGNOSTIC_TIME_FIELDS,
        )
        json.dumps(weekly)
        json.dumps(config)


if __name__ == "__main__":
    unittest.main()
