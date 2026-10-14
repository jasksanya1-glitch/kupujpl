import json
import pathlib
import re

p = pathlib.Path(
    r"C:\Users\Admin\.cursor\projects\d-CursorProjects\agent-transcripts"
    r"\164ebd71-c924-421f-a90e-da4d5c311f54\164ebd71-c924-421f-a90e-da4d5c311f54.jsonl"
)
with p.open(encoding="utf-8", errors="ignore") as f:
    for i, line in enumerate(f, 1):
        if i != 605:
            continue
        obj = json.loads(line)
        text = json.dumps(obj, ensure_ascii=False)
        # unescape common sequences for readability
        text = text.replace("\\n", "\n").replace('\\"', '"')
        for marker in ("FINAL REPORT", "FINAL ACCEPTANCE CHECKLIST", "ISSUE 1"):
            idx = text.find(marker)
            print("===", marker, "at", idx)
        # print from FINAL REPORT to end-ish
        idx = text.find("FINAL REPORT")
        if idx != -1:
            print(text[idx : idx + 4500])
        idx2 = text.find("FINAL ACCEPTANCE CHECKLIST")
        if idx2 != -1:
            print("\n\n==== CHECKLIST ====\n")
            print(text[idx2 : idx2 + 2500])
        break
