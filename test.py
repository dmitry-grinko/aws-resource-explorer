import json
import sys
import os

# --- Load data from JSON file --- START
def load_data(file_path="resources.json"):
    if not os.path.exists(file_path):
        print(f"Error: Data file '{file_path}' not found. Please generate it first.", file=sys.stderr)
        return None # Return None on error, let caller handle exit
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode data file '{file_path}'. Invalid JSON. Error: {e}", file=sys.stderr)
        return None
    except IOError as e:
        print(f"Error: Could not read data file '{file_path}'. Error: {e}", file=sys.stderr)
        return None
# --- Load data from JSON file --- END

def validate_resource_data(resource_relations):
    """Checks if all mentioned resources have a top-level definition."""
    defined_resources = set(resource_relations.keys())
    mentioned_resources = set()
    missing_definitions = set()
    errors_found = False

    print("Starting resource data validation...")

    # Gather all mentioned resources
    for resource_name, data in resource_relations.items():
        for item in data.get("invokes", []):
            mentioned_resources.add(item['name'])
        for item in data.get("invoked_by", []):
            mentioned_resources.add(item['name'])

    # Check if mentioned resources are defined
    for mentioned_name in mentioned_resources:
        if mentioned_name not in defined_resources:
            missing_definitions.add(mentioned_name)
            errors_found = True

    # Report results
    if errors_found:
        print("\nValidation FAILED:")
        for missing_name in sorted(list(missing_definitions)):
            print(f"  - Error: Resource '{missing_name}' is mentioned in relations but has no definition.")
            print(f"    Run the parser or manually add the definition for '{missing_name}' to resources.json.")
    else:
        print("\nValidation SUCCESSFUL: All mentioned resources have definitions.")

    return not errors_found

if __name__ == "__main__":
    # Load data first
    data = load_data()
    if data is None:
        sys.exit(1) # Exit if data loading failed
    
    # Pass data to validation function
    if validate_resource_data(data):
        pass
    else:
        sys.exit(1) 