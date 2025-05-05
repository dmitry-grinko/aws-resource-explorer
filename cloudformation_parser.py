import yaml
import json
import sys
import argparse
import os
import re
from collections import defaultdict

# --- YAML Loader Setup for CFN Tags --- START
def default_constructor(loader, tag_suffix, node):
    # Construct based on the node type (scalar, sequence, mapping)
    if isinstance(node, yaml.ScalarNode):
        # Special case for !Sub where the value might be a string or a list
        if tag_suffix == 'Sub':
             return {'Fn::Sub': loader.construct_scalar(node)}
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        # Special case for !Sub where the value might be a string or a list
        if tag_suffix == 'Sub':
            return {'Fn::Sub': loader.construct_sequence(node)}
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    else:
        raise yaml.constructor.ConstructorError(
            None, None, f"unexpected node type {node.__class__} for tag {tag_suffix}", node.start_mark)

yaml.add_multi_constructor('!', default_constructor, Loader=yaml.SafeLoader)
# --- YAML Loader Setup for CFN Tags --- END

# --- Resource Type Mapping ---
CFN_TYPE_MAP = {
    "AWS::Lambda::Function": "Lambda Function",
    "AWS::DynamoDB::Table": "DynamoDB Table",
    "AWS::SQS::Queue": "SQS Queue",
    "AWS::ApiGateway::RestApi": "API Gateway",
    "AWS::ApiGateway::Resource": "API Gateway Resource",
    "AWS::ApiGateway::Method": "API Gateway Method",
    "AWS::ApiGateway::Deployment": "API Gateway Deployment",
    "AWS::S3::Bucket": "S3 Bucket",
    "AWS::IAM::Role": "IAM Role",
    "AWS::IAM::Policy": "IAM Policy",
    "AWS::Events::Rule": "EventBridge Rule",
    "AWS::Events::EventBus": "EventBridge Bus",
    "AWS::StepFunctions::StateMachine": "Step Function",
    "AWS::Lambda::EventSourceMapping": "Lambda Event Source Mapping",
    "AWS::RDS::DBInstance": "RDS DB Instance",
    "AWS::EC2::SecurityGroup": "Security Group",
    "AWS::AppSync::GraphQLApi": "AppSync API",
    "AWS::AppSync::DataSource": "AppSync DataSource",
    "AWS::AppSync::Resolver": "AppSync Resolver",
    "AWS::AppSync::GraphQLSchema": "AppSync Schema",
    "AWS::AppSync::ApiKey": "AppSync ApiKey",
    "AWS::Lambda::Permission": "Lambda Permission",
    # Add more mappings as needed
}

# --- Helper Function to Extract References --- START
def find_logical_ids(data, defined_logical_ids):
    """Recursively finds potential Logical IDs referenced within data structures."""
    refs = set()
    if isinstance(data, dict):
        # Check for CloudFormation functions like !Ref, !GetAtt, !Sub
        if 'Ref' in data and isinstance(data['Ref'], str) and data['Ref'] in defined_logical_ids:
            refs.add(data['Ref'])
        elif 'Fn::GetAtt' in data and isinstance(data['Fn::GetAtt'], list) and len(data['Fn::GetAtt']) > 0 and data['Fn::GetAtt'][0] in defined_logical_ids:
            refs.add(data['Fn::GetAtt'][0])
        elif 'Fn::Sub' in data:
            sub_input = data['Fn::Sub']
            sub_string = sub_input if isinstance(sub_input, str) else sub_input[0]
            found_refs = re.findall(r'\${([a-zA-Z0-9]+)(?:\.[a-zA-Z0-9]+)?}', sub_string)
            for ref_id in found_refs:
                if ref_id in defined_logical_ids:
                    refs.add(ref_id)
        else:
            for key, value in data.items():
                refs.update(find_logical_ids(value, defined_logical_ids))
    elif isinstance(data, list):
        for item in data:
            refs.update(find_logical_ids(item, defined_logical_ids))
    elif isinstance(data, str):
        # NEW: Explicitly check for patterns like "LogicalId.Arn" resulting from !GetAtt
        # This pattern is common in IAM Policy Resource fields after YAML loading
        if '.' in data:
            potential_id = data.split('.')[0]
            if potential_id in defined_logical_ids:
                # print(f"DEBUG: Found potential GetAtt ref: {potential_id} in string {data}")
                refs.add(potential_id)
        # Keep the basic check for ${LogicalId} from !Sub strings
        found_refs = re.findall(r'\${([a-zA-Z0-9]+)(?:\.[a-zA-Z0-9]+)?}', data)
        for ref_id in found_refs:
            if ref_id in defined_logical_ids:
                # print(f"DEBUG: Found Sub ref: {ref_id} in string {data}")
                refs.add(ref_id)
        # Check for simple !Ref (less common but possible after loading)
        if data in defined_logical_ids:
             # print(f"DEBUG: Found direct Ref?: {data}")
             refs.add(data)

    return refs
# --- Helper Function to Extract References --- END

def parse_cloudformation(template_path, account_name):
    """Parses a CFN template and generates the resource relations structure."""
    try:
        with open(template_path, 'r') as f:
            template = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Template file not found at '{template_path}'", file=sys.stderr)
        return None # Return None instead of exiting
    except yaml.YAMLError as e:
        print(f"Error parsing YAML template: {e}", file=sys.stderr)
        return None
    except Exception as e:
         print(f"An unexpected error occurred during YAML parsing: {e}", file=sys.stderr)
         return None

    if 'Resources' not in template:
        print("Error: Template does not contain a 'Resources' section.", file=sys.stderr)
        return None

    resources = template['Resources']
    defined_logical_ids = set(resources.keys())
    parsed_relations = defaultdict(lambda: {"invokes": set(), "invoked_by": set()})

    # First pass: Initialize basic info and identify potential invocations
    print("Parsing resources and identifying potential invocations...")
    for logical_id, resource_details in resources.items():
        cfn_type = resource_details.get('Type')
        display_type = CFN_TYPE_MAP.get(cfn_type, cfn_type)

        parsed_relations[logical_id]['type'] = display_type
        parsed_relations[logical_id]['account_name'] = account_name

        properties = resource_details.get('Properties', {})

        # --- Infer 'invokes' and direct 'invoked_by' --- 
        invoked_targets = find_logical_ids(properties, defined_logical_ids)

        # Refine relationships based on resource type
        if cfn_type == "AWS::Lambda::Function":
            # Env vars often mean Lambda -> Target
            env_vars = properties.get('Environment', {}).get('Variables', {})
            refs_in_env = find_logical_ids(env_vars, defined_logical_ids)
            for ref_id in refs_in_env:
                print(f"  {logical_id} (Lambda Env) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)
            
            # NEW: Check Role for lambda:InvokeFunction permissions
            role_ref = properties.get('Role')
            role_ids = find_logical_ids(role_ref, defined_logical_ids)
            if role_ids:
                role_logical_id = list(role_ids)[0] # Assuming one role
                if role_logical_id in resources and resources[role_logical_id].get('Type') == "AWS::IAM::Role":
                     role_props = resources[role_logical_id].get('Properties', {})
                     policies = role_props.get('Policies', [])
                     for policy in policies:
                         statements = policy.get('PolicyDocument', {}).get("Statement", [])
                         for statement in statements:
                             # Ensure Action is treated as a list/set for checking
                             action = statement.get('Action', [])
                             if not isinstance(action, list): action = [action]
                             
                             if statement.get('Effect') == 'Allow' and 'lambda:InvokeFunction' in action:
                                 policy_resources = statement.get('Resource', [])
                                 if not isinstance(policy_resources, list): policy_resources = [policy_resources]
                                 
                                 # Use the improved find_logical_ids here
                                 refs_in_policy_res = find_logical_ids(policy_resources, defined_logical_ids)
                                 
                                 for target_lambda_id in refs_in_policy_res:
                                     if target_lambda_id in resources and resources[target_lambda_id].get('Type') == "AWS::Lambda::Function":
                                         print(f"  {logical_id} (Lambda via Role Invoke) -> {target_lambda_id}")
                                         parsed_relations[logical_id]['invokes'].add(target_lambda_id)

        elif cfn_type == "AWS::ApiGateway::Method":
            # Integration Uri likely means API GW Method -> Target (usually Lambda)
            integration = properties.get('Integration', {})
            refs_in_uri = find_logical_ids(integration.get('Uri'), defined_logical_ids)
            for ref_id in refs_in_uri:
                # Assume Method invokes target
                print(f"  {logical_id} (API Method) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)
                # Also infer RestApi invokes target
                api_ref = properties.get('RestApiId')
                api_id = find_logical_ids(api_ref, defined_logical_ids)
                if api_id:
                    api_logical_id = list(api_id)[0]
                    print(f"  {api_logical_id} (API Gateway) -> {ref_id}")
                    parsed_relations[api_logical_id]['invokes'].add(ref_id)

        elif cfn_type == "AWS::StepFunctions::StateMachine":
            # Look for lambdas invoked in DefinitionString or via Role Policy
            role_ref = properties.get('RoleArn')
            role_id = find_logical_ids(role_ref, defined_logical_ids)
            if role_id:
                role_logical_id = list(role_id)[0]
                if role_logical_id in resources and resources[role_logical_id].get('Type') == "AWS::IAM::Role":
                     role_props = resources[role_logical_id].get('Properties', {})
                     refs_in_policy = find_logical_ids(role_props.get('Policies', {}), defined_logical_ids)
                     for ref_id in refs_in_policy:
                         if ref_id in resources and resources[ref_id].get('Type') == "AWS::Lambda::Function":
                             print(f"  {logical_id} (Step Function via Role) -> {ref_id}")
                             parsed_relations[logical_id]['invokes'].add(ref_id)
            # TODO: Add basic DefinitionString parsing for lambda:invoke ARNs

        elif cfn_type == "AWS::Events::Rule":
            # Target Arn means Rule -> Target
            targets = properties.get('Targets', [])
            for target in targets:
                refs_in_target = find_logical_ids(target.get('Arn'), defined_logical_ids)
                for ref_id in refs_in_target:
                    print(f"  {logical_id} (Event Rule) -> {ref_id}")
                    parsed_relations[logical_id]['invokes'].add(ref_id)

        elif cfn_type == "AWS::Lambda::EventSourceMapping":
            # Links FunctionName (Lambda) and EventSourceArn (SQS, etc.)
            func_ref = properties.get('FunctionName')
            source_ref = properties.get('EventSourceArn')
            func_ids = find_logical_ids(func_ref, defined_logical_ids)
            source_ids = find_logical_ids(source_ref, defined_logical_ids)
            if func_ids and source_ids:
                func_id = list(func_ids)[0]
                source_id = list(source_ids)[0]
                # Source invokes the Lambda
                print(f"  {source_id} (Event Source) -> {func_id}")
                parsed_relations[source_id]['invokes'].add(func_id)
                # The mapping resource itself doesn't really invoke/get invoked in our model

        elif cfn_type == "AWS::AppSync::DataSource":
            # Links AppSync API to Lambda or DDB
            lambda_conf = properties.get('LambdaConfig', {})
            ddb_conf = properties.get('DynamoDBConfig', {})
            refs_in_ds = find_logical_ids(lambda_conf.get('LambdaFunctionArn'), defined_logical_ids)
            refs_in_ds.update(find_logical_ids(ddb_conf.get('TableName'), defined_logical_ids))
            for ref_id in refs_in_ds:
                print(f"  {logical_id} (AppSync DS) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)

        elif cfn_type == "AWS::AppSync::Resolver":
             # Links Resolver to a DataSource
             ds_ref = properties.get('DataSourceName')
             # Usually DataSourceName is a string, not a Ref, find it by matching Name property
             ds_logical_id = None
             for res_id, res_data in resources.items():
                 if res_data.get('Type') == "AWS::AppSync::DataSource" and res_data.get('Properties', {}).get('Name') == ds_ref:
                     ds_logical_id = res_id
                     break
             if ds_logical_id:
                 print(f"  {logical_id} (AppSync Resolver) -> {ds_logical_id}")
                 parsed_relations[logical_id]['invokes'].add(ds_logical_id)

        # Catch-all for other general property references (might be less accurate)
        # for ref_id in invoked_targets:
        #     if ref_id not in parsed_relations[logical_id]['invokes']:
        #        # Avoid adding self-references or references already caught by specific logic
        #        if ref_id != logical_id: 
        #             # print(f"  WARN: General reference found: {logical_id} -> {ref_id}")
        #             # parsed_relations[logical_id]['invokes'].add(ref_id)
        #             pass # Disable general references for now to reduce noise

    # Second pass: Populate details and build reciprocal invoked_by
    print("Populating details and building reciprocal relationships...")
    final_relations = {}
    for logical_id, data in parsed_relations.items():
        # Convert sets to lists for output, populate details
        final_invokes = []
        for target_name in sorted(list(data['invokes'])):
             if target_name in parsed_relations:
                 target_data = parsed_relations[target_name]
                 final_invokes.append({
                     "name": target_name,
                     "type": target_data['type'],
                     "account_name": target_data['account_name']
                 })
                 # Add reciprocal invoked_by relationship
                 parsed_relations[target_name]['invoked_by'].add(logical_id)
             else:
                 print(f"  Warning: Resource '{target_name}' invoked by '{logical_id}' not found in parsed definitions.")

        final_relations[logical_id] = {
            "type": data['type'],
            "account_name": data['account_name'],
            "invokes": final_invokes,
            "invoked_by": [] # Placeholder, will be populated next
        }

    # Populate final invoked_by lists with details
    for logical_id, data in final_relations.items():
         final_invoked_by = []
         # Access the sets built in the previous loop
         for invoker_name in sorted(list(parsed_relations[logical_id]['invoked_by'])):
              if invoker_name in final_relations: # Check if invoker exists in final list
                   invoker_data = final_relations[invoker_name]
                   final_invoked_by.append({
                       "name": invoker_name,
                       "type": invoker_data['type'],
                       "account_name": invoker_data['account_name']
                   })
         final_relations[logical_id]['invoked_by'] = final_invoked_by

    print(f"Parsing complete. Processed {len(final_relations)} resources.")
    return final_relations

def write_resources_file(relations, output_path="resources.py"):
    """Writes the relations dictionary to the specified Python file."""
    print(f"Writing data to {output_path}...")
    try:
        with open(output_path, 'w') as f:
            f.write("# Automatically generated by cloudformation_parser.py\n")
            f.write("# Data structure: Resource -> {type, account_name, invokes: [{name, type, account_name}], invoked_by: [{name, type, account_name}]}\n")
            f.write("resource_relations = ")
            # Use json dump for pretty printing the dictionary
            json.dump(relations, f, indent=4)
            f.write("\n")
        print("Successfully updated resources.py.")
    except IOError as e:
        print(f"Error writing to file {output_path}: {e}", file=sys.stderr)
        sys.exit(1)

# --- Read/Write JSON Data File --- START
def load_existing_data(data_file_path):
    """Loads existing data from the JSON file, returns empty dict if not found/invalid."""
    if not os.path.exists(data_file_path):
        return {}
    try:
        with open(data_file_path, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Warning: Could not decode existing data file {data_file_path}. Starting fresh. Error: {e}", file=sys.stderr)
        return {}
    except IOError as e:
        print(f"Warning: Could not read existing data file {data_file_path}. Starting fresh. Error: {e}", file=sys.stderr)
        return {}

def write_data_file(relations, output_path="resources.json"):
    """Writes the relations dictionary to the specified JSON file."""
    print(f"Writing combined data to {output_path}...")
    try:
        with open(output_path, 'w') as f:
            json.dump(relations, f, indent=4)
        print(f"Successfully wrote data to {output_path}.")
    except IOError as e:
        print(f"Error writing to file {output_path}: {e}", file=sys.stderr)
        # Don't exit, just report error
# --- Read/Write JSON Data File --- END

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse CloudFormation templates and update a JSON resource relationship data file. "
                    "Provide template files and account names as pairs."
    )
    parser.add_argument(
        "template_account_pairs",
        metavar="FILE ACCOUNT_NAME",
        nargs='+', # Require at least one pair
        help="Pairs of CloudFormation template file paths and the corresponding AWS Account Name."
    )
    parser.add_argument("-o", "--output", default="resources.json",
                        help="Path to the output/update JSON data file (default: resources.json)")

    args = parser.parse_args()

    if len(args.template_account_pairs) % 2 != 0:
        parser.error("Arguments must be provided in pairs of <template_file> <account_name>.")
        sys.exit(1)

    output_file = args.output
    # Load existing data first
    all_relations_data = load_existing_data(output_file)
    print(f"Loaded {len(all_relations_data)} existing resources from {output_file}")

    print(f"Processing {len(args.template_account_pairs) // 2} template(s) from command line...")

    new_data_parsed = False
    for i in range(0, len(args.template_account_pairs), 2):
        template_file = args.template_account_pairs[i]
        account_name = args.template_account_pairs[i+1]
        
        print(f"\n--- Parsing: {template_file} (Account: {account_name}) ---")
        relations_data = parse_cloudformation(template_file, account_name)
        if relations_data:
            # Merge results - new data overwrites/updates existing keys
            print(f"Merging data from {template_file}...")
            all_relations_data.update(relations_data)
            new_data_parsed = True
        else:
            print(f"Warning: No resource data generated from {template_file}. Skipping merge.", file=sys.stderr)

    # Write the combined data at the end only if new data was parsed
    if new_data_parsed:
        write_data_file(all_relations_data, output_file)
    else:
        print("No new data parsed from provided templates. Output file not modified.")
        if not all_relations_data:
             sys.exit(1) # Exit with error if no data exists at all 