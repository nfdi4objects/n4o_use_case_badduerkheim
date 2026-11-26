import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "csv2json.py"


class ConvertCsvToJsonTests(unittest.TestCase):
	def setUp(self):
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.directory = Path(self.temp_dir.name)

	def write_csv(self, path, rows):
		with path.open("w", encoding="utf-8", newline="") as csv_file:
			writer = csv.writer(csv_file, delimiter=",")
			writer.writerows(rows)

	def run_script(self, input_path):
		return subprocess.run(
			[sys.executable, str(SCRIPT), str(input_path)],
			capture_output=True,
			text=True,
			check=False,
		)

	def test_converts_comma_separated_rows_to_json(self):
		input_path = self.directory / "input.csv"
		self.write_csv(
			input_path,
			[
				["pid", "name", "description"],
				["site-1", "Bad Dürkheim", "A value with\ta tab"],
				["site-2", "Second site", ""],
			],
		)

		result = subprocess.run(
			[sys.executable, str(SCRIPT), str(input_path)],
			capture_output=True,
			text=True,
			check=False,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(
			json.loads(result.stdout),
			[
				{
					"pid": "site-1",
					"name": "Bad Dürkheim",
					"description": "A value with\ta tab",
				},
				{"pid": "site-2", "name": "Second site", "description": ""},
			],
		)

	def test_repeatable_fields_and_booleans_follow_part_c(self):
		input_path = self.directory / "keo.csv"
		self.write_csv(
			input_path,
			[
				["pid", "typ", "befundfrei", "keo_bezeichnung"],
				["site-1", "Siedlung | Gräberfeld", "true", "Burg, Ruine"],
				["site-2", "", "false", ""],
			],
		)

		result = self.run_script(input_path)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(
			json.loads(result.stdout),
			[
				{"pid": "site-1", "typ": ["Siedlung", "Gräberfeld"], "befundfrei": True, "keo_bezeichnung": "Burg, Ruine"},
				{"pid": "site-2", "typ": [], "befundfrei": False, "keo_bezeichnung": ""},
			],
		)

	def test_invalid_boolean_is_kept_as_text_with_warning(self):
		input_path = self.directory / "keo.csv"
		self.write_csv(input_path, [["pid", "befundfrei"], ["site-1", "ja"]])

		result = self.run_script(input_path)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), [{"pid": "site-1", "befundfrei": "ja"}])
		self.assertIn("not a boolean", result.stderr)

	def test_tab_separated_file_is_rejected(self):
		input_path = self.directory / "input.tsv"
		input_path.write_text("pid\tname\nsite-1\tBad Dürkheim\n", encoding="utf-8")

		result = self.run_script(input_path)

		self.assertEqual(result.returncode, 1)
		self.assertIn("not separated by commas", result.stderr)

	def test_empty_file_outputs_empty_array(self):
		input_path = self.directory / "empty.tsv"
		input_path.write_text("", encoding="utf-8")

		result = subprocess.run(
			[sys.executable, str(SCRIPT), str(input_path)],
			capture_output=True,
			text=True,
			check=False,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
	unittest.main()
