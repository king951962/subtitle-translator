import json
import os

file_path = '.tmp/stanford_cs230_autumn_2025_lecture_3_full_cycle_of_a_dl_project/translated.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

fixes = {
    619: '對特定使用者做出不當回應',
    652: '戴著帽子。然後你可能會說：「所有',
    1347: '企業主會說：「不，你的'
}

for x in data:
    if x['index'] in fixes:
        print(f"Fixing {x['index']}...")
        x['translation'] = fixes[x['index']]

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
