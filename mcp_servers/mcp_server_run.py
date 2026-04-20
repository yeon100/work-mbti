from mcp.server.fastmcp import FastMCP

from src.mcp_tools import run_log_upsert_tool

mcp = FastMCP(name="mcp-run")


@mcp.tool()
def run_log_upsert(payload: dict) -> dict:
    """
    Save daily running log.
    payload keys: date, distance_km, pace, duration_min, calories_kcal, cadence_spm, elevation_gain_m, rpe, memo
    """
    return run_log_upsert_tool(payload)


if __name__ == "__main__":
    mcp.run(transport="stdio")
