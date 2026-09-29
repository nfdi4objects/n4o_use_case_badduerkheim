"""Convert a tab-separated cultural heritage CSV file to CIDOC-CRM Turtle."""

import argparse
import csv
from pathlib import Path
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD
from rdflib.plugin import plugins
from rdflib.serializer import Serializer


CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
KEO = Namespace("https://example.org/vocab/kulturerbe/")
KEO_SITE = Namespace("https://example.org/kulturerbe/site/")
EPSG_URIS = {
	"EPSG:25832": "http://www.opengis.net/def/crs/EPSG/0/25832",
}
SERIALIZER_FORMATS = tuple(sorted({plugin.name for plugin in plugins(None, Serializer)}))
FORMAT_EXTENSIONS = {
	"application/ld+json": "jsonld",
	"application/n-quads": "nq",
	"application/n-triples": "nt",
	"application/rdf+xml": "rdf",
	"application/trig": "trig",
	"application/trix": "trix",
	"hext": "hext",
	"json-ld": "jsonld",
	"longturtle": "ttl",
	"n3": "n3",
	"nquads": "nq",
	"nt": "nt",
	"nt11": "nt",
	"ntriples": "nt",
	"patch": "patch",
	"pretty-xml": "rdf",
	"text/n3": "n3",
	"text/turtle": "ttl",
	"trig": "trig",
	"trix": "trix",
	"ttl": "ttl",
	"turtle": "ttl",
	"xml": "rdf",
}


def add_source_fields(graph, subject, row):
	"""Keep every non-empty source value available as a literal."""
	for field, value in row.items():
		if value and value.strip():
			graph.add((subject, KEO[quote(field, safe="")], Literal(value.strip())))


def add_appellation(graph, subject, value, suffix, resource_type):
	"""Attach a named CRM appellation or identifier to a site."""
	resource = URIRef(f"{subject}/{suffix}")
	graph.add((subject, CRM.P1_is_identified_by, resource))
	graph.add((resource, RDF.type, resource_type))
	graph.add((resource, CRM.P190_has_symbolic_content, Literal(value.strip())))


def add_geometry(graph, subject, wkt, crs):
	"""Attach a GeoSPARQL geometry, including its CRS when recognized."""
	geometry = URIRef(f"{subject}/geometry")
	graph.add((subject, GEO.hasGeometry, geometry))
	graph.add((geometry, RDF.type, GEO.Geometry))
	crs_uri = EPSG_URIS.get(crs.strip().upper())
	lexical_value = f"<{crs_uri}> {wkt.strip()}" if crs_uri else wkt.strip()
	graph.add((geometry, GEO.asWKT, Literal(lexical_value, datatype=GEO.wktLiteral)))


def add_site(graph, row, row_number, base_uri):
	"""Convert one CSV record into CRM and source-vocabulary triples."""
	identifier = row.get("pid", "").strip() or row.get("interne_id", "").strip()
	identifier = identifier or f"record-{row_number:06d}"
	site_namespace = Namespace(base_uri.rstrip("/") + "/")
	subject = site_namespace[quote(identifier, safe="")]

	graph.add((subject, RDF.type, CRM.E27_Site))
	add_source_fields(graph, subject, row)

	if row.get("keo_bezeichnung", "").strip():
		add_appellation(
			graph, subject, row["keo_bezeichnung"], "appellation", CRM.E41_Appellation
		)
	for field in ("pid", "interne_id"):
		value = row.get(field, "").strip()
		if value:
			add_appellation(graph, subject, value, f"identifier/{field}", CRM.E42_Identifier)

	for field in ("beschreibung", "erweiterte_beschreibung", "bemerkung"):
		value = row.get(field, "").strip()
		if value:
			graph.add((subject, CRM.P3_has_note, Literal(value, lang="de")))

	for field in ("typ", "epoche"):
		value = row.get(field, "").strip()
		if value:
			for item in value.split(","):
				item = item.strip()
				if item:
					graph.add((subject, CRM.P2_has_type, URIRef(item)))

	start = row.get("datierung_von", "").strip()
	end = row.get("datierung_nach", "").strip()
	if start or end:
		time_span = URIRef(f"{subject}/time-span")
		graph.add((subject, CRM["P4_has_time-span"], time_span))
		graph.add((time_span, RDF.type, CRM["E52_Time-Span"]))
		if start:
			graph.add((time_span, CRM.P82a_begin_of_the_begin, Literal(start, datatype=XSD.gYear)))
		if end:
			graph.add((time_span, CRM.P82b_end_of_the_end, Literal(end, datatype=XSD.gYear)))

	wkt = row.get("WKT", "").strip()
	if wkt:
		add_geometry(graph, subject, wkt, row.get("koordinatenbezugssystem", ""))

	for value in row.get("weitere_datenverknuepfung", "").split(","):
		value = value.strip()
		if value.startswith(("http://", "https://")):
			graph.add((subject, CRM.P67_refers_to, URIRef(value)))


def convert_csv_to_rdf(input_path, output_path, base_uri, rdf_format="turtle"):
	"""Read a tab-separated CSV and serialize its records in the requested RDF format."""
	graph = Graph()
	graph.bind("crm", CRM)
	graph.bind("geo", GEO)
	graph.bind("keo", KEO)
	site_namespace = Namespace(base_uri.rstrip("/") + "/")
	graph.bind("keo_site", site_namespace)

	with open(input_path, newline="", encoding="utf-8-sig") as csv_file:
		reader = csv.DictReader(csv_file, delimiter="\t")
		if not reader.fieldnames:
			raise ValueError("The input file is empty or has no header row.")
		for row_number, row in enumerate(reader, start=1):
			add_site(graph, row, row_number, base_uri)

	graph.serialize(destination=output_path, format=rdf_format, encoding="utf-8")
	return len(set(graph.subjects(RDF.type, CRM.E27_Site)))


def main():
	parser = argparse.ArgumentParser(
		description="Convert a tab-separated CSV file into CIDOC-CRM RDF."
	)
	parser.add_argument("input", type=Path, help="Input TSV/CSV file")
	parser.add_argument(
		"-o", "--output", type=Path, help="Output file (defaults to INPUT with a format-specific extension)"
	)
	parser.add_argument(
		"-f",
		"--format",
		choices=SERIALIZER_FORMATS,
		default="turtle",
		help="RDFLib serializer format (default: %(default)s)",
	)
	parser.add_argument(
		"--base-uri",
		default=str(KEO_SITE),
		help="Namespace for generated site identifiers (default: %(default)s)",
	)
	args = parser.parse_args()
	format_extension = FORMAT_EXTENSIONS.get(args.format, args.format.rsplit("/", 1)[-1])
	output_path = args.output or args.input.with_suffix(f".{format_extension}")

	try:
		record_count = convert_csv_to_rdf(
			args.input, output_path, args.base_uri, args.format
		)
	except (OSError, ValueError, csv.Error) as error:
		parser.error(str(error))

	print(f"Converted {record_count} records to {output_path}")


if __name__ == "__main__":
	main()
