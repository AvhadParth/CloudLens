from pathlib import Path

from dotenv import load_dotenv

# Read backend/.env (MongoDB address, login secret) before any module looks at os.environ.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
