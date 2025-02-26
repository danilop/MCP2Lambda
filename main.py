import json
import os

from mcp.server.fastmcp import FastMCP, Context
import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
FUNCTION_PREFIX = os.environ.get("FUNCTION_PREFIX", "mcp2lambda-")
FUNCTION_LIST = json.loads(os.environ.get("FUNCTION_LIST", "[]"))

mcp = FastMCP("MCP Gateway to AWS Lambda")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)


def validate_function_name(function_name: str) -> bool:
    """Validate that the function name is valid and can be called."""
    return function_name.startswith(FUNCTION_PREFIX) or function_name in FUNCTION_LIST


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

    # The full payload is returned to the model
    return f"Function {function_name} returned payload: {payload}"


if __name__ == "__main__":
    mcp.run()