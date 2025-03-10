import json
import os
import re
import argparse

from mcp.server.fastmcp import FastMCP, Context
import boto3

# Strategy selection - set to True to register Lambda functions as individual tools
# set to False to use the original approach with list and invoke tools
parser = argparse.ArgumentParser(description='MCP Gateway to AWS Lambda')
parser.add_argument('--pre-discovery', 
                   action='store_true',
                   default=os.environ.get('PRE_DISCOVERY', 'true').lower() == 'true',
                   help='Register Lambda functions as individual tools at startup')

args = parser.parse_args()
PRE_DISCOVERY = args.pre_discovery

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
FUNCTION_PREFIX = os.environ.get("FUNCTION_PREFIX", "mcp2lambda-")
FUNCTION_LIST = json.loads(os.environ.get("FUNCTION_LIST", "[]"))

mcp = FastMCP("MCP Gateway to AWS Lambda")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def validate_function_name(function_name: str) -> bool:
    """Validate that the function name is valid and can be called."""
    return function_name.startswith(FUNCTION_PREFIX) or function_name in FUNCTION_LIST


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


# Register the original tools if not using dynamic tools
if not PRE_DISCOVERY:
    @mcp.tool()
    def list_lambda_functions(ctx: Context) -> str:
        """Tool that lists all AWS Lambda functions that you can call as tools.
        Use this list to understand what these functions are and what they do.
        This functions can help you in many different ways."""

        ctx.info("Calling AWS Lambda ListFunctions...")

        functions = lambda_client.list_functions()

        ctx.info(f"Found {len(functions['Functions'])} functions")

        functions_with_prefix = [
            f for f in functions["Functions"] if validate_function_name(f["FunctionName"])
        ]

        ctx.info(f"Found {len(functions_with_prefix)} functions with prefix {FUNCTION_PREFIX}")
        
        # Pass only function names and descriptions to the model
        function_names_and_descriptions = [ 
            {field: f[field] for field in ["FunctionName", "Description"] if field in f}
            for f in functions_with_prefix
        ]
        
        return json.dumps(function_names_and_descriptions)


    @mcp.tool()
    def invoke_lambda_function(function_name: str, parameters: dict, ctx: Context) -> str:
        """Tool that invokes an AWS Lambda function with a JSON payload.
        Before using this tool, list the functions available to you."""
        
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
    
    # Define the inner function
    def lambda_function(parameters: dict, ctx: Context) -> str:
        """Tool for invoking a specific AWS Lambda function with parameters."""
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
        
        return format_lambda_response(function_name, payload)
    
    # Set the function's documentation
    lambda_function.__doc__ = description
    
    # Apply the decorator manually with the specific name
    decorated_function = mcp.tool(name=tool_name)(lambda_function)
    
    return decorated_function


# Register Lambda functions as individual tools if dynamic strategy is enabled
if PRE_DISCOVERY:
    try:
        print("Using dynamic Lambda function registration strategy...")
        functions = lambda_client.list_functions()
        valid_functions = [
            f for f in functions["Functions"] if validate_function_name(f["FunctionName"])
        ]
        
        print(f"Dynamically registering {len(valid_functions)} Lambda functions as tools...")
        
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
        # If dynamic registration fails, fall back to the original strategy
        
        @mcp.tool()
        def list_lambda_functions(ctx: Context) -> str:
            """Tool that lists all AWS Lambda functions that you can call as tools.
            Use this list to understand what these functions are and what they do.
            This functions can help you in many different ways."""

            ctx.info("Calling AWS Lambda ListFunctions...")

            functions = lambda_client.list_functions()

            ctx.info(f"Found {len(functions['Functions'])} functions")

            functions_with_prefix = [
                f for f in functions["Functions"] if validate_function_name(f["FunctionName"])
            ]

            ctx.info(f"Found {len(functions_with_prefix)} functions with prefix {FUNCTION_PREFIX}")
            
            # Pass only function names and descriptions to the model
            function_names_and_descriptions = [ 
                {field: f[field] for field in ["FunctionName", "Description"] if field in f}
                for f in functions_with_prefix
            ]
            
            return json.dumps(function_names_and_descriptions)


        @mcp.tool()
        def invoke_lambda_function(function_name: str, parameters: dict, ctx: Context) -> str:
            """Tool that invokes an AWS Lambda function with a JSON payload.
            Before using this tool, list the functions available to you."""
            
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
else:
    print("Using generic Lambda tools strategy...")


if __name__ == "__main__":
    mcp.run()
