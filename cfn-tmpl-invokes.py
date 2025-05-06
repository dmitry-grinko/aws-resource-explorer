# cfn-tmpl-invokes.py

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
    # "AWS::Lambda::Function": "Lambda Function",
    # "AWS::Serverless::Function": "Lambda Function (SAM)",
    # "AWS::DynamoDB::Table": "DynamoDB Table",
    # "AWS::SQS::Queue": "SQS Queue",
    # "AWS::ApiGateway::RestApi": "API Gateway",
    # "AWS::ApiGateway::Resource": "API Gateway Resource",
    # "AWS::ApiGateway::Method": "API Gateway Method",
    # "AWS::ApiGateway::Deployment": "API Gateway Deployment",
    # "AWS::S3::Bucket": "S3 Bucket",
    # "AWS::IAM::Role": "IAM Role",
    # "AWS::IAM::Policy": "IAM Policy",
    # "AWS::Events::Rule": "EventBridge Rule",
    # "AWS::Events::EventBus": "EventBridge Bus",
    # "AWS::StepFunctions::StateMachine": "Step Function",
    # "AWS::Lambda::EventSourceMapping": "Lambda Event Source Mapping",
    # "AWS::RDS::DBInstance": "RDS DB Instance",
    # "AWS::EC2::SecurityGroup": "Security Group",
    # "AWS::AppSync::GraphQLApi": "AppSync API",
    # "AWS::AppSync::DataSource": "AppSync DataSource",
    # "AWS::AppSync::Resolver": "AppSync Resolver",
    # "AWS::AppSync::GraphQLSchema": "AppSync Schema",
    # "AWS::AppSync::ApiKey": "AppSync ApiKey",
    # "AWS::Lambda::Permission": "Lambda Permission",
    # Add more mappings as needed

    # Add pseudo-types for external services
    "AWS::Service::S3": "S3 Service",
    "AWS::Service::EventBridge": "EventBridge Service",
    "AWS::Service::APIGateway": "API Gateway Service",
    "AWS::Service::SQS": "SQS Service", # If SQS is identified as external principal
}

# Map service principals to pseudo-resource IDs and types
SERVICE_PRINCIPAL_MAP = {
    's3.amazonaws.com': {'id': 'S3', 'type': 'AWS::Service::S3'},
    'events.amazonaws.com': {'id': 'EventBridge', 'type': 'AWS::Service::EventBridge'},
    'apigateway.amazonaws.com': {'id': 'APIGateway', 'type': 'AWS::Service::APIGateway'},
    'sqs.amazonaws.com': {'id': 'SQS', 'type': 'AWS::Service::SQS'},
    # Add other service principals as needed
}


# --- Helper Function to Extract References --- START
def find_logical_ids(data, defined_logical_ids):
    """Recursively finds potential Logical IDs referenced within data structures."""
    refs = set()
    # Allow service IDs (like 'S3') to be considered "defined" for reference finding
    # This helps if !Ref S3 somehow exists, though unlikely for service pseudo-resources
    all_ids = defined_logical_ids.union(set(SERVICE_PRINCIPAL_MAP.get(p, {}).get('id') for p in SERVICE_PRINCIPAL_MAP))

    if isinstance(data, dict):
        # Check for CloudFormation functions like !Ref, !GetAtt, !Sub
        if 'Ref' in data and isinstance(data['Ref'], str) and data['Ref'] in all_ids:
            refs.add(data['Ref'])
        elif 'Fn::GetAtt' in data and isinstance(data['Fn::GetAtt'], list) and len(data['Fn::GetAtt']) > 0 and data['Fn::GetAtt'][0] in all_ids:
            # Only add if the base resource ID is known
            refs.add(data['Fn::GetAtt'][0])
        elif 'Fn::Sub' in data:
            sub_input = data['Fn::Sub']
            sub_string = sub_input if isinstance(sub_input, str) else sub_input[0]
            # Find potential IDs within the ${...} syntax
            found_refs = re.findall(r'\${([a-zA-Z0-9]+)(?:\.[a-zA-Z0-9]+)?}', sub_string)
            for ref_id in found_refs:
                if ref_id in all_ids:
                    refs.add(ref_id)
            # Also check for direct references if sub_string itself is an ID (less common)
            if isinstance(sub_input, str) and sub_input in all_ids:
                 refs.add(sub_input)

        else:
            # Recursively check dictionary values
            for key, value in data.items():
                refs.update(find_logical_ids(value, defined_logical_ids)) # Pass original defined_logical_ids down
    elif isinstance(data, list):
        # Recursively check list items
        for item in data:
            refs.update(find_logical_ids(item, defined_logical_ids)) # Pass original defined_logical_ids down
    elif isinstance(data, str):
        # Check for patterns like "LogicalId.Arn" resulting from !GetAtt after YAML load
        if '.' in data:
            potential_id = data.split('.')[0]
            if potential_id in all_ids:
                refs.add(potential_id)
        # Check for ${LogicalId} patterns within strings
        found_refs = re.findall(r'\${([a-zA-Z0-9]+)(?:\.[a-zA-Z0-9]+)?}', data)
        for ref_id in found_refs:
            if ref_id in all_ids:
                refs.add(ref_id)
        # Check if the string itself is a direct reference
        if data in all_ids:
             refs.add(data)

    # Filter out any service pseudo-IDs found if they weren't originally defined resources
    # We only care about references *to* defined resources within properties.
    # Service pseudo-resources invoke others, but aren't typically referenced *by* others.
    return refs.intersection(defined_logical_ids)

# --- Helper Function to Extract References --- END

def parse_cloudformation(template_path, account_name):
    """Parses a CFN template and generates the resource relations structure (invokes only)."""
    try:
        with open(template_path, 'r') as f:
            template = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Template file not found at '{template_path}'", file=sys.stderr)
        return None
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
    # Initialize structure - REMOVED invoked_by_external
    parsed_relations = defaultdict(lambda: {"invokes": set()})

    # First pass: Collect basic info and potential relationships
    print("Parsing resources and identifying potential invocations...")
    for logical_id, resource_details in resources.items():
        cfn_type = resource_details.get('Type')
        properties = resource_details.get('Properties', {})

        # Store basic type and account info temporarily
        parsed_relations[logical_id]['_original_type'] = cfn_type
        parsed_relations[logical_id]['account_name'] = account_name

        # --- Logic to identify 'invokes' relationships based on type ---
        if cfn_type == "AWS::Lambda::Function" or cfn_type == "AWS::Serverless::Function":
            # Env vars often mean Lambda -> Target
            env_vars = properties.get('Environment', {}).get('Variables', {})
            refs_in_env = find_logical_ids(env_vars, defined_logical_ids)
            for ref_id in refs_in_env:
                print(f"  {logical_id} ({cfn_type} Env) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)

            # Check Role for lambda:InvokeFunction permissions
            role_ref = properties.get('Role') # Works for Function and Serverless::Function
            role_ids = find_logical_ids(role_ref, defined_logical_ids)
            if role_ids:
                role_logical_id = list(role_ids)[0] # Assuming one role
                # Need to check if the Role resource itself exists in the template
                if role_logical_id in resources and resources[role_logical_id].get('Type') == "AWS::IAM::Role":
                     role_props = resources[role_logical_id].get('Properties', {})
                     policies = role_props.get('Policies', [])
                     # Also check ManagedPolicyArns if applicable (more complex to parse)
                     # Also check Inline Policies property

                     # Simple check in inline policies
                     for policy in policies:
                         statements = policy.get('PolicyDocument', {}).get("Statement", [])
                         for statement in statements:
                             action = statement.get('Action', [])
                             if not isinstance(action, list): action = [action]

                             if statement.get('Effect') == 'Allow' and 'lambda:InvokeFunction' in action:
                                 policy_resources = statement.get('Resource', [])
                                 if not isinstance(policy_resources, list): policy_resources = [policy_resources]

                                 # Find logical IDs referenced in the Resource field of the policy
                                 refs_in_policy_res = find_logical_ids(policy_resources, defined_logical_ids)

                                 for target_lambda_id in refs_in_policy_res:
                                     # Ensure the target is actually a Lambda defined in the template
                                     target_type = resources.get(target_lambda_id, {}).get('Type')
                                     if target_lambda_id in resources and target_type in ["AWS::Lambda::Function", "AWS::Serverless::Function"]:
                                         print(f"  {logical_id} ({cfn_type} via Role Invoke) -> {target_lambda_id}")
                                         parsed_relations[logical_id]['invokes'].add(target_lambda_id)

            # Handle SAM 'Events' shorthand for Serverless::Function
            if cfn_type == "AWS::Serverless::Function":
                events = properties.get('Events', {})
                for event_name, event_details in events.items():
                    event_type = event_details.get('Type')
                    event_props = event_details.get('Properties', {})

                    # Example for SQS Event
                    if event_type == 'SQS':
                        queue_ref = event_props.get('Queue')
                        queue_ids = find_logical_ids(queue_ref, defined_logical_ids)
                        if queue_ids:
                            queue_logical_id = list(queue_ids)[0]
                            # Queue invokes this Lambda
                            print(f"  {queue_logical_id} (SQS Event Source for SAM) -> {logical_id}")
                            parsed_relations[queue_logical_id]['invokes'].add(logical_id)
                        else:
                            print(f"  Warning: Could not resolve SQS Queue reference '{queue_ref}' for SAM Function '{logical_id}' event '{event_name}'.")
                    # Add handlers for other SAM Event types (API, Schedule, S3, etc.) here
                    # Example for API Event (more complex, involves implicit API GW resources)
                    elif event_type == 'Api':
                         # This implies an API Gateway invokes this function.
                         # We might need to create a pseudo API GW resource or link to an existing one.
                         # For simplicity, we could use a generic 'APIGateway' pseudo-resource if not explicitly defined.
                         api_gw_pseudo_id = 'APIGateway' # Default pseudo-ID
                         rest_api_id_ref = event_props.get('RestApiId') # Check if linked to specific API
                         if rest_api_id_ref:
                             resolved_api_ids = find_logical_ids(rest_api_id_ref, defined_logical_ids)
                             if resolved_api_ids:
                                 api_gw_pseudo_id = list(resolved_api_ids)[0] # Use the actual logical ID

                         print(f"  {api_gw_pseudo_id} (API Event Source for SAM) -> {logical_id}")
                         # Ensure the API GW resource exists in our structure
                         if api_gw_pseudo_id not in parsed_relations:
                             parsed_relations[api_gw_pseudo_id]['_original_type'] = 'AWS::ApiGateway::RestApi' # Assume type
                             parsed_relations[api_gw_pseudo_id]['account_name'] = account_name
                             parsed_relations[api_gw_pseudo_id]['invokes'] = set() # Initialize invokes
                         parsed_relations[api_gw_pseudo_id]['invokes'].add(logical_id)
                    # --- NEW: Handle other SAM Event Types ---
                    elif event_type == 'S3':
                        bucket_ref = event_props.get('Bucket')
                        if bucket_ref:
                             # S3 Bucket Event invokes this Lambda
                             s3_service_id = 'S3' # Use pseudo-resource ID
                             s3_service_type = 'AWS::Service::S3'
                             print(f"  {s3_service_id} (S3 Event Source for SAM via Bucket Ref: {bucket_ref}) -> {logical_id}")
                             # Ensure S3 pseudo-resource exists
                             if s3_service_id not in parsed_relations:
                                parsed_relations[s3_service_id]['_original_type'] = s3_service_type
                                parsed_relations[s3_service_id]['account_name'] = 'AWS'
                                parsed_relations[s3_service_id]['invokes'] = set()
                             parsed_relations[s3_service_id]['invokes'].add(logical_id)
                        else:
                             print(f"  Warning: SAM S3 Event for '{logical_id}' missing Bucket property.")

                    elif event_type == 'SNS':
                        topic_ref = event_props.get('Topic')
                        topic_ids = find_logical_ids(topic_ref, defined_logical_ids)
                        if topic_ids:
                            topic_logical_id = list(topic_ids)[0]
                            # SNS Topic invokes this Lambda
                            print(f"  {topic_logical_id} (SNS Event Source for SAM) -> {logical_id}")
                            parsed_relations[topic_logical_id]['invokes'].add(logical_id)
                        else:
                            print(f"  Warning: Could not resolve SNS Topic reference '{topic_ref}' for SAM Function '{logical_id}' event '{event_name}'.")

                    elif event_type == 'DynamoDB':
                        stream_ref = event_props.get('Stream')
                        # Stream ARN is usually !GetAtt Table.StreamArn
                        # We need to resolve the Table ID from this
                        table_ids = set()
                        if isinstance(stream_ref, dict) and 'Fn::GetAtt' in stream_ref:
                            getatt_list = stream_ref['Fn::GetAtt']
                            if isinstance(getatt_list, list) and len(getatt_list) > 0 and getatt_list[0] in defined_logical_ids:
                                table_ids.add(getatt_list[0])
                        elif isinstance(stream_ref, str):
                             # Less common, maybe direct ARN reference - try to find base ID
                             table_ids.update(find_logical_ids(stream_ref, defined_logical_ids))

                        if table_ids:
                            table_logical_id = list(table_ids)[0]
                             # DynamoDB Table Stream invokes this Lambda
                            print(f"  {table_logical_id} (DynamoDB Event Source for SAM) -> {logical_id}")
                            parsed_relations[table_logical_id]['invokes'].add(logical_id)
                        else:
                            print(f"  Warning: Could not resolve DynamoDB Table from Stream '{stream_ref}' for SAM Function '{logical_id}' event '{event_name}'.")

                    elif event_type == 'Schedule':
                         # EventBridge Schedule invokes this Lambda
                         eb_service_id = 'EventBridge' # Use pseudo-resource ID
                         eb_service_type = 'AWS::Service::EventBridge'
                         # Schedule name/ARN might be in event_props.Schedule, but not always a defined resource
                         print(f"  {eb_service_id} (Schedule Event Source for SAM) -> {logical_id}")
                         # Ensure EventBridge pseudo-resource exists
                         if eb_service_id not in parsed_relations:
                            parsed_relations[eb_service_id]['_original_type'] = eb_service_type
                            parsed_relations[eb_service_id]['account_name'] = 'AWS'
                            parsed_relations[eb_service_id]['invokes'] = set()
                         parsed_relations[eb_service_id]['invokes'].add(logical_id)

            # --- NEW: Handle Lambda Dead Letter Queue (DLQ) ---
            dlq_config = properties.get('DeadLetterConfig')
            if isinstance(dlq_config, dict):
                 target_arn_ref = dlq_config.get('TargetArn')
                 dlq_ids = find_logical_ids(target_arn_ref, defined_logical_ids)
                 if dlq_ids:
                     dlq_logical_id = list(dlq_ids)[0]
                     # Lambda sends failed events to the DLQ (SQS or SNS)
                     print(f"  {logical_id} (Lambda DLQ) -> {dlq_logical_id}")
                     parsed_relations[logical_id]['invokes'].add(dlq_logical_id)
                 elif target_arn_ref:
                     print(f"  Warning: Could not resolve DLQ TargetArn '{target_arn_ref}' for Lambda '{logical_id}'.")

        elif cfn_type == "AWS::ApiGateway::Method":
            integration = properties.get('Integration', {})
            refs_in_uri = find_logical_ids(integration.get('Uri'), defined_logical_ids)
            for ref_id in refs_in_uri:
                # Method invokes target (usually Lambda)
                print(f"  {logical_id} (API Method) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)
                # Also infer parent RestApi invokes target
                api_ref = properties.get('RestApiId')
                api_ids = find_logical_ids(api_ref, defined_logical_ids)
                if api_ids:
                    api_logical_id = list(api_ids)[0]
                    print(f"  {api_logical_id} (API Gateway) -> {ref_id}")
                    # Ensure API Gateway exists and add invoke
                    if api_logical_id not in parsed_relations: # Should exist if defined
                         parsed_relations[api_logical_id]['_original_type'] = 'AWS::ApiGateway::RestApi'
                         parsed_relations[api_logical_id]['account_name'] = account_name
                         parsed_relations[api_logical_id]['invokes'] = set()
                    parsed_relations[api_logical_id]['invokes'].add(ref_id)

        elif cfn_type == "AWS::StepFunctions::StateMachine":
            # Check RoleArn for permissions to invoke other resources
            role_ref = properties.get('RoleArn')
            role_ids = find_logical_ids(role_ref, defined_logical_ids)
            if role_ids:
                role_logical_id = list(role_ids)[0]
                if role_logical_id in resources and resources[role_logical_id].get('Type') == "AWS::IAM::Role":
                     role_props = resources[role_logical_id].get('Properties', {})
                     # Check inline policies
                     policies = role_props.get('Policies', [])
                     for policy in policies:
                          statements = policy.get('PolicyDocument', {}).get("Statement", [])
                          for statement in statements:
                              action = statement.get('Action', [])
                              if not isinstance(action, list): action = [action]
                              # Check for lambda:InvokeFunction, states:StartExecution, etc.
                              if statement.get('Effect') == 'Allow' and ('lambda:InvokeFunction' in action or 'states:StartExecution' in action):
                                  policy_resources = statement.get('Resource', [])
                                  if not isinstance(policy_resources, list): policy_resources = [policy_resources]
                                  refs_in_policy_res = find_logical_ids(policy_resources, defined_logical_ids)
                                  for target_id in refs_in_policy_res:
                                      if target_id in resources: # Ensure target is defined here
                                           print(f"  {logical_id} (Step Function via Role) -> {target_id}")
                                           parsed_relations[logical_id]['invokes'].add(target_id)
            # TODO: Parse DefinitionString/Definition for Task states invoking Lambdas/other SFNs
            # --- NEW: Parse State Machine Definition ---
            definition = properties.get('Definition')
            definition_string = properties.get('DefinitionString')

            sfn_definition_json = None
            if isinstance(definition, dict): # Definition is already JSON/dict
                sfn_definition_json = definition
            elif isinstance(definition_string, str): # DefinitionString needs parsing
                try:
                    # Handle potential !Sub in DefinitionString
                    if 'Fn::Sub' in definition_string:
                        sub_input = definition_string['Fn::Sub']
                        sub_string_template = sub_input if isinstance(sub_input, str) else sub_input[0]
                        # Very basic substitution - assumes ${LogicalId} or ${LogicalId.Arn}
                        # A more robust solution would need context of Sub variables if provided
                        def replace_sub(match):
                            ref_id = match.group(1)
                            # Attempt to resolve - this is tricky without full context
                            # For now, just return the ID, find_logical_ids will catch it later if it's simple
                            return resources.get(ref_id, {}).get('Properties', {}).get('Arn', ref_id) # Basic ARN guess
                        
                        processed_string = re.sub(r'\${([a-zA-Z0-9]+)(?:\.Arn)?}', replace_sub, sub_string_template)
                        sfn_definition_json = json.loads(processed_string)
                    else:
                        sfn_definition_json = json.loads(definition_string)
                except json.JSONDecodeError as e:
                    print(f"  Warning: Could not parse JSON in DefinitionString for {logical_id}: {e}", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Error processing DefinitionString for {logical_id}: {e}", file=sys.stderr)
            elif isinstance(definition_string, dict) and 'Fn::Sub' in definition_string:
                 # Handle cases where DefinitionString is itself an Fn::Sub object
                 try:
                    sub_input = definition_string['Fn::Sub']
                    sub_string_template = sub_input if isinstance(sub_input, str) else sub_input[0]
                    # Basic substitution again
                    def replace_sub(match):
                        ref_id = match.group(1)
                        return resources.get(ref_id, {}).get('Properties', {}).get('Arn', ref_id)
                    processed_string = re.sub(r'\${([a-zA-Z0-9]+)(?:\.Arn)?}', replace_sub, sub_string_template)
                    sfn_definition_json = json.loads(processed_string)
                 except Exception as e:
                    print(f"  Warning: Error processing Fn::Sub DefinitionString for {logical_id}: {e}", file=sys.stderr)


            if sfn_definition_json and 'States' in sfn_definition_json:
                states = sfn_definition_json['States']
                # Recursive function to find Task resources
                def find_task_refs(current_states):
                    refs = set()
                    for state_name, state_data in current_states.items():
                        if state_data.get('Type') == 'Task':
                            resource_arn = state_data.get('Resource')
                            parameters = state_data.get('Parameters')
                            # Check resource ARN string
                            if isinstance(resource_arn, str):
                                refs.update(find_logical_ids(resource_arn, defined_logical_ids))
                            # Check parameters for relevant ARNs/Refs
                            if isinstance(parameters, dict):
                                for param_key, param_value in parameters.items():
                                     # Look for common keys pointing to other resources
                                     if param_key in ['FunctionName', 'StateMachineArn', 'QueueUrl', 'TopicArn']:
                                         refs.update(find_logical_ids(param_value, defined_logical_ids))
                                     # Also just generally search the value itself
                                     else:
                                          refs.update(find_logical_ids(param_value, defined_logical_ids))

                        # Recurse into Map and Parallel states
                        if state_data.get('Type') == 'Map' and 'Iterator' in state_data and 'States' in state_data['Iterator']:
                             refs.update(find_task_refs(state_data['Iterator']['States']))
                        if state_data.get('Type') == 'Parallel' and 'Branches' in state_data:
                             for branch in state_data['Branches']:
                                 if 'States' in branch:
                                     refs.update(find_task_refs(branch['States']))
                    return refs

                task_invoked_ids = find_task_refs(states)
                for target_id in task_invoked_ids:
                    # Check if it's a resource defined in this template
                    if target_id in resources:
                         print(f"  {logical_id} (Step Function Definition) -> {target_id}")
                         parsed_relations[logical_id]['invokes'].add(target_id)
                    else:
                         # Might be a direct ARN or resource in another stack
                         print(f"  Info: Step Function {logical_id} definition references external/ARN: {target_id}")
                         # Optionally add as Unknown/External if desired, but sticking to known resources for now

        # --- NEW: Handle S3 Bucket Notifications ---
        elif cfn_type == "AWS::S3::Bucket":
            notification_config = properties.get('NotificationConfiguration')
            if isinstance(notification_config, dict):
                # Define service ID for S3
                s3_service_id = 'S3' # Consistent with Lambda:Permission handling
                s3_service_type = 'AWS::Service::S3'

                targets_found = False
                invoked_targets = set()

                # Check Lambda configurations
                for config in notification_config.get('LambdaConfigurations', []):
                    func_arn = config.get('Function')
                    if func_arn:
                        invoked_targets.update(find_logical_ids(func_arn, defined_logical_ids))
                        targets_found = True

                # Check SQS configurations
                for config in notification_config.get('QueueConfigurations', []):
                    queue_arn = config.get('Queue')
                    if queue_arn:
                        invoked_targets.update(find_logical_ids(queue_arn, defined_logical_ids))
                        targets_found = True

                # Check SNS configurations
                for config in notification_config.get('TopicConfigurations', []):
                    topic_arn = config.get('Topic')
                    if topic_arn:
                        invoked_targets.update(find_logical_ids(topic_arn, defined_logical_ids))
                        targets_found = True

                # If any targets found, ensure S3 pseudo-resource exists and add invokes
                if targets_found:
                    if s3_service_id not in parsed_relations:
                        parsed_relations[s3_service_id]['_original_type'] = s3_service_type
                        parsed_relations[s3_service_id]['account_name'] = 'AWS'
                        parsed_relations[s3_service_id]['invokes'] = set()
                    
                    for target_id in invoked_targets:
                         if target_id in resources:
                            print(f"  {s3_service_id} (S3 Notification via Bucket {logical_id}) -> {target_id}")
                            parsed_relations[s3_service_id]['invokes'].add(target_id)
                         else:
                            print(f"  Info: S3 Bucket {logical_id} notification references external/ARN: {target_id}")

        # --- NEW: Handle explicit SNS Subscriptions ---
        elif cfn_type == "AWS::SNS::Subscription":
            topic_arn_ref = properties.get('TopicArn')
            endpoint_ref = properties.get('Endpoint') # Can be Lambda ARN, SQS ARN, etc.
            protocol = properties.get('Protocol') # e.g., 'lambda', 'sqs'

            if topic_arn_ref and endpoint_ref and protocol in ['lambda', 'sqs']: # Focus on Lambda/SQS for now
                topic_ids = find_logical_ids(topic_arn_ref, defined_logical_ids)
                endpoint_ids = find_logical_ids(endpoint_ref, defined_logical_ids)

                if topic_ids and endpoint_ids:
                    topic_logical_id = list(topic_ids)[0]
                    endpoint_logical_id = list(endpoint_ids)[0]

                    # Ensure the referenced Topic exists in our parsed relations
                    if topic_logical_id in parsed_relations:
                        print(f"  {topic_logical_id} (SNS Topic via Subscription) -> {endpoint_logical_id}")
                        parsed_relations[topic_logical_id]['invokes'].add(endpoint_logical_id)
                    else:
                        print(f"  Warning: Topic '{topic_logical_id}' referenced in Subscription '{logical_id}' not found in this template.")
                else:
                     print(f"  Warning: Could not resolve TopicArn ({topic_arn_ref}) or Endpoint ({endpoint_ref}) for Subscription '{logical_id}'.")


        elif cfn_type == "AWS::Events::Rule":
            targets = properties.get('Targets', [])
            for target in targets:
                # Target 'Arn' points to the invoked resource
                refs_in_target_arn = find_logical_ids(target.get('Arn'), defined_logical_ids)
                for ref_id in refs_in_target_arn:
                    print(f"  {logical_id} (Event Rule) -> {ref_id}")
                    parsed_relations[logical_id]['invokes'].add(ref_id)

        elif cfn_type == "AWS::Lambda::EventSourceMapping":
            # Source Arn invokes the FunctionName
            func_ref = properties.get('FunctionName')
            source_ref = properties.get('EventSourceArn')
            func_ids = find_logical_ids(func_ref, defined_logical_ids)
            source_ids = find_logical_ids(source_ref, defined_logical_ids)
            if func_ids and source_ids:
                func_id = list(func_ids)[0]
                source_id = list(source_ids)[0]
                print(f"  {source_id} (Event Source) -> {func_id}")
                # Source invokes the Lambda
                parsed_relations[source_id]['invokes'].add(func_id)

        elif cfn_type == "AWS::Lambda::Permission":
            # ** NEW LOGIC: Create pseudo-resource for external service **
            principal = properties.get('Principal')
            func_ref = properties.get('FunctionName')
            func_ids = find_logical_ids(func_ref, defined_logical_ids)

            if func_ids and principal in SERVICE_PRINCIPAL_MAP:
                target_lambda_id = list(func_ids)[0]
                service_info = SERVICE_PRINCIPAL_MAP[principal]
                service_id = service_info['id']
                service_type = service_info['type']

                print(f"  {service_id} (External Service via Permission) -> {target_lambda_id}")

                # Ensure the service pseudo-resource exists in our structure
                if service_id not in parsed_relations:
                    parsed_relations[service_id]['_original_type'] = service_type
                    parsed_relations[service_id]['account_name'] = 'AWS' # Mark as AWS service account
                    parsed_relations[service_id]['invokes'] = set() # Initialize invokes

                # Add the lambda to the service's invokes list
                parsed_relations[service_id]['invokes'].add(target_lambda_id)
            elif func_ids:
                # Handle non-service principals if necessary (e.g., another AWS account)
                print(f"  Note: Lambda permission found for principal '{principal}' targeting '{list(func_ids)[0]}'. Handling non-service principals not implemented.")


        elif cfn_type == "AWS::AppSync::DataSource":
            lambda_conf = properties.get('LambdaConfig', {})
            ddb_conf = properties.get('DynamoDBConfig', {})
            # DataSource invokes underlying Lambda or DynamoDB table
            refs_in_ds = find_logical_ids(lambda_conf.get('LambdaFunctionArn'), defined_logical_ids)
            refs_in_ds.update(find_logical_ids(ddb_conf.get('TableName'), defined_logical_ids))
            # Add other DataSource types (HTTP, Relational DB, etc.)
            for ref_id in refs_in_ds:
                print(f"  {logical_id} (AppSync DS) -> {ref_id}")
                parsed_relations[logical_id]['invokes'].add(ref_id)

            # --- NEW: Handle other AppSync DataSource Types ---
            http_config = properties.get('HttpConfig')
            event_bridge_config = properties.get('EventBridgeConfig')
            # Add others like RelationalDatabaseConfig, ElasticsearchConfig etc. if needed

            if isinstance(http_config, dict) and http_config.get('Endpoint'):
                 # DataSource invokes an HTTP endpoint
                 http_endpoint = http_config['Endpoint']
                 print(f"  {logical_id} (AppSync DS) -> {http_endpoint} (HTTP Endpoint)")
                 # Not adding to invokes list as it's not a defined CFN resource
                 # Could add a special representation if needed

            if isinstance(event_bridge_config, dict) and event_bridge_config.get('EventBusArn'):
                 # DataSource invokes EventBridge
                 eb_bus_arn_ref = event_bridge_config['EventBusArn']
                 eb_ids = find_logical_ids(eb_bus_arn_ref, defined_logical_ids)
                 if eb_ids:
                      eb_logical_id = list(eb_ids)[0]
                      print(f"  {logical_id} (AppSync DS) -> {eb_logical_id} (EventBridge Bus)")
                      parsed_relations[logical_id]['invokes'].add(eb_logical_id)
                 else:
                      print(f"  Info: AppSync DS {logical_id} targets external/ARN EventBus: {eb_bus_arn_ref}")


        elif cfn_type == "AWS::AppSync::Resolver":
             # Resolver invokes its DataSource
             ds_name = properties.get('DataSourceName') # This is usually the *name* property of the DS
             ds_logical_id = None
             # Find the DataSource resource by its Name property
             for res_id, res_data in resources.items():
                 if res_data.get('Type') == "AWS::AppSync::DataSource" and res_data.get('Properties', {}).get('Name') == ds_name:
                     ds_logical_id = res_id
                     break
             if ds_logical_id:
                 print(f"  {logical_id} (AppSync Resolver) -> {ds_logical_id}")
                 parsed_relations[logical_id]['invokes'].add(ds_logical_id)
             else:
                 # Could also be a Ref to the logical ID
                 ds_ids = find_logical_ids(ds_name, defined_logical_ids)
                 if ds_ids:
                      ds_logical_id = list(ds_ids)[0]
                      print(f"  {logical_id} (AppSync Resolver Ref) -> {ds_logical_id}")
                      parsed_relations[logical_id]['invokes'].add(ds_logical_id)
                 else:
                      print(f"  Warning: Could not find DataSource '{ds_name}' for Resolver '{logical_id}'")

        # --- NEW: Handle CloudFormation Custom Resource ---
        elif cfn_type == "AWS::CloudFormation::CustomResource":
            service_token_ref = properties.get('ServiceToken')
            token_ids = find_logical_ids(service_token_ref, defined_logical_ids)
            if token_ids:
                 # Custom Resource invokes the Lambda/SNS specified in ServiceToken
                 token_logical_id = list(token_ids)[0]
                 print(f"  {logical_id} (Custom Resource) -> {token_logical_id}")
                 parsed_relations[logical_id]['invokes'].add(token_logical_id)
            elif service_token_ref:
                 print(f"  Warning: Could not resolve ServiceToken '{service_token_ref}' for Custom Resource '{logical_id}'.")

        # --- NEW: Handle API Gateway Authorizer ---
        elif cfn_type == "AWS::ApiGateway::Authorizer":
            # Authorizer is invoked by the API Gateway it's attached to
            rest_api_ref = properties.get('RestApiId')
            authorizer_uri_ref = properties.get('AuthorizerUri') # Lambda URI

            api_ids = find_logical_ids(rest_api_ref, defined_logical_ids)
            # AuthorizerUri format: arn:aws:apigateway:{region}:lambda:path/2015-03-31/functions/{lambda_arn}/invocations
            # We need to extract the lambda ARN/Ref from the URI string or object
            lambda_ids = set()
            if isinstance(authorizer_uri_ref, str):
                 # Try simple find_logical_ids first if URI itself contains a ref
                 lambda_ids.update(find_logical_ids(authorizer_uri_ref, defined_logical_ids))
                 # Basic regex to extract potential Lambda ref from standard URI path
                 match = re.search(r'functions/arn:aws:lambda:[^:]+:[^:]+:function:([^/]+)/invocations', authorizer_uri_ref)
                 if match:
                     lambda_name_or_ref = match.group(1)
                     # Check if the extracted name is a logical ID
                     if lambda_name_or_ref in defined_logical_ids:
                         lambda_ids.add(lambda_name_or_ref)
                     else:
                        # Try find_logical_ids on the extracted part too
                         lambda_ids.update(find_logical_ids(lambda_name_or_ref, defined_logical_ids))
            elif isinstance(authorizer_uri_ref, dict):
                 # Handle cases like !Sub in AuthorizerUri
                 lambda_ids.update(find_logical_ids(authorizer_uri_ref, defined_logical_ids))


            if api_ids and lambda_ids:
                 api_logical_id = list(api_ids)[0]
                 lambda_logical_id = list(lambda_ids)[0]
                 # API Gateway invokes the Authorizer Lambda
                 print(f"  {api_logical_id} (API Gateway via Authorizer {logical_id}) -> {lambda_logical_id}")
                 # Ensure API resource exists in structure
                 if api_logical_id in parsed_relations:
                     parsed_relations[api_logical_id]['invokes'].add(lambda_logical_id)
                 else:
                     print(f"  Warning: RestApi '{api_logical_id}' for Authorizer '{logical_id}' not found in this template.")
            elif rest_api_ref and authorizer_uri_ref:
                 print(f"  Warning: Could not fully resolve RestApiId ({rest_api_ref}) or Lambda from AuthorizerUri ({authorizer_uri_ref}) for Authorizer '{logical_id}'.")

        # --- NEW: Handle CloudFront Lambda@Edge ---
        elif cfn_type == "AWS::CloudFront::Distribution":
            dist_config = properties.get('DistributionConfig', {})
            lambda_associations = []
            # Check default cache behavior
            default_behavior = dist_config.get('DefaultCacheBehavior', {})
            lambda_associations.extend(default_behavior.get('LambdaFunctionAssociations', []))
            # Check other cache behaviors
            for behavior in dist_config.get('CacheBehaviors', []):
                 lambda_associations.extend(behavior.get('LambdaFunctionAssociations', []))
            
            invoked_lambda_ids = set()
            for assoc in lambda_associations:
                 lambda_arn_with_version = assoc.get('LambdaFunctionARN')
                 if isinstance(lambda_arn_with_version, str):
                     # Attempt to remove potential version suffix
                     base_lambda_arn = lambda_arn_with_version.split(':')[:-1] # Remove potential version/alias
                     base_lambda_arn = ":".join(base_lambda_arn)
                     # Try resolving the base ARN
                     lambda_ids = find_logical_ids(base_lambda_arn, defined_logical_ids)
                     if not lambda_ids:
                         # Also try resolving the original ARN in case it was a direct !Ref without version
                          lambda_ids = find_logical_ids(lambda_arn_with_version, defined_logical_ids)
                     invoked_lambda_ids.update(lambda_ids)
                 elif isinstance(lambda_arn_with_version, dict): # Handle !Ref, !GetAtt
                     # find_logical_ids should handle resolving refs/getatts
                     invoked_lambda_ids.update(find_logical_ids(lambda_arn_with_version, defined_logical_ids))

            for lambda_id in invoked_lambda_ids:
                 if lambda_id in resources:
                     # CloudFront distribution invokes the Lambda@Edge function
                     print(f"  {logical_id} (CloudFront Distribution) -> {lambda_id} (Lambda@Edge)")
                     parsed_relations[logical_id]['invokes'].add(lambda_id)
                 else:
                      print(f"  Warning: Lambda@Edge function '{lambda_id}' for CloudFront Distribution '{logical_id}' not found in this template.")


    # Second pass: Format the output structure for this template
    print("Formatting results for this template...")
    final_relations = {}
    # Include both defined resources and any created service pseudo-resources
    all_ids_to_process = set(parsed_relations.keys())

    for logical_id in all_ids_to_process:
        data = parsed_relations[logical_id]
        original_type = data.get('_original_type', 'Unknown')
        display_type = CFN_TYPE_MAP.get(original_type, original_type) # Use map, fallback to original

        # Format the 'invokes' list
        final_invokes = []
        for target_name in sorted(list(data.get('invokes', set()))):
             target_info = {}
             if target_name in parsed_relations: # Check if target exists in *our collected data*
                 # Target is defined in this template or is another pseudo-resource
                 target_original_type = parsed_relations[target_name].get('_original_type', 'Unknown')
                 target_info = {
                     "name": target_name,
                     "type": CFN_TYPE_MAP.get(target_original_type, target_original_type),
                     "account_name": parsed_relations[target_name].get('account_name', account_name) # Use target's account
                 }
             else:
                  # Target is referenced but not defined in this template (likely external CFN stack)
                  # Note: This case becomes less likely for service pseudo-resources as they are created on the fly
                  print(f"  Info: Resource '{target_name}' invoked by '{logical_id}' is likely external or in another template.")
                  target_info = {
                     "name": target_name,
                     "type": "Unknown/External",
                     "account_name": "Unknown"
                 }
             final_invokes.append(target_info)

        final_relations[logical_id] = {
            "type": display_type,
            "account_name": data.get('account_name', account_name),
            "invokes": final_invokes,
            # NO 'invoked_by' or 'invoked_by_external' here
        }

    print(f"Parsing complete for {template_path}. Processed {len(final_relations)} resources (including pseudo-services).")
    return final_relations


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
    """Writes the relations dictionary (invokes only) to the specified JSON file."""
    print(f"Writing combined data (invokes only) to {output_path}...")
    output_data = {}
    # Convert sets to lists for JSON serialization before writing
    for logical_id, data in relations.items():
        # Ensure essential keys exist before copying
        data.setdefault('type', 'Unknown')
        data.setdefault('account_name', 'Unknown')
        data.setdefault('invokes', [])
        output_data[logical_id] = data.copy() # Shallow copy is fine

    try:
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=4) # Write the formatted data
        print(f"Successfully wrote data to {output_path}.")
    except IOError as e:
        print(f"Error writing to file {output_path}: {e}", file=sys.stderr)
        # Don't exit, just report error
# --- Read/Write JSON Data File --- END

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Parse CloudFormation templates and update a JSON resource relationship data file (generates invokes, including pseudo-services; run invoked_by script afterwards). "
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
    # Load existing data first - this allows merging across multiple runs
    # including merging service pseudo-resources defined by permissions in different templates
    all_relations_data = load_existing_data(output_file)
    print(f"Loaded {len(all_relations_data)} existing resource definitions from {output_file}")

    print(f"Processing {len(args.template_account_pairs) // 2} template(s) from command line...")

    new_data_parsed = False
    for i in range(0, len(args.template_account_pairs), 2):
        template_file = args.template_account_pairs[i]
        account_name = args.template_account_pairs[i+1]

        print(f"\n--- Parsing: {template_file} (Account: {account_name}) ---")
        # Parse the current template
        relations_data = parse_cloudformation(template_file, account_name)

        if relations_data:
            print(f"Merging data from {template_file}...")
            # Merge results - new data overwrites/updates existing keys
            for res_id, res_data in relations_data.items():
                if res_id in all_relations_data:
                    # If resource already exists (e.g., service pseudo-resource), update its invokes list
                    existing_invokes = set(tuple(sorted(d.items())) for d in all_relations_data[res_id].get('invokes', []))
                    new_invokes = set(tuple(sorted(d.items())) for d in res_data.get('invokes', []))
                    merged_invokes_tuples = existing_invokes.union(new_invokes)
                    # Convert tuples back to dictionaries
                    all_relations_data[res_id]['invokes'] = sorted([dict(t) for t in merged_invokes_tuples], key=lambda x: x['name'])

                    # Update type and account only if the new data is more specific (e.g. not 'Unknown')
                    if res_data.get('type') and res_data['type'] != 'Unknown':
                         all_relations_data[res_id]['type'] = res_data['type']
                    if res_data.get('account_name') and res_data['account_name'] != 'Unknown':
                         all_relations_data[res_id]['account_name'] = res_data['account_name']
                else:
                    # New resource, just add it
                    all_relations_data[res_id] = res_data

            new_data_parsed = True
        else:
            print(f"Warning: No resource data generated from {template_file}. Skipping merge.", file=sys.stderr)

    # Write the combined data (without invoked_by) at the end
    if new_data_parsed or all_relations_data:
        # Final check to ensure essential keys exist in all entries before writing
        for res_id, res_data in all_relations_data.items():
            res_data.setdefault('type', 'Unknown')
            res_data.setdefault('account_name', 'Unknown')
            res_data.setdefault('invokes', [])

        write_data_file(all_relations_data, output_file)
    else:
        print("No data parsed or loaded. Output file not created or modified.")
        sys.exit(1) # Exit with error if no data exists at all 