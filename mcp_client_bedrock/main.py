import asyncio
from mcp import StdioServerParameters
from converse_agent import ConverseAgent
from converse_tools import ConverseToolManager
from mcp_client import MCPClient

async def main():
    """
    Main function that sets up and runs an interactive AI agent with tool integration.
    The agent can process user prompts and utilize registered tools to perform tasks.
    """
    # Initialize model configuration
    model_id = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
    #model_id = "us.amazon.nova-pro-v1:0"
        
    # Set up the agent and tool manager
    agent = ConverseAgent(model_id)
    agent.tools = ConverseToolManager()

    # Define the agent's behavior through system prompt
    agent.system_prompt = """You are a helpful assistant that can use tools to help you answer 
questions and perform tasks."""

    # Create server parameters for SQLite configuration
    server_params = StdioServerParameters(
        command="uv",
        args=["--directory", "..", "run", "main.py"],
        env=None
    )

    # Initialize MCP client with server parameters
    async with MCPClient(server_params) as mcp_client:

        # Fetch available tools from the MCP client
        tools = await mcp_client.get_available_tools()

        # Register each available tool with the agent
        for tool in tools:
            agent.tools.register_tool(
                name=tool.name,
                func=mcp_client.call_tool,
                description=tool.description,
                input_schema={'json': tool.inputSchema}
            )

        # Start interactive prompt loop
        while True:
            try:
                # Get user input and check for exit commands
                user_prompt = input("\nEnter your prompt (or 'quit' to exit): ")
                if user_prompt.lower() in ['quit', 'exit', 'q']:
                    break
                
                # Process the prompt and display the response
                response = await agent.invoke_with_prompt(user_prompt)
                print("\nResponse:", response)
                
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except Exception as e:
                print(f"\nError occurred: {e}")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main()) 