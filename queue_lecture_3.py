import time
import os
import subprocess

file_to_wait = r"e:\antigravity\subtitle\output\stanford_cs230_autumn_2025_lecture_2_supervised_self_supervised_weakly_supervised_learning_1080p_quality_report.txt"

print(f"Waiting for Lecture 2 to finish: {file_to_wait}")

# Loop until the quality report for lecture 2 is created
while not os.path.exists(file_to_wait):
    time.sleep(30)

print("Lecture 2 finished! Starting Lecture 3 translation...")
subprocess.run([
    "uv", "run", "python", "tools/run.py",
    "input/Stanford CS230 _ Autumn 2025 _ Lecture 3_ Full Cycle of a DL project.srt"
], check=True)
print("Lecture 3 translation completed or errored.")
