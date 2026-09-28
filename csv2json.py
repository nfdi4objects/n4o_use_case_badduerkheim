# Import modules for reading CSV files, accessing command-line arguments,
# and generating JSON output.
import csv, sys, json

objects = []

# Read the file name from the first command-line argument and open the file.
# newline='' helps prevent issues when processing line endings.
with open(sys.argv[1], newline='') as csvfile:
    # Read the file as a tab-separated table. 
    reader = csv.DictReader(csvfile, delimiter='\t')
    objects = list(reader)
    #print(reader.fieldnames)
print(json.dumps(objects,indent=3))
