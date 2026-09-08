# Ei-GDA V14: Calling the Local Model from Google Colab

Ei-GDA uses:

```text
http://10.80.39.43:8087/v1/chat/completions
```

This is a private-network IP address. **Google Colab normally cannot reach `10.80.39.43` directly** unless the Colab runtime has a VPN/tunnel or the service is exposed through a secure reachable endpoint.

## Minimal Colab test

```python
import requests

URL = "http://10.80.39.43:8087/v1/chat/completions"

# If the server exposes /v1/models, discover a model first.
models_url = URL.replace("/chat/completions", "/models")
try:
    models = requests.get(models_url, timeout=20).json()["data"]
    model = models[0]["id"]
except Exception:
    model = "local-model"

payload = {
    "model": model,
    "temperature": 0,
    "messages": [
        {"role": "user", "content": "Return JSON: {\"status\": \"ok\"}"}
    ]
}

r = requests.post(URL, json=payload, timeout=120)
r.raise_for_status()
print(r.json())
```

No API key is required by Ei-GDA V14.

## Testing Ei-GDA scoring logic in Colab

Upload/copy these modules:

```text
services/local_model_service.py
services/scoring_service.py
services/kg_service.py
models.py
utils.py
```

For full application execution, a MySQL database is also required. For algorithm experiments, it is usually easier to export Test Suite/Standard Items to CSV/JSON and call the local model directly from the notebook.

## Recommended secure options for Colab

- Organization VPN that routes the Colab runtime to the private network, if supported.
- A temporary authenticated HTTPS reverse proxy managed by the organization.
- Run Jupyter locally/on-premise instead of public Colab when working with confidential documents.

Do not expose the unauthenticated local-model endpoint directly to the public Internet.
