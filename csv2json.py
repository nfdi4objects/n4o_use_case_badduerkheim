# Import modules for reading CSV files, accessing command-line arguments,
# and generating JSON output.
import csv, sys, json

from keo_standard import BOOLEAN_FIELDS, FIELDS, parse_boolean, split_list

objects = []

# Read the file name from the first command-line argument and open the file.
# newline='' helps prevent issues when processing line endings.
with open(sys.argv[1], newline='', encoding='utf-8-sig') as csvfile:
    # Read the file as a comma-separated table, as part C of the KEO standard requires. 
    reader = csv.DictReader(csvfile, delimiter=',')
    if reader.fieldnames and len(reader.fieldnames) == 1 and any(c in reader.fieldnames[0] for c in '\t;'):
        sys.exit(f"{sys.argv[1]}: columns are not separated by commas, as part C of the KEO standard requires")
    objects = list(reader)
    #print(reader.fieldnames)

# Repeatable fields become JSON arrays, because part C requires the list type
# of the format. Booleans become true or false.
for record in objects:
    for field, value in record.items():
        if field is None or value is None:
            continue
        if FIELDS.get(field):
            record[field] = split_list(value)
        elif field in BOOLEAN_FIELDS and value.strip():
            try:
                record[field] = parse_boolean(value)
            except ValueError as error:
                print(f"WARNING {field}: {error}, kept as text", file=sys.stderr)
print(json.dumps(objects,indent=3))
