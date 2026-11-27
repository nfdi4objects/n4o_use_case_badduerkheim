"""Convert a cultural heritage CSV file to CIDOC-CRM RDF.

The input follows version 1.1 of the community standard for cultural heritage
objects (KEO). The mapping is specified in docs/mapping_cidoc_crm.md and
follows CIDOC CRM 7.1.3 and the NFDI4Objects CIDOC-CRM-in-RDF application
profile. Problems in the data do not stop the conversion. They are reported
as warnings.
"""

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pyproj
import shapely
import shapely.wkt
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD
from rdflib.plugin import plugins
from rdflib.serializer import Serializer

from keo_standard import FIELDS, REQUIRED, DelimiterError, nfc, parse_boolean, read_csv_rows, split_list

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
KEO = Namespace("https://example.org/vocab/kulturerbe/")
KEO_BASE = Namespace("https://example.org/keo/")
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
BIBO = Namespace("http://purl.org/ontology/bibo/")
PROV = Namespace("http://www.w3.org/ns/prov#")
EDTF = URIRef("http://id.loc.gov/datatypes/edtf/EDTF")

# Fields that expect a URI or a term. Text containing an embedded URI is
# almost always a list with the wrong separator: report it, do not guess.
URI_OR_TERM = [
	"typ", "epoche", "lagegenauigkeit", "datenerhebungsqualität", "vorschaubild", "fachbehörde",
	"genehmigungsbehörde", "datenhaltende_institution", "datenhaltendes_system", "urheber",
]

# Fixed vocabulary of the mapping (SKOS). Key -> (path below <base>vocab/, label)
VOCABULARY = {
	"pid": ("identifikator/pid", "PID des Datensatzes"),
	"interne_id": ("identifikator/interne-id", "Interne ID"),
	"adresse": ("identifikator/adresse", "Adresse"),
	"ags": ("identifikator/ags", "Amtlicher Gemeindeschlüssel"),
	"beschreibung": ("text/beschreibung", "Kurzbeschreibung"),
	"erweiterte_beschreibung": ("text/erweiterte-beschreibung", "Erweiterte Beschreibung"),
	"datierungsinformation": ("text/datierungsinformation", "Weitere Datierungsinformationen"),
	"lagebeschreibung": ("text/lagebeschreibung", "Lagebeschreibung"),
	"bemerkung": ("text/bemerkung", "Bemerkung zum Datensatz"),
	"abgeleitet": ("datierung/abgeleitet", "Absolute Datierung aus Epoche abgeleitet"),
	"sichtbar": ("sichtbarkeit/obertaegig-sichtbar", "obertägig sichtbar"),
	"nicht_sichtbar": ("sichtbarkeit/nicht-obertaegig-sichtbar", "nicht obertägig sichtbar"),
	"befundfrei": ("befund/befundfrei", "befundfrei"),
	"nicht_befundfrei": ("befund/nicht-befundfrei", "nicht befundfrei"),
	"nicht_transloziert": ("translozierung/nicht-transloziert", "nicht transloziert"),
	"fachzustaendigkeit": ("zustaendigkeit/fachbehoerde", "denkmalfachliche Zuständigkeit"),
	"genehmigungszustaendigkeit": ("zustaendigkeit/genehmigung", "Genehmigungszuständigkeit"),
}
# Concept schemes for values given as free text instead of a URI
SCHEMES = {
	"typ": "Typ",
	"lagegenauigkeit": "Lagegenauigkeit",
	"datenerhebungsqualitaet": "Datenerhebungsqualität",
}

# zugriffsrecht: values of the standard -> EU access right authority table
ACCESS_RIGHTS = "http://publications.europa.eu/resource/authority/access-right/"
ACCESS_RIGHT_VALUES = {
	"öffentlich": "PUBLIC",
	"eingeschränkt": "RESTRICTED",
	"nicht öffentlich": "NON_PUBLIC",
}

CC_LICENSES = {
	"cc0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
	"cc by 4.0": "https://creativecommons.org/licenses/by/4.0/",
	"cc by-sa 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
	"cc by-nd 4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
	"cc by-nc 4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
	"cc by-nc-sa 4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
	"cc by-nc-nd 4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
}

URI = re.compile(r"^https?://\S+$")
EDTF_DATE = re.compile(
	r"^(?:Y-?\d{5,}|-?(?:\d{4}|\d{3}X|\d{2}XX)(?:-\d{2}(?:-\d{2})?)?)[?~%]?$")
ISO_TIMESTAMP = re.compile(
	r"^\d{4}(?:-\d{2}(?:-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?)?)?$")
ALLOWED_GEOMETRIES = {"Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"}



class Warnings:
	"""Collects warnings per record instead of stopping the conversion."""

	def __init__(self):
		self.items = []

	def __call__(self, record, field, text):
		self.items.append((record, field, text))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def add_source_fields(graph, subject, row):
	"""Keep every non-empty source value available as a literal."""
	for field, value in row.items():
		if value and value.strip():
			graph.add((subject, KEO[quote(field, safe="")], Literal(value.strip())))


def normalise(row, warn, label):
	"""Record as dict field name -> value. Repeatable fields become lists."""
	record = {}
	for name, value in row.items():
		field = nfc(name)
		if field not in FIELDS:
			warn(label, field, "unknown field, ignored")
			continue
		if value is None or not nfc(value):
			continue
		record[field] = split_list(value) if FIELDS[field] else nfc(value)
	return record


def read_records(input_path, delimiter, warn):
	"""Yield (row, record) per CSV line. The geometry becomes a shapely object."""
	try:
		rows = list(read_csv_rows(input_path, delimiter))
	except DelimiterError as error:
		warn(Path(input_path).name, "-", f"{error}. File skipped")
		return
	for line_number, row in rows:
		label = f"{Path(input_path).name}:{line_number}"
		if None in row:
			warn(label, "-", "more values than columns, surplus values ignored")
			del row[None]
		record = normalise(row, warn, label)
		if "geometrie" in record:
			try:
				record["geometrie"] = shapely.wkt.loads(record["geometrie"])
			except Exception as error:
				warn(record.get("pid", label), "geometrie", f"WKT not readable: {error}")
				del record["geometrie"]
		yield row, record


# ---------------------------------------------------------------------------
# Value conversions
# ---------------------------------------------------------------------------
def edtf_bounds(value):
	"""Split a single value or an interval a/b into (lower, upper) bound."""
	parts = value.split("/")
	if len(parts) == 1:
		lower = upper = parts[0]
	elif len(parts) == 2:
		lower, upper = parts
	else:
		raise ValueError(f"not an EDTF value: {value}")
	for part in (lower, upper):
		if not EDTF_DATE.match(part):
			raise ValueError(f"not an EDTF date according to ISO 8601-2: {part}")
	return lower, upper


def year(edtf):
	"""Rough year for checking that the beginning precedes the end."""
	match = re.match(r"^Y?(-?\d+)", edtf.replace("X", "0"))
	return int(match.group(1)) if match else None


def dating_edtf(start, end):
	"""Join absolute_datierung_von and _bis into one EDTF expression from the
	earliest to the latest bound."""
	begin = edtf_bounds(start)[0] if start else ".."
	finish = edtf_bounds(end)[1] if end else ".."
	if start and end and begin == finish:
		return begin
	if start and end and year(begin) is not None and year(finish) is not None and year(begin) > year(finish):
		raise ValueError(f"beginning {begin} lies after the end {finish}")
	return f"{begin}/{finish}"


def timestamp(value):
	"""ISO 8601 date or date and time as a suitably typed literal."""
	text = str(value).strip()
	if not ISO_TIMESTAMP.match(text):
		raise ValueError(f"not an ISO 8601 date: {text}")
	if "T" in text:
		return Literal(text, datatype=XSD.dateTime)
	datatype = {4: XSD.gYear, 7: XSD.gYearMonth, 10: XSD.date}[len(text)]
	return Literal(text, datatype=datatype)


def wkt_literal(geometry, crs_text):
	"""WKT with CRS IRI according to GeoSPARQL.

	GeoSPARQL reads coordinates in the axis order defined by the CRS. The KEO
	standard always writes east before north. Coordinates of a CRS with north
	first are therefore swapped. EPSG:4326 is written without CRS IRI, which
	means CRS84 in GeoSPARQL: WGS 84 with longitude before latitude. No
	coordinates are transformed.
	"""
	crs = pyproj.CRS.from_user_input(crs_text)
	if crs.to_epsg() == 4326 or crs_text.upper() in ("OGC:CRS84", "CRS84"):
		iri = None
	else:
		authority = crs.to_authority()
		if authority is None:
			raise ValueError(f"CRS without code of an authority: {crs_text}")
		iri = f"http://www.opengis.net/def/crs/{authority[0]}/0/{authority[1]}"
		if crs.axis_info and crs.axis_info[0].direction.lower() in ("north", "south"):
			order = [1, 0, 2] if geometry.has_z else [1, 0]
			geometry = shapely.transform(geometry, lambda coords: coords[:, order], include_z=geometry.has_z)
	wkt = shapely.to_wkt(geometry, rounding_precision=-1, trim=True)
	return Literal(f"<{iri}> {wkt}" if iri else wkt, datatype=GEO.wktLiteral)


# ---------------------------------------------------------------------------
# Mapping of one record to CIDOC CRM
# ---------------------------------------------------------------------------
class Mapper:
	def __init__(self, base_uri, language, warn):
		self.base = base_uri if base_uri.endswith("/") else base_uri + "/"
		self.language = language
		self.warn = warn
		self.graph = Graph()
		for prefix, namespace in [("crm", CRM), ("geo", GEO), ("bibo", BIBO), ("prov", PROV), ("skos", SKOS),
								  ("dcterms", DCTERMS), ("owl", OWL), ("xsd", XSD),
								  ("edtf", Namespace("http://id.loc.gov/datatypes/edtf/")),
								  ("keo", KEO), ("keo_base", Namespace(self.base)),
								  ("keov", Namespace(self.base + "vocab/"))]:
			self.graph.bind(prefix, namespace)
		self.used_concepts = set()
		self.areas = set()
		self.checked_crs = set()

	# --- helpers ------------------------------------------------------------
	def iri(self, path):
		return URIRef(self.base + path)

	def concept(self, key):
		self.used_concepts.add(key)
		return self.iri("vocab/" + VOCABULARY[key][0])

	def text(self, value, with_language=True):
		return Literal(value, lang=self.language if with_language else None)

	def value_concept(self, value, scheme):
		"""Use a URI from a vocabulary directly, free text as a local concept."""
		if URI.match(value):
			return URIRef(value)
		iri = self.iri(f"vocab/{scheme}/{quote(value, safe='')}")
		scheme_iri = self.iri(f"vocab/{scheme}")
		self.graph.add((iri, RDF.type, SKOS.Concept))
		self.graph.add((iri, SKOS.prefLabel, self.text(value)))
		self.graph.add((iri, SKOS.inScheme, scheme_iri))
		self.graph.add((scheme_iri, RDF.type, SKOS.ConceptScheme))
		self.graph.add((scheme_iri, SKOS.prefLabel, self.text(SCHEMES[scheme])))
		return iri

	def identifier(self, subject, value, key):
		node = BNode()
		self.graph.add((subject, CRM.P1_is_identified_by, node))
		self.graph.add((node, RDF.value, Literal(value)))
		self.graph.add((node, CRM.P2_has_type, self.concept(key)))

	def free_text(self, subject, value, key):
		node = BNode()
		self.graph.add((subject, CRM.P67i_is_referred_to_by, node))
		self.graph.add((node, RDF.type, CRM.E33_Linguistic_Object))
		self.graph.add((node, CRM.P2_has_type, self.concept(key)))
		self.graph.add((node, CRM.P190_has_symbolic_content, self.text(value)))

	def actor(self, value):
		if URI.match(value):
			iri = URIRef(value)
			actor_class = (CRM.E74_Group if "://ror.org/" in value else
						   CRM.E21_Person if "://orcid.org/" in value else CRM.E39_Actor)
			self.graph.add((iri, RDF.type, actor_class))
			return iri
		iri = self.iri("akteur/" + quote(value, safe=""))
		self.graph.add((iri, RDF.type, CRM.E39_Actor))
		self.graph.add((iri, SKOS.prefLabel, Literal(value)))
		return iri

	@staticmethod
	def part(iri, name):
		return URIRef(f"{iri}{'#' if '#' not in iri else '-'}{name}")

	def record_iri(self, record):
		"""IRI of the record and whether the PID itself is that IRI."""
		pid = record.get("pid")
		if not pid:
			key = f"{record.get('datenhaltende_institution', '')}|{record.get('interne_id', '')}"
			return self.iri("datensatz/ohne-pid/" + hashlib.sha1(key.encode()).hexdigest()[:16]), False
		if URI.match(pid):
			return URIRef(pid), True
		for pattern, resolver in [(r"^hdl:(.+)$", "https://hdl.handle.net/"),
								  (r"^doi:(.+)$", "https://doi.org/"),
								  (r"^(ark:/?.+)$", "https://n2t.net/")]:
			match = re.match(pattern, pid, re.IGNORECASE)
			if match:
				return URIRef(resolver + match.group(1)), False
		return self.iri("datensatz/" + quote(pid, safe="")), False

	# --- main mapping -------------------------------------------------------
	def map_record(self, record):
		g, P = self.graph, CRM
		dataset, pid_is_iri = self.record_iri(record)
		name = record.get("pid") or record.get("interne_id") or str(dataset)

		def warn(field, text):
			self.warn(name, field, text)

		for field in REQUIRED:
			if field not in record:
				warn(field, "MUSS field missing")
		for field in URI_OR_TERM:
			values = record.get(field)
			listed = values if isinstance(values, list) else [values] if isinstance(values, str) else []
			invalid = [v for v in listed if re.search(r"https?://", v) and not URI.match(v)]
			for value in invalid:
				warn(field, f"not a single valid URI, not mapped (the separator for several values is |): {value}")
			if invalid:
				rest = [v for v in listed if v not in invalid]
				if isinstance(values, list) and rest:
					record[field] = rest
				else:
					del record[field]
		if not any(f in record for f in ("absolute_datierung_von", "absolute_datierung_bis", "epoche")):
			warn("datierung", "MUSS: neither absolute dating nor epoch given")

		keo = self.part(dataset, "keo")
		place = self.part(dataset, "ort")

		# 1 Identifiers
		g.add((dataset, RDF.type, P.E31_Document))
		g.add((dataset, P.P70_documents, keo))
		if record.get("pid") and not pid_is_iri:
			self.identifier(dataset, record["pid"], "pid")
		g.add((keo, RDF.type, P.E18_Physical_Thing))
		if "interne_id" in record:
			self.identifier(keo, record["interne_id"], "interne_id")
		for value in record.get("weitere_datenverknüpfung", []):
			self.data_link(keo, value, warn)
		if "keo_bezeichnung" in record:
			g.add((keo, SKOS.prefLabel, self.text(record["keo_bezeichnung"])))

		# 2 Description
		if "beschreibung" in record:
			self.free_text(keo, record["beschreibung"], "beschreibung")
		if "erweiterte_beschreibung" in record:
			self.free_text(keo, record["erweiterte_beschreibung"], "erweiterte_beschreibung")
		for value in record.get("typ", []):
			g.add((keo, P.P2_has_type, self.value_concept(value, "typ")))
		self.dating(keo, dataset, record, warn)
		for value in record.get("literatur", []):
			doi = re.search(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\S+)", value, re.IGNORECASE)
			document = URIRef("https://doi.org/" + doi.group(1).rstrip(".,;)")) if doi else BNode()
			g.add((document, RDF.type, BIBO.Document))
			g.add((document, RDF.type, P.E31_Document))  # domain of P70, allowed by the profile
			g.add((document, RDFS.label, Literal(value)))
			g.add((document, P.P70_documents, keo))
		self.boolean_concept(keo, record, "obertägige_sichtbarkeit", "sichtbar", "nicht_sichtbar", warn)
		if "vorschaubild" in record:
			image = URIRef(record["vorschaubild"])
			g.add((keo, P.P138i_has_representation, image))
			g.add((image, RDF.type, P.E36_Visual_Item))
		for value in record.get("verweise", []):
			match = re.match(r"^\[(.*)\]\((\S+)\)$", value)
			target, caption = (match.group(2), match.group(1)) if match else (value, None)
			if not URI.match(target):
				warn("verweise", f"not a link: {value}")
				continue
			g.add((keo, P.P67i_is_referred_to_by, URIRef(target)))
			g.add((URIRef(target), RDF.type, P.E73_Information_Object))
			if caption:
				g.add((URIRef(target), RDFS.label, self.text(caption)))

		# 3 Location
		g.add((keo, P.P53_has_former_or_current_location, place))
		g.add((place, RDF.type, P.E53_Place))
		self.geometry(place, dataset, record, warn)
		self.translocation(keo, place, dataset, record, warn)
		if "lagebezeichnung_adresse" in record:
			self.identifier(place, record["lagebezeichnung_adresse"], "adresse")
		if "lagebezeichnung_ags" in record:
			ags = re.sub(r"\s+", "", record["lagebezeichnung_ags"])
			if ags != record["lagebezeichnung_ags"]:
				warn("lagebezeichnung_ags", "spaces removed from AGS")
			if not re.fullmatch(r"\d{2}|\d{3}|\d{5}|\d{8}", ags):
				warn("lagebezeichnung_ags", f"AGS does not have 2, 3, 5 or 8 digits: {ags}")
			area = self.iri("ags/" + ags)
			g.add((place, P.P89_falls_within, area))
			if area not in self.areas:  # identifier only once per area
				self.areas.add(area)
				g.add((area, RDF.type, P.E53_Place))
				self.identifier(area, ags, "ags")
		if "lagebezeichnung_geonames" in record:
			match = re.search(r"(?:geonames\.org/)?(\d+)", record["lagebezeichnung_geonames"])
			if match:
				g.add((place, P.P89_falls_within, URIRef(f"https://sws.geonames.org/{match.group(1)}/")))
			else:
				warn("lagebezeichnung_geonames", "no GeoNames ID found")
		if "lagebezeichnung_freitext" in record:
			self.free_text(place, record["lagebezeichnung_freitext"], "lagebeschreibung")
		self.boolean_concept(keo, record, "befundfrei", "befundfrei", "nicht_befundfrei", warn)

		# 4 Responsibility
		for field, key in [("fachbehörde", "fachzustaendigkeit"),
						   ("genehmigungsbehörde", "genehmigungszustaendigkeit")]:
			if field in record:
				right = self.part(dataset, key)
				g.add((keo, P.P104_is_subject_to, right))
				g.add((right, RDF.type, P.E30_Right))
				g.add((right, P.P2_has_type, self.concept(key)))
				g.add((right, P.P75i_is_possessed_by, self.actor(record[field])))
		if "datenhaltende_institution" in record:
			g.add((dataset, DCTERMS.publisher, self.actor(record["datenhaltende_institution"])))

		# 5 Technical metadata and 6 comment
		if "datenhaltendes_system" in record:
			value = record["datenhaltendes_system"]
			system = URIRef(value) if URI.match(value) else self.iri("system/" + quote(value, safe=""))
			g.add((dataset, DCTERMS.source, system))
			if not URI.match(value):
				g.add((system, SKOS.prefLabel, Literal(value)))
		for field, prop in [("letzte_änderung", DCTERMS.modified),
							("datenexport", PROV.generatedAtTime),
							("datenerstellung", DCTERMS.created)]:
			if field in record:
				try:
					g.add((dataset, prop, timestamp(record[field])))
				except ValueError as error:
					warn(field, str(error))
		if "lizenz" in record:
			g.add((dataset, DCTERMS.license, self.license(record["lizenz"])))
		if "zugriffsrecht" in record:
			value = record["zugriffsrecht"]
			code = ACCESS_RIGHT_VALUES.get(re.sub(r"\s+", " ", value.lower()))
			if code is None and value.startswith(ACCESS_RIGHTS):
				code = value[len(ACCESS_RIGHTS):]
			if code in ACCESS_RIGHT_VALUES.values():
				g.add((dataset, DCTERMS.accessRights, URIRef(ACCESS_RIGHTS + code)))
			else:
				warn("zugriffsrecht", f"value not allowed: {value} (allowed: öffentlich, eingeschränkt, nicht öffentlich)")
		if "urheber" in record:
			g.add((dataset, DCTERMS.creator, self.actor(record["urheber"])))
		if "bemerkung" in record:
			self.free_text(dataset, record["bemerkung"], "bemerkung")
		return keo

	# --- partial mappings ---------------------------------------------------
	def data_link(self, keo, value, warn):
		"""Authority URIs denote the object itself (owl:sameAs as in the profile).
		Portal pages are documents about the object (P70)."""
		if not URI.match(value):
			warn("weitere_datenverknüpfung", f"not a link: {value}")
			return
		wikidata = re.match(r"^https?://(?:www\.)?wikidata\.org/(?:wiki|entity)/(Q\d+)$", value)
		if wikidata:
			self.graph.add((keo, OWL.sameAs, URIRef("http://www.wikidata.org/entity/" + wikidata.group(1))))
		elif re.match(r"^https?://d-nb\.info/gnd/\S+$", value):
			self.graph.add((keo, OWL.sameAs, URIRef(value)))
		else:
			self.graph.add((keo, CRM.P70i_is_documented_in, URIRef(value)))
			self.graph.add((URIRef(value), RDF.type, CRM.E31_Document))

	def dating(self, keo, dataset, record, warn):
		start, end = record.get("absolute_datierung_von"), record.get("absolute_datierung_bis")
		epochs = record.get("epoche", [])
		fields = ("absolute_datierung_von", "absolute_datierung_bis", "absolute_datierung_abgeleitet",
				  "epoche", "weitere_datierungsinformationen")
		if not any(f in record for f in fields):
			return
		# Epoch and dating do not say what they refer to (creation, use,
		# existence). P12 does not fix a role. A more specific reading (E63
		# with P92i, E12 with P108i) is a subproperty of it.
		period = self.part(dataset, "zeitstellung")
		g, P = self.graph, CRM
		g.add((keo, P.P12i_was_present_at, period))
		g.add((period, RDF.type, P.E5_Event))
		if start or end:
			try:
				g.add((period, P["P4_has_time-span"], Literal(dating_edtf(start, end), datatype=EDTF)))
			except ValueError as error:
				warn("absolute_datierung", str(error))
			if "absolute_datierung_abgeleitet" not in record:
				warn("absolute_datierung_abgeleitet", "MUSS field missing, as an absolute dating is given")
		if "absolute_datierung_abgeleitet" in record:
			try:
				if parse_boolean(record["absolute_datierung_abgeleitet"]):
					g.add((period, P.P2_has_type, self.concept("abgeleitet")))
			except ValueError as error:
				warn("absolute_datierung_abgeleitet", str(error))
		# One epoch contains the dated period (P10). Several epochs cannot all
		# contain it, it overlaps with each of them (P132).
		relation = P.P10_falls_within if len(epochs) == 1 else P.P132_spatiotemporally_overlaps_with
		for value in epochs:
			if URI.match(value):
				epoch = URIRef(value)
			else:
				epoch = self.iri("epoche/" + quote(value, safe=""))
				g.add((epoch, RDF.type, P.E4_Period))
				g.add((epoch, SKOS.prefLabel, self.text(value)))
			g.add((period, relation, epoch))
		if "weitere_datierungsinformationen" in record:
			self.free_text(period, record["weitere_datierungsinformationen"], "datierungsinformation")

	def geometry(self, place, dataset, record, warn):
		geometry = record.get("geometrie")
		if geometry is None:
			return
		if geometry.geom_type not in ALLOWED_GEOMETRIES or geometry.is_empty:
			warn("geometrie", f"geometry type not allowed: {geometry.geom_type}")
			return
		if "koordinatenbezugssystem" not in record:
			warn("geometrie", "not mapped without koordinatenbezugssystem")
			return
		try:
			literal = wkt_literal(geometry, record["koordinatenbezugssystem"])
		except Exception as error:
			warn("koordinatenbezugssystem", f"CRS not usable: {error}")
			return
		self.check_crs(record["koordinatenbezugssystem"], warn)
		node = self.part(dataset, "geometrie")
		self.graph.add((place, GEO.hasGeometry, node))
		self.graph.add((node, RDF.type, GEO.Geometry))
		self.graph.add((node, GEO.asWKT, literal))
		if "lagegenauigkeit" in record:
			self.graph.add((node, CRM.P2_has_type, self.value_concept(record["lagegenauigkeit"], "lagegenauigkeit")))
		for value in record.get("datenerhebungsqualität", []):
			self.graph.add((node, CRM.P2_has_type, self.value_concept(value, "datenerhebungsqualitaet")))

	def check_crs(self, crs_text, warn):
		"""GeoSPARQL systems know CRS IRIs of EPSG and OGC. For other
		authorities (such as ESRI) warn once per CRS and name the equivalent
		EPSG code if there is one. The value itself stays unchanged."""
		if crs_text in self.checked_crs:
			return
		self.checked_crs.add(crs_text)
		crs = pyproj.CRS.from_user_input(crs_text)
		authority = crs.to_authority()
		if authority and authority[0] not in ("EPSG", "OGC"):
			epsg = crs.to_authority("EPSG")
			hint = f" Equivalent: EPSG:{epsg[1]}." if epsg else ""
			warn("koordinatenbezugssystem", f"{crs_text}: GeoSPARQL systems usually know only EPSG and OGC IRIs.{hint}")

	def translocation(self, keo, place, dataset, record, warn):
		if "translozierung" not in record:
			if "transloziert_standort" in record:
				warn("transloziert_standort", "given without translozierung, ignored")
			return
		try:
			translocated = parse_boolean(record["translozierung"])
		except ValueError as error:
			warn("translozierung", str(error))
			return
		if not translocated:
			self.graph.add((keo, CRM.P2_has_type, self.concept("nicht_transloziert")))
			return
		move = self.part(dataset, "translozierung")
		self.graph.add((keo, RDF.type, CRM.E19_Physical_Object))  # P25 requires E19
		self.graph.add((keo, CRM.P25i_moved_by, move))
		self.graph.add((move, RDF.type, CRM.E9_Move))
		location = record.get("transloziert_standort", "").lower()
		if "neu" in location:
			self.graph.add((move, CRM.P26_moved_to, place))
		elif "original" in location or "ursprüng" in location:
			self.graph.add((move, CRM.P27_moved_from, place))
		elif location:
			warn("transloziert_standort", f"value not recognised: {record['transloziert_standort']}")

	def boolean_concept(self, keo, record, field, true_key, false_key, warn):
		if field not in record:
			return
		try:
			key = true_key if parse_boolean(record[field]) else false_key
		except ValueError as error:
			warn(field, str(error))
			return
		self.graph.add((keo, CRM.P2_has_type, self.concept(key)))

	def license(self, value):
		if URI.match(value):
			match = re.match(r"^https?://creativecommons\.org/(licenses/[a-z-]+/\d\.\d|publicdomain/zero/1\.0)", value)
			return URIRef(f"https://creativecommons.org/{match.group(1)}/") if match else URIRef(value)
		known = CC_LICENSES.get(re.sub(r"\s+", " ", value.strip().lower()))
		if known:
			return URIRef(known)
		node = BNode()
		self.graph.add((node, RDF.type, DCTERMS.LicenseDocument))
		self.graph.add((node, RDFS.label, self.text(value)))
		return node

	def add_vocabulary(self):
		scheme = self.iri("vocab/")
		self.graph.add((scheme, RDF.type, SKOS.ConceptScheme))
		self.graph.add((scheme, SKOS.prefLabel, self.text("Vokabular des KEO-Austauschformats")))
		for key in sorted(self.used_concepts):
			path, label = VOCABULARY[key]
			concept = self.iri("vocab/" + path)
			self.graph.add((concept, RDF.type, SKOS.Concept))
			self.graph.add((concept, SKOS.prefLabel, self.text(label)))
			self.graph.add((concept, SKOS.inScheme, scheme))


def build_graph(input_path, base_uri=str(KEO_BASE), delimiter=",", language="de"):
	"""Map the records of a CSV file. Returns (graph, record count, warnings)."""
	warn = Warnings()
	mapper = Mapper(base_uri, language, warn)
	with open(input_path, newline="", encoding="utf-8-sig") as csv_file:
		if not csv.DictReader(csv_file, delimiter=delimiter).fieldnames:
			raise ValueError("The input file is empty or has no header row.")
	records = list(read_records(input_path, delimiter, warn))
	crs = {record.get("koordinatenbezugssystem") for _, record in records} - {None}
	if len(crs) > 1:
		warn(Path(input_path).name, "koordinatenbezugssystem",
			 f"several CRS in one file ({', '.join(sorted(crs))}), part C requires one")
	for row, record in records:
		keo = mapper.map_record(record)
		add_source_fields(mapper.graph, keo, row)
	mapper.add_vocabulary()
	return mapper.graph, len(records), warn.items


def convert_csv_to_rdf(
	input_path, output_path, base_uri, rdf_format="turtle", delimiter=",", warnings=None
):
	"""Read a delimited CSV and serialize its records in the requested RDF format."""
	graph, record_count, found = build_graph(input_path, base_uri, delimiter)
	if warnings is not None:
		warnings.extend(found)
	graph.serialize(destination=str(output_path), format=rdf_format, encoding="utf-8")
	return record_count


def main():
	parser = argparse.ArgumentParser(
		description="Convert a delimited CSV file into CIDOC-CRM RDF."
	)
	parser.add_argument("input", type=Path, help="Input TSV/CSV file")
	parser.add_argument(
		"-d",
		"--delimiter",
		default=",",
		help="CSV field delimiter (default: %(default)s)",
	)
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
		default=str(KEO_BASE),
		help="Namespace for generated identifiers (default: %(default)s)",
	)
	args = parser.parse_args()
	format_extension = FORMAT_EXTENSIONS.get(args.format, args.format.rsplit("/", 1)[-1])
	output_path = args.output or args.input.with_suffix(f".{format_extension}")

	warnings = []
	try:
		record_count = convert_csv_to_rdf(
			args.input, output_path, args.base_uri, args.format, args.delimiter, warnings
		)
	except (OSError, ValueError, csv.Error) as error:
		parser.error(str(error))

	for record, field, text in warnings:
		print(f"WARNING {record} [{field}]: {text}", file=sys.stderr)
	print(f"Converted {record_count} records to {output_path}")


if __name__ == "__main__":
	main()
