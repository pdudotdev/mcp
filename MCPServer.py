import os
import json
from fastmcp import FastMCP
from dotenv import load_dotenv
from scrapli import AsyncScrapli
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()
USERNAME = os.getenv("ROUTER_USERNAME")
PASSWORD = os.getenv("ROUTER_PASSWORD")

if not USERNAME or not PASSWORD:
    raise RuntimeError("ROUTER_USERNAME / ROUTER_PASSWORD not set")
    
# Instantiate the FastMCP class
mcp = FastMCP("mcp_automation")

# Loading devices from inventory
INVENTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory", "NETWORK.json")
if not os.path.exists(INVENTORY_FILE):
    raise RuntimeError(f"Inventory file not found: {INVENTORY_FILE}")

# Read the inventory file
with open(INVENTORY_FILE) as f:
    devices = json.load(f)

if not USERNAME or not PASSWORD:
    raise RuntimeError("DEVICE_USERNAME / DEVICE_PASSWORD not set")

# Show command - input model
class ShowCommand(BaseModel):
    """Run a show command against a network device."""
    device: str = Field(..., description="Device name from inventory (e.g. R1, R2, R3)")
    command: str = Field(..., description="Show command to execute on the device")

# Config commands - input model
class ConfigCommand(BaseModel):
    """Send configuration commands to one or more devices."""
    devices: list[str] = Field(..., description="Device names from inventory (e.g. ['R1','R2'])")
    commands: list[str] = Field(..., description="Configuration commands to apply")

# Read config tool
@mcp.tool(name="run_show")
async def run_show(params: ShowCommand) -> str:
    """
    Execute a show command asynchronously using Scrapli via SSH.
    """
    device = devices.get(params.device)
    if not device:
        return f"Unknown device. Available devices are: {list(devices.keys())}"

    connection = {
        "host": device["host"],
        "platform": device["platform"],
        "transport": device["transport"],
        "auth_username": USERNAME,
        "auth_password": PASSWORD,
        "auth_strict_key": False,
    }

    async with AsyncScrapli(**connection) as conn:
        response = await conn.send_command(params.command)
        return response.result

# Forbidden commands
FORBIDDEN = {"reload", "write erase", "format", "delete", "boot"}

def validate_commands(cmds: list[str]):
    for c in cmds:
        if any(bad in c.lower() for bad in FORBIDDEN):
            raise ValueError(f"Forbidden command detected: {c}")

# Send config tool
@mcp.tool(name="push_config")
async def push_config(params: ConfigCommand) -> dict:
    """
    Push configuration commands to one or more devices.
    """
    # Check for any forbidden commands
    validate_commands(params.commands)

    results = {}

    for dev_name in params.devices:
        try:
            device = devices.get(dev_name)
            if not device:
                results[dev_name] = "Unknown device"
                continue

            connection = {
                "host": device["host"],
                "platform": device["platform"],
                "transport": device["transport"],
                "auth_username": USERNAME,
                "auth_password": PASSWORD,
                "auth_strict_key": False,
            }

            async with AsyncScrapli(**connection) as conn:
                response = await conn.send_configs(params.commands)
                results[dev_name] = response.result
        
        except Exception as e:
            results[dev_name] = {
                "status": "failed",
                "error": str(e),
            }

    return results

# Run the MCP Server
if __name__ == "__main__":
    mcp.run()

