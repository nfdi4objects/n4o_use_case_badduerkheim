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

	def write_tsv(self, path, rows):
		with path.open("w", encoding="utf-8", newline="") as csv_file:
			writer = csv.writer(csv_file, delimiter="\t")
			writer.writerows(rows)

	def test_converts_tab_separated_rows_to_json(self):
		input_path = self.directory / "input.tsv"
		self.write_tsv(
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
