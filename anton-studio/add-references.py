import json
import re

def remove_comments(json_str):
    return re.sub(r'^\s*//.*$', '', json_str, flags=re.MULTILINE)

pkgs = [
  'ui-ops-now',
  'ui-ops-automations',
  'ui-ops-approvals',
  'ui-ops-schedule',
  'ui-ops-memory',
  'ui-ops-learning',
  'ui-ops-alerts',
  'ui-ops-addons',
  'ui-ops-setup'
]

for filename in ['tsconfig.client.json', 'tsconfig.host.json']:
    with open(filename, 'r') as f:
        content = f.read()
    
    # Simple insertion right before the last "]". We don't even need to parse JSON.
    # We find the last "]" which closes the "references" array (since it's at the very end).
    
    last_bracket_idx = content.rfind(']')
    
    refs = ""
    for pkg in pkgs:
        path_str = f'./packages/client/{pkg}'
        if path_str not in content:
            refs += f'    {{ "path": "{path_str}" }},\n'
            
    if refs:
        new_content = content[:last_bracket_idx] + ",\n" + refs + content[last_bracket_idx:]
        # Fix comma before closing bracket if needed (we added a trailing comma, JSON doesn't like it)
        # Actually wait, tsconfig allows trailing commas, but let's be clean:
        new_content = new_content.replace('},\n  ]', '}\n  ]')
        with open(filename, 'w') as f:
            f.write(new_content)

print("done")
