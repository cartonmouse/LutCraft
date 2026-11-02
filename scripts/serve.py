import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
load_dotenv(ROOT / ".env")

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8765")), workers=1
    )
