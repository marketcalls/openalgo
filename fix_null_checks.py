import os
import re

def add_null_check(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if "if request.json is None:" in content or "request.json or {}" in content:
        return False

    lines = content.splitlines()
    new_lines = []
    modified = False
    
    for i, line in enumerate(lines):
        if "try:" in line and not modified:
            # Check if request.json is used inside this try block
            found_req_json = False
            for j in range(i+1, min(i+20, len(lines))):
                if "request.json" in lines[j]:
                    found_req_json = True
                    break
            
            if found_req_json:
                new_lines.append(line)
                indent = re.match(r"^(\s*)", line).group(1) + "    "
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
            # Replace request.json with data
            new_lines.append(line.replace("request.json", "data"))
        else:
            new_lines.append(line)

    if modified:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        return True
    return False

api_dir = r"d:\sem4\openalgo\restx_api"
files = [f for f in os.listdir(api_dir) if f.endswith(".py")]

for f in files:
    path = os.path.join(api_dir, f)
    if add_null_check(path):
        print(f"Fixed {f}")
