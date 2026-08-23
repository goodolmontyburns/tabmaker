import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_root_or_docs():
    response = client.get("/docs")
    assert response.status_code == 200

def test_get_session_not_found():
    response = client.get("/session/non_existent_id_12345")
    assert response.status_code == 404

def test_save_notes_endpoint_not_found():
    response = client.post("/session/non_existent_id_12345/notes", json={"notes": []})
    assert response.status_code == 404
