import csv
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyproj
import shapely
import shapely.wkt
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from csv2rdf import CRM, EDTF, GEO, KEO, PROV, build_graph, convert_csv_to_rdf, dating_edtf, wkt_literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "csv2rdf.py"
TEST_DATA = Path(__file__).resolve().parent / "data"
SAMPLE = PROJECT_ROOT / "data" / "Kulturerbeobjekte_Knowledge_Graph"


class ConvertCsvToRdfTests(unittest.TestCase):
	def setUp(self):
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.directory = Path(self.temp_dir.name)

	def write_csv(self, path, rows, delimiter=","):
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
					"absolute_datierung_von",
					"geometrie",
					"koordinatenbezugssystem",
					"weitere_datenverknüpfung",
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
		record = URIRef("https://data.example.org/sites/datensatz/site-1")
		subject = URIRef(f"{record}#keo")
		place = URIRef(f"{record}#ort")
		geometry = URIRef(f"{record}#geometrie")
		period = URIRef(f"{record}#zeitstellung")
		description = graph.value(
			predicate=CRM.P190_has_symbolic_content, object=Literal("Beschreibung", lang="de")
		)

		self.assertIn((subject, RDF.type, CRM.E18_Physical_Thing), graph)
		self.assertIn((record, CRM.P70_documents, subject), graph)
		self.assertIn((subject, KEO.keo_bezeichnung, Literal("Beispiel")), graph)
		self.assertIn((subject, SKOS.prefLabel, Literal("Beispiel", lang="de")), graph)
		self.assertIn((subject, CRM.P67i_is_referred_to_by, description), graph)
		self.assertIn((subject, CRM.P2_has_type, URIRef("https://example.org/type/building")), graph)
		self.assertIn((subject, CRM.P12i_was_present_at, period), graph)
		self.assertIn((period, CRM["P4_has_time-span"], Literal("1800/..", datatype=EDTF)), graph)
		self.assertIn((subject, CRM.P53_has_former_or_current_location, place), graph)
		self.assertIn((place, GEO.hasGeometry, geometry), graph)
		self.assertIn(
			(
				geometry,
				GEO.asWKT,
				Literal(
					"<http://www.opengis.net/def/crs/EPSG/0/25832> POINT (7.5 49.5)",
					datatype=GEO.wktLiteral,
				),
			),
			graph,
		)
		self.assertIn(
			(subject, CRM.P70i_is_documented_in, URIRef("https://example.org/related")),
			graph,
		)

	def test_custom_delimiter(self):
		input_path = self.directory / "comma.csv"
		output_path = self.directory / "comma.ttl"
		self.write_csv(
			input_path,
			[["pid", "keo_bezeichnung"], ["site-1", "Example"]],
			delimiter=";",
		)

		count = convert_csv_to_rdf(
			input_path,
			output_path,
			"https://data.example.org/sites",
			delimiter=";",
		)

		self.assertEqual(count, 1)
		graph = Graph().parse(output_path, format="turtle")
		self.assertIn(
			(
				URIRef("https://data.example.org/sites/datensatz/site-1#keo"),
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
		input_path = self.directory / "semicolon.csv"
		output_path = self.directory / "result.ttl"
		self.write_csv(
			input_path,
			[["pid", "keo_bezeichnung"], ["site-1", "Example"]],
			delimiter=";",
		)

		result = subprocess.run(
			[
				sys.executable,
				str(SCRIPT),
				str(input_path),
				"-d",
				";",
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
				URIRef("https://example.org/keo/datensatz/site-1#keo"),
				RDF.type,
				CRM.E18_Physical_Thing,
			),
			graph,
		)

	def test_cli_uses_comma_by_default_and_turtle_extension(self):
		input_path = self.directory / "comma.csv"
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


# Minimal record with all MUSS fields
BASE = dict(
	pid="https://pid.example.org/t/1", interne_id="T1", typ="Test", fachbehörde="Amt",
	datenhaltende_institution="Amt", letzte_änderung="2025-01-01", datenexport="2025-01-02",
	epoche="Testzeit", geometrie="POINT (1 2)", koordinatenbezugssystem="EPSG:4326",
)


class CsvTestCase(unittest.TestCase):
	def setUp(self):
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.directory = Path(self.temp_dir.name)

	def convert_rows(self, rows):
		"""Write rows as KEO CSV, convert them and return (graph, count, warnings)."""
		path = self.directory / "input.csv"
		fields = sorted({field for row in rows for field in row})
		with path.open("w", encoding="utf-8", newline="") as csv_file:
			writer = csv.DictWriter(csv_file, fieldnames=fields)
			writer.writeheader()
			writer.writerows(rows)
		return build_graph(path)

	@staticmethod
	def texts(warnings):
		return " ".join(text for _, _, text in warnings)


class DatingTests(unittest.TestCase):
	def test_valid_combinations(self):
		for start, end, expected in [
			("1542", "1542", "1542"),
			("-0149/-0014", "-0149/-0014", "-0149/-0014"),
			("1200", "1350", "1200/1350"),
			("Y-11999", "-9999", "Y-11999/-9999"),
			("14XX", None, "14XX/.."),
			(None, "1520", "../1520"),
			("1542-05-21", "1543", "1542-05-21/1543"),
		]:
			with self.subTest(start=start, end=end):
				self.assertEqual(dating_edtf(start, end), expected)

	def test_invalid_combinations(self):
		for start, end in [("1600", "1500"), ("15.4.1600", "1601"), ("1542/1543/1544", "1545")]:
			with self.subTest(start=start, end=end):
				with self.assertRaises(ValueError):
					dating_edtf(start, end)


class AxisOrderTests(unittest.TestCase):
	def test_point_stays_at_brandenburg_gate_in_geosparql_reading(self):
		lon, lat = 13.377704, 52.516272
		for crs in ["EPSG:4326", "EPSG:25833", "EPSG:31467", "EPSG:4258", "EPSG:3035"]:
			with self.subTest(crs=crs):
				east, north = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
				literal = str(wkt_literal(shapely.Point(east, north), crs))
				iri, _, wkt = literal.rpartition("> ")
				# GeoSPARQL: coordinates in the axis order of the given CRS, CRS84 without IRI
				point = shapely.wkt.loads(wkt if iri else literal)
				back = pyproj.Transformer.from_crs(crs if iri else "OGC:CRS84", "OGC:CRS84").transform(point.x, point.y)
				self.assertAlmostEqual(back[0], lon, places=6)
				self.assertAlmostEqual(back[1], lat, places=6)


class ValueRuleTests(CsvTestCase):
	def test_complete_record_without_warning(self):
		_, count, warnings = self.convert_rows([BASE])
		self.assertEqual(count, 1)
		self.assertEqual(warnings, [])

	def test_data_links(self):
		graph, _, _ = self.convert_rows([dict(BASE, weitere_datenverknüpfung=(
			"https://www.wikidata.org/wiki/Q1 | https://d-nb.info/gnd/4005728-8 | https://portal.example.org/1"))])
		keo = URIRef("https://pid.example.org/t/1#keo")
		self.assertIn((keo, OWL.sameAs, URIRef("http://www.wikidata.org/entity/Q1")), graph)
		self.assertIn((keo, OWL.sameAs, URIRef("https://d-nb.info/gnd/4005728-8")), graph)
		self.assertIn((keo, CRM.P70i_is_documented_in, URIRef("https://portal.example.org/1")), graph)

	def test_invalid_values_are_reported(self):
		_, _, warnings = self.convert_rows([dict(
			BASE, obertägige_sichtbarkeit="ja", geometrie="GEOMETRYCOLLECTION (POINT (1 2))", fachbehörde="")])
		texts = self.texts(warnings)
		self.assertIn("not a boolean", texts)
		self.assertIn("geometry type not allowed: GeometryCollection", texts)
		self.assertIn(("https://pid.example.org/t/1", "fachbehörde", "MUSS field missing"), warnings)

	def test_comma_separated_uris_are_not_mapped(self):
		graph, _, warnings = self.convert_rows([dict(BASE, epoche="http://example.org/e/1, http://example.org/e/2")])
		self.assertIn("not a single valid URI", self.texts(warnings))
		self.assertNotIn((None, RDF.type, CRM.E4_Period), graph)

	def test_several_crs_in_one_csv_are_reported(self):
		_, _, warnings = self.convert_rows([BASE, dict(BASE, pid="P2", koordinatenbezugssystem="EPSG:25832")])
		self.assertIn("several CRS in one file", self.texts(warnings))

	def test_absolute_dating_requires_abgeleitet(self):
		_, _, warnings = self.convert_rows([dict(BASE, absolute_datierung_von="1200")])
		self.assertIn(("https://pid.example.org/t/1", "absolute_datierung_abgeleitet",
					   "MUSS field missing, as an absolute dating is given"), warnings)

	def test_examples_from_the_standard(self):
		graph, _, warnings = self.convert_rows([
			dict(BASE, pid="hdl:20.500.12345/beispiel-suffix",
				 lagebezeichnung_geonames="https://www.geonames.org/2950159/berlin.html",
				 translozierung="true", transloziert_standort="Datensatz beschreibt neuen Standort", lizenz="CC BY 4.0"),
			dict(BASE, pid="GDKE/FM2017-134", lagebezeichnung_geonames="2950159",
				 translozierung="true", transloziert_standort="Datensatz beschreibt Originalstandort",
				 lizenz="https://creativecommons.org/publicdomain/zero/1.0/deed.de"),
		])
		handle = URIRef("https://hdl.handle.net/20.500.12345/beispiel-suffix")
		gdke = URIRef("https://example.org/keo/datensatz/GDKE%2FFM2017-134")
		self.assertIn((handle, RDF.type, CRM.E31_Document), graph)
		self.assertIn((gdke, RDF.type, CRM.E31_Document), graph)
		self.assertEqual(len(list(graph.subjects(CRM.P89_falls_within, URIRef("https://sws.geonames.org/2950159/")))), 2)
		self.assertIn((URIRef(f"{handle}#translozierung"), CRM.P26_moved_to, URIRef(f"{handle}#ort")), graph)
		self.assertIn((URIRef(f"{gdke}#translozierung"), CRM.P27_moved_from, URIRef(f"{gdke}#ort")), graph)
		self.assertIn((handle, DCTERMS.license, URIRef("https://creativecommons.org/licenses/by/4.0/")), graph)
		self.assertIn((gdke, DCTERMS.license, URIRef("https://creativecommons.org/publicdomain/zero/1.0/")), graph)
		self.assertEqual(warnings, [])

	def test_csv_example_of_part_c(self):
		path = self.directory / "teil_c.csv"
		path.write_text(
			"interne_id,typ,epoche,geometrie,koordinatenbezugssystem\n"
			"FM2017-134,Grabhügel,Bronzezeit,POINT (13.377704 52.516272),EPSG:4326\n"
			'FM2017-135,Siedlung | Gräberfeld,Hallstatt D | Latène A,"POLYGON ((11.36078 48.06161, '
			'11.72287 48.06161, 11.72287 48.24822, 11.36078 48.06161))",EPSG:4326\n',
			encoding="utf-8",
		)
		graph, count, warnings = build_graph(path)
		self.assertEqual(count, 2)
		self.assertEqual(len(set(graph.subjects(RDF.type, CRM.E4_Period))), 3)
		self.assertEqual(len(list(graph.objects(None, GEO.asWKT))), 2)
		self.assertEqual({field for _, field, _ in warnings},
						 {"pid", "fachbehörde", "datenhaltende_institution", "letzte_änderung", "datenexport"})

	def test_access_rights_use_the_eu_authority_table(self):
		graph, _, warnings = self.convert_rows([
			dict(BASE, pid="https://pid.example.org/t/1", zugriffsrecht="öffentlich"),
			dict(BASE, pid="https://pid.example.org/t/2", zugriffsrecht="Eingeschränkt"),
			dict(BASE, pid="https://pid.example.org/t/3", zugriffsrecht="nicht öffentlich"),
			dict(BASE, pid="https://pid.example.org/t/4", zugriffsrecht="ja"),
		])
		base = "http://publications.europa.eu/resource/authority/access-right/"
		for number, code in [(1, "PUBLIC"), (2, "RESTRICTED"), (3, "NON_PUBLIC")]:
			with self.subTest(code=code):
				self.assertIn((URIRef(f"https://pid.example.org/t/{number}"), DCTERMS.accessRights, URIRef(base + code)), graph)
		self.assertNotIn((URIRef("https://pid.example.org/t/4"), DCTERMS.accessRights, None), graph)
		self.assertIn("value not allowed: ja", self.texts(warnings))

	def test_export_date_is_the_generation_time_of_the_record(self):
		graph, _, _ = self.convert_rows([dict(BASE, datenexport="2026-06-23T08:12:30")])
		record = URIRef("https://pid.example.org/t/1")
		self.assertIn((record, PROV.generatedAtTime, Literal("2026-06-23T08:12:30", datatype=XSD.dateTime)), graph)
		self.assertNotIn((record, DCTERMS.issued, None), graph)

	def test_esri_crs_with_latitude_first_is_swapped_and_reported_once(self):
		graph, _, warnings = self.convert_rows([
			dict(BASE, geometrie="POINT (13.377704 52.516272)", koordinatenbezugssystem="ESRI:104013"),
			dict(BASE, pid="P2", geometrie="POINT (13.4 52.5)", koordinatenbezugssystem="ESRI:104013"),
		])
		literals = sorted(str(o) for o in graph.objects(None, GEO.asWKT))
		self.assertTrue(literals[0].startswith("<http://www.opengis.net/def/crs/ESRI/0/104013> POINT (52.5"))
		self.assertEqual(
			[text for _, field, text in warnings if field == "koordinatenbezugssystem"],
			["ESRI:104013: GeoSPARQL systems usually know only EPSG and OGC IRIs. Equivalent: EPSG:9055."],
		)

	def test_tab_separated_file_is_skipped_with_message(self):
		path = self.directory / "tabs.csv"
		path.write_text("geometrie\tpid\tinterne_id\nPOINT (1 2)\tP1\tT1\n", encoding="utf-8")
		_, count, warnings = build_graph(path)
		self.assertEqual(count, 0)
		self.assertIn("separated by tabs", self.texts(warnings))


class SampleDataTests(unittest.TestCase):
	"""The files in data/ must match what the scripts produce from the CSV."""

	def test_turtle_and_ntriples_are_current(self):
		graph, _, warnings = build_graph(SAMPLE.with_suffix(".csv"))
		self.assertEqual(warnings, [])
		for suffix, rdf_format in ((".ttl", "turtle"), (".nt", "nt")):
			with self.subTest(file=suffix):
				self.assertTrue(isomorphic(graph, Graph().parse(SAMPLE.with_suffix(suffix), format=rdf_format)))

	def test_json_is_current(self):
		result = subprocess.run([sys.executable, str(PROJECT_ROOT / "csv2json.py"), str(SAMPLE.with_suffix(".csv"))],
								capture_output=True, text=True, encoding="utf-8", check=True)
		self.assertEqual(result.stdout, SAMPLE.with_suffix(".json").read_text(encoding="utf-8"))


class FurtherCommandLineTests(unittest.TestCase):
	def setUp(self):
		self.temp_dir = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp_dir.cleanup)
		self.directory = Path(self.temp_dir.name)

	def run_script(self, *arguments):
		return subprocess.run([sys.executable, str(SCRIPT), *map(str, arguments)],
							  capture_output=True, text=True, encoding="utf-8", check=False)

	def test_default_output_beside_the_input(self):
		input_path = self.directory / "keo.csv"
		input_path.write_bytes((TEST_DATA / "keo_beispiel.csv").read_bytes())
		result = self.run_script(input_path)
		self.assertEqual(result.returncode, 0, result.stderr)
		self.assertIn(f"Converted 6 records to {input_path.with_suffix('.ttl')}", result.stdout)
		self.assertIn("WARNING https://pid.example.org/keo/0006 [geometrie]", result.stderr)
		self.assertTrue(input_path.with_suffix(".ttl").exists())

	def test_format_option_ntriples(self):
		output_path = self.directory / "out.nt"
		result = self.run_script(TEST_DATA / "keo_beispiel.csv", "-f", "nt", "-o", output_path)
		self.assertEqual(result.returncode, 0, result.stderr)
		expected = build_graph(TEST_DATA / "keo_beispiel.csv")[0]
		self.assertTrue(isomorphic(Graph().parse(output_path, format="nt"), expected))


class ApplicationProfileTests(unittest.TestCase):
	"""Constructs the profile excludes must not appear (no ontology files needed)."""

	def test_no_excluded_constructs(self):
		graph = build_graph(TEST_DATA / "keo_beispiel.csv")[0]
		excluded = [CRM.E55_Type, CRM.E41_Appellation, CRM.E42_Identifier, CRM.E32_Authority_Document, CRM.P71_lists,
					CRM.P81a_end_of_the_begin, CRM.P81b_begin_of_the_end, CRM.P82a_begin_of_the_begin,
					CRM.P82b_end_of_the_end, CRM.P169i_spacetime_volume_is_defined_by, CRM.E95_Spacetime_Primitive]
		for term in excluded:
			with self.subTest(term=term):
				self.assertNotIn((None, None, term), graph)
				self.assertNotIn((None, term, None), graph)


@unittest.skipUnless(os.environ.get("CRM_RDF_AP"), "set CRM_RDF_AP to a clone of nfdi4objects/crm-rdf-ap")
class OntologyConformanceTests(unittest.TestCase):
	"""All terms are defined, and domain and range of all CRM properties fit."""

	@classmethod
	def setUpClass(cls):
		profile = Path(os.environ["CRM_RDF_AP"])
		cls.ontology = Graph().parse(profile / "cidoc-crm.rdf", format="xml")
		for name in ("geo.ttl", "bibo.ttl"):
			cls.ontology.parse(profile / name)
		cls.graph = Graph()
		for path in (TEST_DATA / "keo_beispiel.csv", SAMPLE.with_suffix(".csv")):
			cls.graph += build_graph(path)[0]

	def test_all_terms_are_defined(self):
		skos = Namespace("http://www.w3.org/2004/02/skos/core#")
		known = set(self.ontology.subjects()) | {skos[t] for t in ("Concept", "ConceptScheme", "inScheme", "prefLabel")}
		terms = set(self.graph.predicates()) | set(self.graph.objects(None, RDF.type))
		namespaces = (str(CRM), str(GEO), "http://purl.org/ontology/bibo/", str(skos))
		unknown = sorted(str(t) for t in terms if str(t).startswith(namespaces) and t not in known)
		self.assertEqual(unknown, [])

	def test_domain_and_range(self):
		def superclasses(cls):
			result, todo = set(), [cls]
			while todo:
				current = todo.pop()
				if current not in result:
					result.add(current)
					todo.extend(self.ontology.objects(current, RDFS.subClassOf))
			return result

		def types(resource):
			classes = list(self.graph.objects(resource, RDF.type))
			return set().union(*map(superclasses, classes)) if classes else None

		violations = []
		for subject, prop, obj in self.graph:
			if not str(prop).startswith(str(CRM)):
				continue
			for domain in self.ontology.objects(prop, RDFS.domain):
				subject_types = types(subject)
				if subject_types is not None and domain not in subject_types and domain != CRM.E1_CRM_Entity:
					violations.append(f"domain of {prop}: {subject}")
			for range_ in self.ontology.objects(prop, RDFS.range):
				if isinstance(obj, Literal) or range_ in (CRM.E1_CRM_Entity, RDFS.Literal):
					continue
				object_types = types(obj)
				if object_types is not None and range_ not in object_types:
					violations.append(f"range of {prop}: {obj}")
		self.assertEqual(violations, [])


if __name__ == "__main__":
	unittest.main()
