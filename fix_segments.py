import json
import os

file_path = '.tmp/stanford_cs230_autumn_2025_lecture_1_introduction_to_deep_learning/translated.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

fixes = {
    677: '大學生，然後說：「喔，我的',
    710: '你會怎麼做，然後看看你是否',
    961: '敏感資訊，那麼除非你'
}

for x in data:
    if x['index'] in fixes:
        print(f"Fixing {x['index']}: {x['translation']} -> {fixes[x['index']]}")
        x['translation'] = fixes[x['index']]

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
