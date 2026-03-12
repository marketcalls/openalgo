import os
import re

restx_api_dir = r"d:\sem4\openalgo\restx_api"
filename = "market_holidays.py"
filepath = os.path.join(restx_api_dir, filename)

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

lines = content.splitlines()
new_lines = []
modified = False

for i, line in enumerate(lines):
    if "try:" in line and not modified:
        # Check if the next non-empty line has request.json
        found_req_json = False
        for j in range(i+1, min(i+10, len(lines))):
            if "request.json" in lines[j]:
                found_req_json = True
                break
        
        if found_req_json:
            new_lines.append(line)
            indent = " " * (line.find("try:") + 4)
            new_lines.append(f"{indent}# Get request data")
            new_lines.append(f"{indent}data = request.json")
            new_lines.append("")
            new_lines.append(f"{indent}if data is None:")
            new_lines.append(f"{indent}    return make_response(")
            new_lines.append(f"{indent}        jsonify(")
            new_lines.append(f"{indent}            {{\"status\": \"error\", \"message\": \"Request body is missing or invalid JSON\"}}")
            new_lines.append(f"{indent}        ),")
            new_lines.append(f"{indent}        400,")
            new_lines.append(f"{indent}    )")
            new_lines.append("")
            modified = True
            continue

    if modified and "request.json" in line:
        new_lines.append(line.replace("request.json", "data"))
    else:
        new_lines.append(line)

if modified:
    with open(filepath + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")
    print(f"Proposed check for {filename}")
