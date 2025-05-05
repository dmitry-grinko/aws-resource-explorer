#!/bin/bash

rm -rf resources.json

python cloudformation_parser.py cfn-templates/cfn-1.yml aws-1
python cloudformation_parser.py cfn-templates/cfn-2.yml aws-2
python cloudformation_parser.py cfn-templates/cfn-3.yml aws-3
python cloudformation_parser.py cfn-templates/cfn-4.yml aws-4
python cloudformation_parser.py cfn-templates/cfn-5.yml aws-5
python cloudformation_parser.py cfn-templates/cfn-6.yml aws-1
python cloudformation_parser.py cfn-templates/cfn-7.yml aws-1




python test.py