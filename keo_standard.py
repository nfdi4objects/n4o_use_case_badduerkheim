"""Definitions of the community standard for cultural heritage objects (KEO),
version 1.1, shared by csv2rdf.py and csv2json.py.

Part B of the standard defines the fields, part C the file formats. A CSV file
uses commas as delimiter, UTF-8 and the field names as header row. Repeatable
fields separate their values with " | ".
"""

import csv
import unicodedata

# Field name -> repeatable
FIELDS = {
	"pid": False,
	"interne_id": False,
	"weitere_datenverknüpfung": True,
	"keo_bezeichnung": False,
	"beschreibung": False,
	"erweiterte_beschreibung": False,
	"typ": True,
	"absolute_datierung_von": False,
	"absolute_datierung_bis": False,
	"absolute_datierung_abgeleitet": False,
	"epoche": True,
	"weitere_datierungsinformationen": False,
	"literatur": True,
	"obertägige_sichtbarkeit": False,
	"vorschaubild": False,
	"verweise": True,
	"geometrie": False,
	"koordinatenbezugssystem": False,
	"lagegenauigkeit": False,
	"datenerhebungsqualität": True,
	"translozierung": False,
	"transloziert_standort": False,
	"lagebezeichnung_adresse": False,
	"lagebezeichnung_ags": False,
	"lagebezeichnung_geonames": False,
	"lagebezeichnung_freitext": False,
	"befundfrei": False,
	"fachbehörde": False,
	"genehmigungsbehörde": False,
	"datenhaltende_institution": False,
	"datenhaltendes_system": False,
	"letzte_änderung": False,
	"datenexport": False,
	"datenerstellung": False,
	"lizenz": False,
	"zugriffsrecht": False,
	"urheber": False,
	"bemerkung": False,
}

# MUSS fields. The meta concept "datierung" (absolute dating or epoch) and
# absolute_datierung_abgeleitet (required once an absolute dating is given)
# are checked separately.
REQUIRED = [
	"pid", "interne_id", "typ", "geometrie", "koordinatenbezugssystem", "fachbehörde",
	"datenhaltende_institution", "letzte_änderung", "datenexport",
]

BOOLEAN_FIELDS = ["absolute_datierung_abgeleitet", "obertägige_sichtbarkeit", "translozierung", "befundfrei"]

LIST_SEPARATOR = " | "


def nfc(text):
	"""Unicode NFC form without surrounding whitespace."""
	return unicodedata.normalize("NFC", text).strip()


def split_list(value):
	"""Split a repeatable field of a format without list type (part C, section 2)."""
	return [nfc(part) for part in str(value).split("|") if nfc(part)]


def parse_boolean(value):
	"""Return True or False. Part B allows only true and false."""
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)) and value in (0, 1):
		return bool(value)  # GeoPackage stores BOOLEAN as 0 and 1
	text = str(value).strip().lower()
	if text in ("true", "1"):
		return True
	if text in ("false", "0"):
		return False
	raise ValueError(f"not a boolean: {value!r} (allowed: true, false)")


class DelimiterError(ValueError):
	"""The CSV file is not comma separated as required by part C."""


def read_csv_rows(path, delimiter=","):
	"""Yield (line number, row dict) of a CSV file.

	Part C requires commas. With the default delimiter, tab or semicolon
	separated files raise DelimiterError. Values beyond the header are
	reported with the key None in the row.
	"""
	with open(path, encoding="utf-8-sig", newline="") as csv_file:
		reader = csv.DictReader(csv_file, delimiter=delimiter)
		header = reader.fieldnames or []
		if delimiter == "," and len(header) == 1 and any(char in header[0] for char in "\t;"):
			name = "tabs" if "\t" in header[0] else "semicolons"
			raise DelimiterError(f"{path}: columns are separated by {name}, part C of the standard requires commas")
		for line_number, row in enumerate(reader, start=2):
			yield line_number, row
