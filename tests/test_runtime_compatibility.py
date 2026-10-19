"""Offline behavior checks without pytest or site-packages."""
import argparse
import json
import unittest
import cli_args

class RuntimeCompatibilityTests(unittest.TestCase):
    def test_parse_structured_arguments(self):
        args = cli_args.parse_args([cli_args.Argument(("--count",), {"type": int})], ["--count", "3"])
        self.assertEqual(args.count, 3)

    def test_finite_positive_validation(self):
        self.assertEqual(cli_args.positive_seconds("1.5"), 1.5)
        for value in ("0", "-1", "nan", "inf", "bad"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                cli_args.positive_seconds(value)

    def test_json_rendering(self):
        self.assertEqual(json.loads(cli_args.render_output({"a": [1, 2]}, format="json")), {"a": [1, 2]})
