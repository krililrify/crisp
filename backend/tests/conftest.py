import os, tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "sqlite:///" + str(Path(tempfile.mkdtemp()) / "test.db")
)
os.environ["PUBLIC_URL"] = "http://testserver"
os.environ["COOKIE_SECURE"] = "false"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp()
from cryptography.fernet import Fernet

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Base, engine, Session
from app.models import AdminUser
from app.security import passwords


@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as db:
        db.add(
            AdminUser(
                username="admin", password_hash=passwords.hash("test-admin-password")
            )
        )
        db.commit()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    r = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "test-admin-password"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    client.headers.update(
        {"Origin": "http://testserver", "X-CSRF-Token": r.json()["csrf"]}
    )
    return client


@pytest.fixture
def site(admin):
    r = admin.post(
        "/api/admin/sites", json={"name": "测试站", "domains": ["https://example.com"]}
    )
    assert r.status_code == 200, r.text
    return r.json()


def start(client, site, email="a@example.com"):
    r = client.post(
        f"/api/sites/{site['id']}/sessions",
        json={"email": email},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def visitor_headers(s):
    return {"Authorization": "Bearer " + s["token"]}
