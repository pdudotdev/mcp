import os
import json
import time
import asyncio
from fastmcp import FastMCP
from dotenv import load_dotenv
from scrapli import AsyncScrapli
from pydantic import BaseModel, Field

# Load environment variables
load_dotenv()
USERNAME = os.getenv("ROUTER_USERNAME")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")

if not USERNAME or not SSH_KEY_PATH:
    raise RuntimeError("Credentials not set")

# Instantiate the FastMCP class
mcp = FastMCP("mcp_automation")

# Loading devices from inventory
INVENTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory", "NETWORK.json")
if not os.path.exists(INVENTORY_FILE):
    raise RuntimeError(f"Inventory file not found: {INVENTORY_FILE}")

# Read the inventory file
with open(INVENTORY_FILE) as f:
    devices = json.load(f)

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

# Empty placeholder - input model
class EmptyInput(BaseModel):
    pass

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
        "auth_private_key": SSH_KEY_PATH,
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

# Function for pushing configs to a device
async def push_config_to_device(dev_name, device, commands):
    connection = {
                "host": device["host"],
                "platform": device["platform"],
                "transport": device["transport"],
                "auth_username": USERNAME,
                "auth_private_key": SSH_KEY_PATH,
                "auth_strict_key": False,
            }

    async with AsyncScrapli(**connection) as conn:
        response = await conn.send_configs(commands)
        return dev_name, response.result

# Send config tool
@mcp.tool(name="push_config")
async def push_config(params: ConfigCommand) -> dict:
    """
    Push configuration commands to one or more devices.
    """

    start = time.perf_counter()

    # Check for any forbidden commands
    validate_commands(params.commands)

    tasks = []

    for dev_name in params.devices:
        device = devices.get(dev_name)
        tasks.append(
            asyncio.create_task(
                push_config_to_device(dev_name, device, params.commands)
            )
        )

    results = {}

    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for item in completed:
        if isinstance(item, Exception):
            continue
        dev_name, result = item
        results[dev_name] = result

    end = time.perf_counter()
    results["execution_time_seconds"] = round(end - start, 2)
    return results

# Returns the expected network intent defined in INTENT.json (source of truth)
@mcp.tool(name="get_intent")
async def get_intent(params: EmptyInput) -> dict:
    """
    Return the desired network intent.
    """
    intent_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "intent",
        "INTENT.json"
    )

    if not os.path.exists(intent_file):
        raise RuntimeError("INTENT.json not found")

    with open(intent_file) as f:
        return json.load(f)

# Run the MCP Server
if __name__ == "__main__":
    mcp.run()