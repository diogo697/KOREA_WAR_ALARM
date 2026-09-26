import json
import os
from urllib.request import Request, urlopen

headers = {}
if token := os.environ.get("KWA_API_TOKEN"):
    headers["Authorization"] = f"Bearer {token}"
request = Request("http://127.0.0.1:8080/api/v1/alert/simple", headers=headers)
with urlopen(request, timeout=5) as response:
    print(json.load(response))
