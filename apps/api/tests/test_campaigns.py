from fastapi.testclient import TestClient

from app import create_app
from services.campaign_configs import CAMPAIGNS

app = create_app()
client = TestClient(app)


def _hdrs():
    import os
    return {"X-API-Key": os.environ.get("MODELFORGE_API_KEY", "")}


def test_list_campaigns_returns_all_known():
    resp = client.get("/api/campaigns", headers=_hdrs())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {c["id"] for c in body["campaigns"]}
    assert ids == set(CAMPAIGNS.keys())


def test_get_campaign_returns_404_for_unknown():
    resp = client.get("/api/campaigns/does-not-exist", headers=_hdrs())
    assert resp.status_code == 404


def test_each_campaign_has_description_and_experiments():
    for cid, cfg in CAMPAIGNS.items():
        assert cfg.get("description"), f"missing description for {cid}"
        assert isinstance(cfg.get("experiments"), list)
        assert len(cfg["experiments"]) > 0, f"no experiments for {cid}"
