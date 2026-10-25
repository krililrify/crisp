from app.db import Session
from app.services import setting
from app.security import decrypt

def test_saving_telegram_preserves_registered_webhook_secret(admin, client, monkeypatch):
    monkeypatch.setattr("app.admin.tg", lambda *a, **kw: True)
    config = {'bot_token': 'test-token', 'chat_id': '-100123456', 'admin_ids': [123]}
    assert admin.put('/api/admin/telegram', json=config).status_code == 200
    with Session() as db:
        original = decrypt(setting(db, 'telegram')['secret'])
    config['bot_token'] = ''
    config['admin_ids'] = [123, 456]
    assert admin.put('/api/admin/telegram', json=config).status_code == 200
    with Session() as db:
        assert decrypt(setting(db, 'telegram')['secret']) == original
    response = client.post('/api/telegram/webhook', json={'update_id': 12345}, headers={'X-Telegram-Bot-Api-Secret-Token': original})
    assert response.status_code == 200
    config['webhook_secret'] = 'explicit-secret-change'
    assert admin.put('/api/admin/telegram', json=config).status_code == 200
    with Session() as db:
        assert decrypt(setting(db, 'telegram')['secret']) == 'explicit-secret-change'
