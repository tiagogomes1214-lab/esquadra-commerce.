import os,sys,tempfile,hmac,hashlib,time
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
with tempfile.TemporaryDirectory() as temp:
    os.environ['ESQUADRA_DATA_DIR']=temp
    os.environ.pop('ESQUADRA_PUBLIC_DEPLOYMENT',None)
    from app import app
    from importlib import import_module
    v3=import_module('v3')
    admin=TestClient(app);a=TestClient(app);other=TestClient(app)
    assert admin.post('/api/admin/setup',json={'username':'admin','password':'a-very-secure-long-secret'}).status_code==200
    for cl,email in [(a,'a@example.com'),(other,'b@example.com')]:
        assert cl.post('/api/customer/register',json={'name':'Cliente Teste','email':email,'password':'complex-password-12345'}).status_code==200
    pid=a.get('/api/catalog').json()['products'][0]['id']
    # No pricing shown until merchant configures it
    assert not a.post('/api/sales/estimate',json={'product_id':pid,'width_mm':1200,'height_mm':1000}).json()['available']
    assert a.put(f'/api/admin/sales/pricing/{pid}',json={'price_m2':500,'minimum':100,'black_pct':10,'premium_glass':50,'extra_leaf':20}).status_code==401
    assert admin.put(f'/api/admin/sales/pricing/{pid}',json={'price_m2':500,'minimum':100,'black_pct':10,'premium_glass':50,'extra_leaf':20}).status_code==200
    estimation=a.post('/api/sales/estimate',json={'product_id':pid,'width_mm':1200,'height_mm':1000,'quantity':2,'finish':'preto','glass':'temperado','leaves':3})
    assert estimation.status_code==200,estimation.text
    assert estimation.json()['unit_price_cents']==73000,estimation.json()
    assert admin.post('/api/admin/sales/shipping',json={'cep_prefix':'099','description':'Região teste','fee':49.9,'lead_days':5}).status_code==200
    assert admin.post('/api/admin/sales/coupons',json={'code':'ESQUADRA5','percent':5,'max_uses':1}).status_code==200
    price=a.get('/api/catalog').json()['products'][0]['price_cents']
    summary=a.post('/api/sales/preview',json={'items':[{'product_id':pid,'quantity':1}],'coupon':'ESQUADRA5','cep':'09900-000','delivery_mode':'entrega'})
    assert summary.status_code==200,summary.text
    assert summary.json()['total_cents']==price-price*5//100+4990
    # A browser cannot set discount, shipping or final price directly
    buy=a.post('/api/checkout',json={'customer_name':'Alterado','items':[{'product_id':pid,'quantity':1}],'coupon':'ESQUADRA5','cep':'09900-000','delivery_mode':'entrega'})
    assert buy.status_code==200,buy.text
    order=a.get('/api/customer/orders').json()['orders'][0]
    assert order['total_cents']==price-price*5//100+4990
    assert order['shipping_cents']==4990 and order['coupon_code']=='ESQUADRA5'
    assert a.post('/api/checkout',json={'customer_name':'Teste','items':[{'product_id':pid,'quantity':1}],'coupon':'ESQUADRA5'}).status_code==422
    assert other.get(f"/api/customer/orders/{order['id']}/online-payments").status_code==404
    # No payment link possible until merchant credentials and valid HTTPS base URL set
    assert a.post(f"/api/customer/orders/{order['id']}/mercadopago",json={'installment':'total'}).status_code==503
    os.environ.update(MP_ACCESS_TOKEN='TEST-TOKEN',MP_WEBHOOK_SECRET='test-webhook-secret',ESQUADRA_BASE_URL='https://example.com',MP_MODE='production')
    def mp_mock(method,url,token,**kwargs):
        if method=='POST':
            return {'id':'pref-test-123','init_point':'https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=123'}
        # Tie the server-side payment lookup to the intent ref stored in the database
        with v3.db() as c:
            row=c.execute('SELECT * FROM mp_intents ORDER BY id DESC LIMIT 1').fetchone()
        return {'external_reference':row['external_reference'],'status':'approved','currency_id':'BRL',
                'transaction_amount':row['amount_cents']/100}
    with patch.object(v3,'mp_request',side_effect=mp_mock):
        link=a.post(f"/api/customer/orders/{order['id']}/mercadopago",json={'installment':'entrada30'})
        assert link.status_code==200,link.text
        assert link.json()['amount_cents']==(order['total_cents']*30+99)//100
        assert other.post(f"/api/customer/orders/{order['id']}/mercadopago",json={'installment':'total'}).status_code==404
        webhook_body={'type':'payment','data':{'id':'123456789'}}
        reqid='request-987';ts=str(int(time.time()))
        manifest=f'id:123456789;request-id:{reqid};ts:{ts};'
        sig=hmac.new(b'test-webhook-secret',manifest.encode(),'sha256').hexdigest()
        headers={'x-signature':f'ts={ts},v1={sig}','x-request-id':reqid}
        url='/api/webhooks/mercadopago?data.id=123456789'
        assert a.post(url,json=webhook_body,headers={'x-signature':'bad','x-request-id':reqid}).status_code==401
        first=a.post(url,json=webhook_body,headers=headers)
        assert first.status_code==200,first.text
        second=a.post(url,json=webhook_body,headers=headers)
        assert second.status_code==200 and second.json().get('duplicate'),second.text
        paid=admin.get('/api/admin/finance').json()['paid_cents']
        assert paid==link.json()['amount_cents'],paid
        with v3.db() as c:
            assert c.execute('SELECT COUNT(*) FROM payments WHERE order_id=?',(order['id'],)).fetchone()[0]==1
        assert a.get(f"/api/customer/orders/{order['id']}/online-payments").status_code==200
    # Additional sales workflows
    assert admin.post('/api/admin/sales/tier',json={'customer_id':order['customer_id'],'tier':'profissional','discount_pct':10}).status_code==200
    prev=a.post('/api/sales/preview',json={'items':[{'product_id':pid,'quantity':1}]})
    assert prev.json()['discount_cents']==price*10//100,prev.json()
    assert admin.post('/api/admin/sales/opportunities',json={'customer_id':order['customer_id'],'title':'Obra do cliente','value':700}).status_code==200
    assert admin.get('/api/admin/sales/overview').status_code==200
    assert a.post('/api/customer/cart-draft',json={'consent':True,'items':[{'product_id':pid,'quantity':1}]}).status_code==200
    assert admin.get('/api/admin/sales/overview').json()['leads']
    assert a.post('/api/customer/cart-draft',json={'consent':False}).status_code==200
    assert not admin.get('/api/admin/sales/overview').json()['leads']
    assert other.post('/api/customer/sales/reviews',json={'product_id':pid,'order_id':order['id'],'stars':5,'comment':'Muito bom'}).status_code==403
print('OK: precificação, cupons, CEP, checkout, isolamento de dados, assinatura, idempotência, CRM e LGPD básica')
