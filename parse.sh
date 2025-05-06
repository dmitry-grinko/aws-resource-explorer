#!/bin/bash

rm -f resources.json

echo "Parsing CloudFormation templates..."
python cfn-tmpl-invokes.py cfn-templates/cfn-tmpl-1.yml aws-1
python cfn-tmpl-invokes.py cfn-templates/cfn-tmpl-2.yml aws-2

if [ ! -f resources.json ]; then
    echo "Error: resources.json not found after parsing. Aborting."
    exit 1
fi

echo "Calculating invoked_by relationships..."
python cfn-tmpl-invoked-by.py resources.json


python test.py

echo "Processing complete."
