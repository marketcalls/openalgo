import os
import re

directory = r"d:\sem4\openalgo\restx_api"

for fname in os.listdir(directory):
    if not fname.endswith(".py"):
        continue
    filepath = os.path.join(directory, fname)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original_content = content
    
    # 1. Remove import traceback
    content = re.sub(r'^import traceback\r?\n?', '', content, flags=re.MULTILINE)

    # 2. Iterate lines to replace logger.error with logger.exception in except blocks,
    # and remove traceback.print_exc()
    lines = content.split('\n')
    new_lines = []
    in_except = False
    except_indent = 0
    
    for line in lines:
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        
        if stripped.startswith("except ") or stripped == "except:":
            in_except = True
            except_indent = current_indent
            new_lines.append(line)
            continue
            
        if in_except:
            if stripped == "":
                new_lines.append(line)
                continue
            if current_indent <= except_indent:
                in_except = False
            else:
                if 'logger.error(' in line:
                    line = line.replace('logger.error(', 'logger.exception(')
                if 'traceback.print_exc()' in line:
                    continue  # skip adding this line entirely
                
        new_lines.append(line)
                    
    content = '\n'.join(new_lines)
    
    # Final cleanup if there is double newline imported by deleting tracebacks
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    
    if content != original_content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Fixed {fname}")

