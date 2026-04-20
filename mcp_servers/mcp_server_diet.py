from mcp.server.fastmcp import FastMCP

from src.mcp_tools import diet_analyze_tool

mcp = FastMCP(name="mcp-diet")


@mcp.tool()
def diet_analyze(payload: dict) -> dict:
    """
    Analyze meal text and save daily diet log.
    payload keys: date(YYYY-MM-DD), meal_text
    """
    return diet_analyze_tool(payload)


if __name__ == "__main__":
    mcp.run(transport="stdio")
