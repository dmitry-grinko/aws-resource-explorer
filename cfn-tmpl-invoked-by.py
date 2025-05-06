# cfn-tmpl-invoked-by.py

import json
import os
import sys
import argparse
from collections import defaultdict

def load_data(filepath):
    """Loads the resource data from the JSON file."""
    if not os.path.exists(filepath):
        print(f"Error: Input file not found at '{filepath}'", file=sys.stderr)
        sys.exit(1)
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON data file {filepath}. Error: {e}", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error: Could not read data file {filepath}. Error: {e}", file=sys.stderr)
        sys.exit(1)

def calculate_invoked_by(data):
    """Calculates the invoked_by list for each resource based on invokes lists."""
    print("Calculating invoked_by relationships...")
    # Ensure every resource has an 'invoked_by' list initialized
    for logical_id in data:
        data[logical_id]['invoked_by'] = []

    # Iterate through all resources to find who invokes whom
    for invoker_id, invoker_data in data.items():
        invoker_type = invoker_data.get('type', 'Unknown')
        invoker_account = invoker_data.get('account_name', 'Unknown')

        for target_info in invoker_data.get('invokes', []):
            target_id = target_info.get('name')
            if not target_id:
                print(f"Warning: Found invoke entry with no name for invoker '{invoker_id}'. Skipping.", file=sys.stderr)
                continue

            if target_id in data:
                # Add the invoker to the target's invoked_by list
                target_resource = data[target_id]
                invoker_details = {
                    "name": invoker_id,
                    "type": invoker_type,
                    "account_name": invoker_account
                }
                # Avoid adding duplicates if script runs multiple times on same input
                if invoker_details not in target_resource['invoked_by']:
                    target_resource['invoked_by'].append(invoker_details)
            else:
                # This case means the parser found an 'invokes' relationship
                # pointing to a resource not defined in any parsed template.
                print(f"Warning: Resource '{invoker_id}' invokes '{target_id}', but '{target_id}' was not found in the combined resource data.", file=sys.stderr)

    # Sort the invoked_by lists for consistency
    for logical_id in data:
        data[logical_id]['invoked_by'].sort(key=lambda x: x['name'])

    print("Finished calculating invoked_by relationships.")
    return data

def write_data(data, filepath):
    """Writes the updated resource data (including invoked_by) back to the JSON file."""
    print(f"Writing updated data (including invoked_by) to {filepath}...")
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
        print(f"Successfully wrote updated data to {filepath}.")
    except IOError as e:
        print(f"Error writing updated data to file {filepath}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reads resource data JSON, calculates invoked_by relationships, and writes updated JSON."
    )
    parser.add_argument(
        "data_file",
        nargs='?', # Make the argument optional
        default="resources.json", # Default to resources.json
        help="Path to the input/output JSON data file (default: resources.json)"
    )

    args = parser.parse_args()
    data_file_path = args.data_file

    # Load data
    resource_data = load_data(data_file_path)

    # Calculate invoked_by
    updated_data = calculate_invoked_by(resource_data)

    # Write updated data
    write_data(updated_data, data_file_path)
