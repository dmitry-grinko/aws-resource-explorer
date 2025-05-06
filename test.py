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
    """Checks if all mentioned resources have definitions and if relationships are reciprocal."""
    defined_resources = set(resource_relations.keys())
    mentioned_resources = set()
    missing_definitions = set()
    reciprocity_errors = [] # List to store reciprocity error messages
    errors_found = False

    print("Starting resource data validation...")

    # 1. Gather all mentioned resources and check for definitions
    print("Checking for missing resource definitions...")
    for resource_name, data in resource_relations.items():
        for item in data.get("invokes", []):
            # Ensure 'name' key exists before adding
            if 'name' in item:
                 mentioned_resources.add(item['name'])
            else:
                 print(f"  - Warning: Entry in 'invokes' list of '{resource_name}' is missing 'name' key.")
                 errors_found = True # Treat malformed entry as an error
        for item in data.get("invoked_by", []):
             if 'name' in item:
                 mentioned_resources.add(item['name'])
             else:
                 print(f"  - Warning: Entry in 'invoked_by' list of '{resource_name}' is missing 'name' key.")
                 errors_found = True # Treat malformed entry as an error

    for mentioned_name in mentioned_resources:
        if mentioned_name not in defined_resources:
            missing_definitions.add(mentioned_name)
            errors_found = True

    if missing_definitions:
        print("\nDefinition Errors Found:")
        for missing_name in sorted(list(missing_definitions)):
            print(f"  - Error: Resource '{missing_name}' is mentioned but has no definition.")
    else:
         print("Definition check passed.")

    # 2. Check for reciprocal relationships
    print("\nChecking for reciprocal relationships...")
    for source_name, source_data in resource_relations.items():
        # Check invokes list
        for target_info in source_data.get("invokes", []):
            target_name = target_info.get('name')
            if not target_name:
                 continue # Skip if name is missing (already warned)

            # Check if target exists (skip if definition is missing - handled above)
            if target_name not in defined_resources:
                continue

            target_data = resource_relations[target_name]
            # Check if source_name is in target's invoked_by list
            found_invoked_by = any(invoker.get('name') == source_name for invoker in target_data.get("invoked_by", []))
            if not found_invoked_by:
                errors_found = True
                error_msg = f"  - Reciprocity Error: '{source_name}' invokes '{target_name}', but '{target_name}' does not list '{source_name}' in invoked_by."
                reciprocity_errors.append(error_msg)

        # Check invoked_by list
        for invoker_info in source_data.get("invoked_by", []):
            invoker_name = invoker_info.get('name')
            if not invoker_name:
                continue # Skip if name is missing (already warned)

            # Check if invoker exists (skip if definition is missing - handled above)
            if invoker_name not in defined_resources:
                 continue

            invoker_data = resource_relations[invoker_name]
            # Check if source_name is in invoker's invokes list
            found_invokes = any(target.get('name') == source_name for target in invoker_data.get("invokes", []))
            if not found_invokes:
                errors_found = True
                error_msg = f"  - Reciprocity Error: '{source_name}' is invoked_by '{invoker_name}', but '{invoker_name}' does not list '{source_name}' in invokes."
                reciprocity_errors.append(error_msg)

    if reciprocity_errors:
        print("\nReciprocity Errors Found:")
        for error in sorted(reciprocity_errors):
            print(error)
    else:
        print("Reciprocity check passed.")


    # Final Report
    if errors_found:
        print("\nValidation FAILED.")
    else:
        print("\nValidation SUCCESSFUL: All checks passed.")

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