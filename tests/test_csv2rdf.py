import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from csv2rdf import CRM, GEO, KEO, convert_csv_to_rdf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "csv2rdf.py"


class ConvertCsvToRdfTests(unittest.TestCase):
	def setUp(self):
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.directory = Path(self.temp_dir.name)

	def write_csv(self, path, rows, delimiter=";"):
		with path.open("w", encoding="utf-8", newline="") as csv_file:
			writer = csv.writer(csv_file, delimiter=delimiter)
			writer.writerows(rows)

	def test_default_delimiter_and_rdf_mapping(self):
		input_path = self.directory / "input.csv"
		output_path = self.directory / "output.ttl"
		self.write_csv(
			input_path,
			[
				[
					"pid",
					"keo_bezeichnung",
					"beschreibung",
					"typ",
					"datierung_von",
					"WKT",
					"koordinatenbezugssystem",
					"weitere_datenverknuepfung",
				],
				[
					"site-1",
					" Beispiel ",
					" Beschreibung ",
					"https://example.org/type/building",
					"1800",
					"POINT (7.5 49.5)",
					"EPSG:25832",
					"https://example.org/related",
				],
			],
		)

		count = convert_csv_to_rdf(
			input_path, output_path, "https://data.example.org/sites"
		)

		self.assertEqual(count, 1)
		graph = Graph().parse(output_path, format="turtle")
		subject = URIRef("https://data.example.org/sites/site-1")
		geometry = URIRef(f"{subject}/geometry")
		time_span = URIRef(f"{subject}/time-span")
		appellation = URIRef(f"{subject}/appellation")

		self.assertIn((subject, RDF.type, CRM.E27_Site), graph)
		self.assertIn((subject, KEO.keo_bezeichnung, Literal("Beispiel")), graph)
		self.assertIn((subject, CRM.P3_has_note, Literal("Beschreibung", lang="de")), graph)
		self.assertIn((subject, CRM.P2_has_type, URIRef("https://example.org/type/building")), graph)
		self.assertIn((subject, CRM["P4_has_time-span"], time_span), graph)
		self.assertIn((time_span, CRM.P82a_begin_of_the_begin, Literal("1800", datatype=XSD.gYear)), graph)
		self.assertIn((subject, GEO.hasGeometry, geometry), graph)
		self.assertIn((geometry, GEO.asWKT, Literal("POINT (7.5 49.5)", datatype=GEO.wktLiteral)), graph)
		self.assertIn(
			(
				geometry,
				KEO.coordinateReferenceSystem,
				URIRef("http://www.opengis.net/def/crs/EPSG/0/25832"),
			),
			graph,
		)
		self.assertIn(
			(subject, CRM.P67_refers_to, URIRef("https://example.org/related")),
			graph,
		)
		self.assertIn(
			(appellation, CRM.P190_has_symbolic_content, Literal("Beispiel")),
			graph,
		)

	def test_custom_delimiter(self):
		input_path = self.directory / "comma.csv"
		output_path = self.directory / "comma.ttl"
		self.write_csv(
			input_path,
			[["pid", "keo_bezeichnung"], ["site-1", "Example"]],
			delimiter=",",
		)

		count = convert_csv_to_rdf(
			input_path,
			output_path,
			"https://data.example.org/sites",
			delimiter=",",
		)

		self.assertEqual(count, 1)
		graph = Graph().parse(output_path, format="turtle")
		self.assertIn(
			(
				URIRef("https://data.example.org/sites/site-1"),
				KEO.keo_bezeichnung,
				Literal("Example"),
			),
			graph,
		)

	def test_missing_header_raises_value_error(self):
		input_path = self.directory / "empty.csv"
		output_path = self.directory / "empty.ttl"
		input_path.write_text("", encoding="utf-8")

		with self.assertRaisesRegex(ValueError, "no header row"):
			convert_csv_to_rdf(input_path, output_path, "https://data.example.org/sites")

	def test_cli_accepts_delimiter_and_output_path(self):
		input_path = self.directory / "comma.csv"
		output_path = self.directory / "result.ttl"
		self.write_csv(
			input_path,
			[["pid", "keo_bezeichnung"], ["site-1", "Example"]],
			delimiter=",",
		)

		result = subprocess.run(
			[
				sys.executable,
				str(SCRIPT),
				str(input_path),
				"-d",
				",",
				"-o",
				str(output_path),
			],
			capture_output=True,
			text=True,
			check=False,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn("Converted 1 records", result.stdout)
		self.assertTrue(output_path.exists())
		graph = Graph().parse(output_path, format="turtle")
		self.assertIn(
			(
				URIRef("https://example.org/kulturerbe/site/site-1"),
				RDF.type,
				CRM.E27_Site,
			),
			graph,
		)

	def test_cli_uses_semicolon_by_default_and_turtle_extension(self):
		input_path = self.directory / "semicolon.csv"
		self.write_csv(input_path, [["pid"], ["site-1"]])
		output_path = input_path.with_suffix(".ttl")

		result = subprocess.run(
			[sys.executable, str(SCRIPT), str(input_path)],
			capture_output=True,
			text=True,
			check=False,
		)

		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn(f"Converted 1 records to {output_path}", result.stdout)
		self.assertTrue(output_path.exists())


if __name__ == "__main__":
	unittest.main()
