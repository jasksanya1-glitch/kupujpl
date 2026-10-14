import json
import pathlib
import re

p = pathlib.Path(
    r"C:\Users\Admin\.cursor\projects\d-CursorProjects\agent-transcripts"
    r"\164ebd71-c924-421f-a90e-da4d5c311f54\164ebd71-c924-421f-a90e-da4d5c311f54.jsonl"
)
print("exists", p.exists(), "size", p.stat().st_size if p.exists() else 0)
keys = [
    "16-point",
    "16 point",
    "acceptance",
    "Raport",
    "hardcoded",
    "Final report",
    "store_count",
    "DOM order",
    "user brief",
    "Acceptance",
    "checklist",
]
found = 0
with p.open(encoding="utf-8", errors="ignore") as f:
    for i, line in enumerate(f, 1):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        role = obj.get("role") or obj.get("type") or ""
        text = json.dumps(obj, ensure_ascii=False)
        if not any(k.lower() in text.lower() for k in keys):
            continue
        # prefer user messages
        blob = text
        if "user" not in str(role).lower() and "user_query" not in text.lower():
            continue
        print("--- LINE", i, "role", role, "len", len(text))
        for k in keys:
            idx = text.lower().find(k.lower())
            if idx != -1:
                snippet = text[max(0, idx - 60) : idx + 220]
                snippet = re.sub(r"\s+", " ", snippet)
                print(" hit", k, ":", snippet[:300])
        found += 1
        if found >= 15:
            break
print("done found", found)
