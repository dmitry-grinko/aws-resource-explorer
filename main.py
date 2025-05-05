import sys
import json
import os

# --- Load data from JSON file --- START
def load_data(file_path="resources.json"):
    if not os.path.exists(file_path):
        print(f"Error: Data file '{file_path}' not found. Please generate it first.", file=sys.stderr)
        sys.exit(1)
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode data file '{file_path}'. Invalid JSON. Error: {e}", file=sys.stderr)
        sys.exit(1)
    except IOError as e:
        print(f"Error: Could not read data file '{file_path}'. Error: {e}", file=sys.stderr)
        sys.exit(1)

resource_relations = load_data()
# --- Load data from JSON file --- END

# Create a mapping for case-insensitive lookup
lowercase_map = {k.lower(): k for k in resource_relations}

def print_table(title, items, start_index):
    # This function assumes items list is not empty, check before calling.

    max_index = start_index + len(items) - 1
    index_width = max(len(str(max_index)), 1)

    item_name_width = max(len(item['name']) for item in items)
    name_width = max(item_name_width, len("Resource"))

    item_type_width = max(len(item['type']) for item in items)
    type_width = max(item_type_width, len("Type"))

    item_account_width = max(len(item['account_name']) for item in items)
    account_width = max(item_account_width, len("Account"))

    # Calculate widths based on the required structure
    inner_dash_width = index_width + name_width + type_width + account_width + 11
    inner_title_width = index_width + name_width + type_width + account_width + 9

    # Define table components using the calculated widths
    top_border = f"┌{'─' * inner_dash_width}┐"
    title_line = f"│ {title.center(inner_title_width)} │"
    header_separator = f"├{'─' * (index_width + 2)}┬{'─' * (name_width + 2)}┬{'─' * (type_width + 2)}┬{'─' * (account_width + 2)}┤"
    header_line = f"│ {'#'.center(index_width)} │ {'Resource'.center(name_width)} │ {'Type'.center(type_width)} │ {'Account'.center(account_width)} │"
    row_separator = f"├{'─' * (index_width + 2)}┼{'─' * (name_width + 2)}┼{'─' * (type_width + 2)}┼{'─' * (account_width + 2)}┤"
    bottom_border = f"└{'─' * (index_width + 2)}┴{'─' * (name_width + 2)}┴{'─' * (type_width + 2)}┴{'─' * (account_width + 2)}┘"

    print(top_border)
    print(title_line)
    print(header_separator)
    print(header_line)
    print(row_separator)

    current_index = start_index
    for i, item in enumerate(items):
        print(f"│ {str(current_index).rjust(index_width)} │ {item['name'].ljust(name_width)} │ {item['type'].ljust(type_width)} │ {item['account_name'].ljust(account_width)} │")
        if i < len(items) - 1:
            print(row_separator)
        current_index += 1
    print(bottom_border)

    print()
    return len(items)

def display_and_select_resource(resource_name):
    if resource_name not in resource_relations:
        print(f"\nError: Resource '{resource_name}' definition not found. Returning.")
        return

    resource_data = resource_relations[resource_name]
    resource_type = resource_data.get("type", "Unknown Type")
    resource_account = resource_data.get("account_name", "Unknown Account")
    invokes_list = resource_data.get("invokes", [])
    invoked_by_list = resource_data.get("invoked_by", [])

    print(f"\n--- {resource_name} --- ({resource_type} / {resource_account}) --- ")

    displayed_resources = []
    num_displayed = 0

    if invokes_list:
        num_displayed += print_table("Invokes", invokes_list, 1)
        displayed_resources.extend(invokes_list)

    if invoked_by_list:
        num_displayed += print_table("Invoked by", invoked_by_list, len(displayed_resources) + 1)
        displayed_resources.extend(invoked_by_list)

    if not displayed_resources:
        print(f"\n{resource_name} has no defined/valid relations listed to display.")
        return

    while True:
        try:
            prompt = f"Select a resource number (1-{len(displayed_resources)}) to explore, or 'q' to quit: "
            choice_str = input(prompt)

            if choice_str.lower() == 'q':
                print("Quitting program.")
                sys.exit(0)

            choice = int(choice_str)
            if 1 <= choice <= len(displayed_resources):
                selected_resource_dict = displayed_resources[choice - 1]
                selected_resource_name = selected_resource_dict['name']
                display_and_select_resource(selected_resource_name)
                return
            else:
                print(f"Invalid selection. Please enter a number between 1 and {len(displayed_resources)} or 'q'.")
        except ValueError:
            print("Invalid input. Please enter a number or 'q'.")

while True:
    start_resource_input = input("Enter an AWS resource name to start (or 'q' to quit): ")
    if start_resource_input.lower() == 'q':
        print("Exiting.")
        break

    start_resource_lower = start_resource_input.lower()
    canonical_name = lowercase_map.get(start_resource_lower)

    if canonical_name:
        display_and_select_resource(canonical_name)
        print("\nExploration finished.")
        break
    else:
        print(f"Try again, unknown resource name: '{start_resource_input}'")

print("Goodbye!")
