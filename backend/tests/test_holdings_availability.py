from test_circulation import client,seed,issue,close,session
from app.db import User
from app.security import password_hash


def test_catalogue_copy_follows_issue_and_return(client):
    readers,copies,rid=seed(2)
    url=f'/api/records/{rid}/copies'
    before=client.get(url).json()
    assert before['on_loan']==0
    assert all(c['availability']=='available' and c['can_edit'] for c in before['items'])
    loan=issue(client,readers[0],[copies[0]]).json()['loans'][0]
    after=client.get(url).json()
    assert after['active']==2 and after['on_loan']==1
    used,free=after['items']
    assert used['availability']=='on_loan' and not used['can_edit']
    assert used['loan']['id']==loan['id'] and used['loan']['reader_id']==readers[0]
    assert used['loan']['reader_name']=='Тест 0' and used['loan']['due_at']
    assert free['availability']=='available' and free['loan'] is None
    # Filtering/pagination must not change the whole-record totals.
    filtered=client.get(url+'?q=001&limit=1').json()
    assert filtered['on_loan']==1 and filtered['matched']==1
    assert issue(client,readers[1],[copies[0]],override=True,reason='Повторная выдача запрещена').status_code==409
    payload={k:used[k] for k in ('version','inventory_number','barcode','sigla','checked_on','note')}
    assert client.put('/api/copies/'+str(copies[0]),json=payload).status_code==409
    assert client.delete(f'/api/records/{rid}?version=1').status_code==409
    assert close(client,loan['id'],condition='good').status_code==200
    returned=client.get(url).json()
    assert returned['on_loan']==0
    assert returned['items'][0]['availability']=='available'
    assert returned['items'][0]['loan'] is None and returned['items'][0]['can_edit']
    assert issue(client,readers[1],[copies[0]]).status_code==200


def test_catalogue_viewer_sees_state_without_borrower_details(client):
    readers,copies,rid=seed(1)
    assert issue(client,readers[0],copies).status_code==200
    with session() as s:
        s.add(User(username='catalog-only',display_name='Каталогизатор',role='librarian',permissions=['catalog.view'],password_hash=password_hash('test-secret')))
        s.commit()
    auth=client.post('/api/auth/login',json={'username':'catalog-only','password':'test-secret'}).json()
    client.headers['X-CSRF-Token']=auth['csrf_token']
    response=client.get(f'/api/records/{rid}/copies')
    assert response.status_code==200,response.text
    item=response.json()['items'][0]
    assert item['availability']=='on_loan' and not item['can_edit'] and item['loan'] is None
    assert 'Тест 0' not in response.text
