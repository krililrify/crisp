from app.db import Session
from app.models import Message
from sqlalchemy import select

def test_initial_question_stored_and_profile_private(client, site):
    path = f"/api/sites/{site['id']}"
    for problem in ['12345', '     12345    ', '']:
        assert client.post(path+'/sessions', json={'email':'question@example.com','problem':problem}, headers={'Origin':'http://testserver'}).status_code == 422
    r = client.post(path+'/sessions', json={'email':'question@example.com','problem':'  这是我的第一个问题  '}, headers={'Origin':'http://testserver'})
    assert r.status_code == 200
    c = r.json(); headers={'Authorization':'Bearer '+c['token']}
    messages = client.get(path+'/messages', headers=headers).json()
    assert len(messages) == 1 and messages[0]['body'] == '这是我的第一个问题'
    assert c['email'] == 'question@example.com'
    assert client.get(path+'/me').status_code == 401
    assert client.get(path+'/me', headers=headers).json()['email'] == 'question@example.com'

def test_site_copy_settings(admin, client, site):
    data = dict(site, subtitle='人工在线', welcome_heading='欢迎咨询', welcome_icon='👋', business_hours='周一至周五 09:00–18:00', problem_prompt='请说明问题')
    assert admin.put('/api/admin/sites/'+site['id'], json=data).status_code == 200
    public = client.get('/api/sites/'+site['id']+'/public').json()
    for key in ['subtitle','welcome_heading','welcome_icon','business_hours','problem_prompt']:
        assert public[key] == data[key]
