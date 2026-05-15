import re

path = "str(Path(__file__).resolve().parent / 'searxng_search.py')"
with open(path, "r") as f:
    content = f.read()

content = content.replace(
    "LOCAL_SEARXNG = os.getenv('SEARXNG_LOCAL_URL', 'http://127.0.0.1:18080').rstrip('/')",
    "LOCAL_SEARXNG = os.getenv('SEARXNG_LOCAL_URL', 'http://127.0.0.1:8888').rstrip('/')")

with open(path, "w") as f:
    f.write(content)

print("✅ 端口从 18080 改为 8888")
