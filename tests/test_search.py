import unittest
import json

from bastioncam.search import fts_expression, parse_query


class SearchTest(unittest.TestCase):
    def test_plain_query(self):
        def fake(*args, **kwargs):
            return {"response": json.dumps({"search_text":"cargo build","start":None,"end":None,"interpretation":None})}
        text, start, end, interpretation = parse_query("cargo build", request=fake)
        self.assertEqual(text, "cargo build")
        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertIsNone(interpretation)

    def test_model_time_range_is_normalized_to_utc(self):
        def fake(*args, **kwargs):
            return {"response": json.dumps({"search_text":"codex","start":"2026-08-30T18:00:00+02:00","end":"2026-08-30T19:00:00+02:00","interpretation":"last hour"})}
        text, start, end, interpretation = parse_query("codex an hour ago", request=fake)
        self.assertEqual((text, start, end, interpretation),
            ("codex", "2026-08-30T16:00:00+00:00", "2026-08-30T17:00:00+00:00", "last hour"))

    def test_model_failure_keeps_original_query(self):
        def fail(*args, **kwargs): raise TimeoutError()
        self.assertEqual(parse_query("anything", request=fail), ("anything", None, None, None))

    def test_fts_is_quoted(self):
        self.assertEqual(fts_expression("cargo build"), '"cargo" AND "build"')


if __name__ == "__main__":
    unittest.main()
