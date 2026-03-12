import os

directory = r"d:\sem4\openalgo\restx_api"
target_files = [
    "cancel_order.py",
    "close_position.py",
    "cancel_all_order.py",
    "basket_order.py",
    "place_order.py",
    "modify_order.py"
]

for fname in target_files:
    filepath = os.path.join(directory, fname)
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    in_except = False
    except_indent = 0
    new_lines = []
    
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        
        if stripped.startswith("except ") or stripped == "except:":
            in_except = True
            except_indent = indent
            new_lines.append(line)
            continue
            
        if in_except:
            if stripped == "":
                new_lines.append(line)
                continue
            if indent <= except_indent:
                in_except = False
            elif 'logger.error(' in line:
                line = line.replace('logger.error(', 'logger.exception(')
                
        new_lines.append(line)
        
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Fixed {fname}")
