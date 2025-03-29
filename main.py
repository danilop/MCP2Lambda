import json
import os
import re
import argparse

from mcp.server.fastmcp import FastMCP, Context
import boto3

# Strategy selection - set to True to register Lambda functions as individual tools
# set to False to use the original approach with list and invoke tools
parser = argparse.ArgumentParser(description='MCP Gateway to AWS Lambda')
parser.add_argument('--no-pre-discovery', 
                   action='store_true',
                   help='Disable registering Lambda functions as individual tools at startup')

# Parse arguments and set default configuration
args = parser.parse_args()

# Check environment variable first (takes precedence if set)
if 'PRE_DISCOVERY' in os.environ:
    PRE_DISCOVERY = os.environ.get('PRE_DISCOVERY').lower() == 'true'
    print(f"Using PRE_DISCOVERY from env: {PRE_DISCOVERY}")
else:
    # Otherwise use CLI argument (default is enabled, --no-pre-discovery disables)
    PRE_DISCOVERY = not args.no_pre_discovery
    print(f"Using PRE_DISCOVERY from args: {PRE_DISCOVERY}")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
FUNCTION_PREFIX = os.environ.get("FUNCTION_PREFIX", "mcp2lambda-")
FUNCTION_LIST = json.loads(os.environ.get("FUNCTION_LIST", "[]"))

print(f"AWS_REGION: {AWS_REGION}")
print(f"FUNCTION_PREFIX: {FUNCTION_PREFIX}")
print(f"FUNCTION_LIST: {FUNCTION_LIST}")

mcp = FastMCP("MCP Gateway to AWS Lambda")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def validate_function_name(function_name: str) -> bool:
    """Validate that the function name is valid and can be called."""
    is_valid = function_name.startswith(FUNCTION_PREFIX) or function_name in FUNCTION_LIST
    print(f"Validating function name: {function_name}, valid: {is_valid}")
    return is_valid


def sanitize_tool_name(name: str) -> str:
    """Sanitize a Lambda function name to be used as a tool name."""
    # Remove prefix if present
    if name.startswith(FUNCTION_PREFIX):
        name = name[len(FUNCTION_PREFIX):]
    
    # Replace invalid characters with underscore
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    
    # Ensure name doesn't start with a number
    if name and name[0].isdigit():
        name = "_" + name
    
    print(f"Sanitized tool name: {name}")
    return name


def format_lambda_response(function_name: str, payload: bytes) -> str:
    """Format the Lambda function response payload."""
    try:
        # Try to parse the payload as JSON
        payload_json = json.loads(payload)
        return f"Function {function_name} returned: {json.dumps(payload_json, indent=2)}"
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Return raw payload if not JSON
        return f"Function {function_name} returned payload: {payload}"


def list_functions_paginated():
    """List Lambda functions with pagination."""
    functions = []
    paginator = lambda_client.get_paginator('list_functions')
    
    try:
        # Configure pagination to get more results per page
        page_iterator = paginator.paginate(
            PaginationConfig={
                'PageSize': 50  # Maximum page size
            }
        )
        
        # Filter for functions matching our prefix during pagination
        filtered_iterator = page_iterator.search(
            f"Functions[?starts_with(FunctionName, `{FUNCTION_PREFIX}`)]"
        )
        
        # Collect matching functions
        for function in filtered_iterator:
            functions.append(function)
            print(f"Found matching function: {function['FunctionName']}")
                
    except Exception as e:
        print(f"Error listing functions: {e}")
        return []
    
    print(f"Total matching functions found: {len(functions)}")
    return functions


# Define the generic tool functions that can be used directly or as fallbacks
def list_lambda_functions_impl(ctx: Context) -> str:
    """Tool that lists all AWS Lambda functions that you can call as tools.
    Use this list to understand what these functions are and what they do.
    This functions can help you in many different ways."""

    print("Listing Lambda functions...")
    ctx.info("Calling AWS Lambda ListFunctions...")

    functions = list_functions_paginated()
    print(f"Retrieved {len(functions)} total functions")

    functions_with_prefix = [
        f for f in functions if validate_function_name(f["FunctionName"])
    ]

    ctx.info(f"Found {len(functions_with_prefix)} functions with prefix {FUNCTION_PREFIX}")
    print(f"Functions with prefix: {json.dumps(functions_with_prefix, indent=2)}")
    
    # Pass only function names and descriptions to the model
    function_names_and_descriptions = [ 
        {field: f[field] for field in ["FunctionName", "Description"] if field in f}
        for f in functions_with_prefix
    ]
    
    return json.dumps(function_names_and_descriptions)


def invoke_lambda_function_impl(function_name: str, parameters: dict, ctx: Context) -> str:
    """Tool that invokes an AWS Lambda function with a JSON payload.
    Before using this tool, list the functions available to you."""
    
    print(f"Attempting to invoke function: {function_name}")
    if not validate_function_name(function_name):
        return f"Function {function_name} is not valid"

    ctx.info(f"Invoking {function_name} with parameters: {parameters}")

    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(parameters),
    )

    ctx.info(f"Function {function_name} returned with status code: {response['StatusCode']}")

    if "FunctionError" in response:
        error_message = f"Function {function_name} returned with error: {response['FunctionError']}"
        ctx.error(error_message)
        return error_message

    payload = response["Payload"].read()
    
    # Format the response payload
    return format_lambda_response(function_name, payload)


def create_lambda_tool(function_name: str, description: str):
    """Create a tool function for a Lambda function."""
    # Create a meaningful tool name
    tool_name = sanitize_tool_name(function_name)
    print(f"Creating Lambda tool: {tool_name}")
    
    # Define the inner function
    def lambda_function(parameters: dict, ctx: Context) -> str:
        """Tool for invoking a specific AWS Lambda function with parameters."""
        # Use the same implementation as the generic invoke function
        return invoke_lambda_function_impl(function_name, parameters, ctx)
    
    # Set the function's documentation
    lambda_function.__doc__ = description
    
    # Apply the decorator manually with the specific name
    print(f"Registering tool with MCP: {tool_name}")
    decorated_function = mcp.tool(name=tool_name)(lambda_function)
    print(f"Successfully registered tool: {tool_name}")
    
    return decorated_function


print("Starting MCP server...")

# Register Lambda functions as individual tools if dynamic strategy is enabled
if PRE_DISCOVERY:
    try:
        print("Using dynamic Lambda function registration strategy...")
        functions = list_functions_paginated()
        print(f"Found {len(functions)} total functions")
        
        valid_functions = [
            f for f in functions if validate_function_name(f["FunctionName"])
        ]
        
        print(f"Dynamically registering {len(valid_functions)} Lambda functions as tools...")
        print(f"Valid functions: {json.dumps(valid_functions, indent=2)}")
        
        for function in valid_functions:
            function_name = function["FunctionName"]
            description = function.get("Description", f"AWS Lambda function: {function_name}")
            
            # Extract information about parameters from the description if available
            if "Expected format:" in description:
                # Add parameter information to the description
                parameter_info = description.split("Expected format:")[1].strip()
                description = f"{description}\n\nParameters: {parameter_info}"
            
            # Register the Lambda function as a tool
            create_lambda_tool(function_name, description)
        
        print("Lambda functions registered successfully as individual tools.")
    
    except Exception as e:
        print(f"Error registering Lambda functions as tools: {e}")
        print("Falling back to generic Lambda tools...")
        
        # Register the generic tool functions with MCP as fallback
        print("Registering generic Lambda tools...")
        mcp.tool()(list_lambda_functions_impl)
        mcp.tool()(invoke_lambda_function_impl)
        print("Using generic Lambda tools strategy...")
else:
    # Register the generic tool functions with MCP
    print("Registering generic Lambda tools...")
    mcp.tool()(list_lambda_functions_impl)
    mcp.tool()(invoke_lambda_function_impl)
    print("Using generic Lambda tools strategy...")

print("MCP server initialization complete.")

if __name__ == "__main__":
    mcp.run()
