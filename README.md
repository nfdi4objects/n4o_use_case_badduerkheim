# n4o_use_case_badduerkheim
Data and Software for the AG "Use case Bad Dürkheim"

## Convert TSV to CIDOC-CRM RDF

`csv2rdf.py` converts a tab-separated UTF-8 CSV file into RDF serialized as
Turtle. It uses RDFLib to create the RDF graph.

Install the dependency:

```sh
python3 -m pip install -r requirements.txt
```

Convert the sample data:

```sh
python3 csv2rdf.py data/Kulturerbeobjekte_Knowledge_Graph.csv
```

By default, the output is written beside the input file with a `.ttl` extension.
Choose a different output path and the namespace for generated site identifiers
with:

```sh
python3 csv2rdf.py input.tsv --output output.ttl \
	--base-uri https://data.example.org/kulturerbe/site/
```

By default, site identifiers use the `keo_site:` namespace, mapped to
`https://example.org/kulturerbe/site/`.

Each CSV record becomes a `crm:E27_Site`. Names and identifiers are represented
as CRM appellations/identifiers, descriptions as `crm:P3_has_note`, types and
epochs as `crm:P2_has_type`, and dating bounds as a `crm:E52_Time-Span`.
WKT geometries are attached using GeoSPARQL; the sample's `EPSG:25832` CRS is
included in each WKT literal. All non-empty CSV fields are also retained as
literal properties in the `keo:` source-data namespace.
