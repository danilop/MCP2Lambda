import json
import os

from mcp.server.fastmcp import FastMCP, Context
import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
FUNCTION_PREFIX = os.environ.get("FUNCTION_PREFIX", "mcp2lambda-")


mcp = FastMCP("MCP Gateway to AWS Lambda")

lambda_client = boto3.client("lambda", region_name=AWS_REGION)


@mcp.tool()
def list_lambda_functions(ctx: Context) -> str:
    """Tool that lists all AWS Lambda functions that you can call as tools.
    Use this list to understand what these functions are and what they do.
    This functions can help you in many different ways."""

    ctx.info("Calling AWS Lambda ListFunctions...")
    functions = lambda_client.list_functions()
    ctx.info(f"Found {len(functions['Functions'])} functions")
    functions_with_prefix = [
        f for f in functions["Functions"] if f["FunctionName"].startswith(FUNCTION_PREFIX)
    ]
    ctx.info(f"Found {len(functions_with_prefix)} functions with prefix {FUNCTION_PREFIX}")
    
    function_names_and_descriptions = [ 
        {field: f[field] for field in ["FunctionName", "Description"] if field in f}
        for f in functions_with_prefix
    ]
    return json.dumps(function_names_and_descriptions)


@mcp.tool()
def invoke_lambda_function(function_name: str, parameters: dict, ctx: Context) -> str:
    """Tool that invokes an AWS Lambda function with a JSON payload.
    Before using this tool, list the functions available to you."""
    
    if not function_name.startswith(FUNCTION_PREFIX):
        return f"Function {function_name} does not start with prefix {FUNCTION_PREFIX}"
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
    return f"Function {function_name} returned payload: {payload}"


if __name__ == "__main__":
    mcp.run()