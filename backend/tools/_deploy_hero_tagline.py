import sys
from pathlib import Path
sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
import ssh_exec
LOCAL = Path(r"D:/CursorProjects/kupujpl-games/backend")
client = ssh_exec._connect()
sftp = client.open_sftp()
for rel in ["app/static/index.html", "app/static/style.css"]:
    sftp.put(str(LOCAL / rel), f"/opt/kupujpl-games/{rel}")
    print("ok", rel)
sftp.close()
client.close()
