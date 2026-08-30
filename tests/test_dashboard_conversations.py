# Simulation : patient Karim (entré via Meta) prend RDV et s'arrête au choix du créneau
# → doit apparaître dans les "conversations en cours" du dashboard.
import httpx

API = "http://127.0.0.1:8000"


def meta_msg(text: str, mid: str) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": 999999999},
                    "contacts": [{"wa_id": "21269999999", "profile": {"name": "Karim"}}],
                    "messages": [{"from": "21269999999", "id": mid, "type": "text",
                                  "text": {"body": text}}],
                },
            }],
        }],
    }


for text, mid in [("1", "m1"), ("1", "m2")]:
    r = httpx.post(f"{API}/webhook", json=meta_msg(text, mid))
    r.raise_for_status()
    print(f"Karim tape « {text} » → {r.json()['summary']['messages'][-1]['replied']}")

import sys

sys.path.insert(0, ".")
from tests.auth_helper import auth_headers

r = httpx.get(
    f"{API}/public/dashboard/demo-cabinet-rabat/conversations",
    headers=auth_headers(),
)
r.raise_for_status()
print("\nconversations en cours :", r.json())
