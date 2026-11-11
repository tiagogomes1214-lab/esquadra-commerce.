"""Smoke tests: execute with `python -m unittest discover -s tests -v`."""
import os, tempfile, unittest, sys
from pathlib import Path
from fastapi.testclient import TestClient

class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ['ESQUADRA_DATA_DIR']=cls.temp.name
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from app import app
        cls.app=app

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_customer_and_admin(self):
        a=TestClient(self.app);b=TestClient(self.app);adm=TestClient(self.app)
        self.assertEqual(a.get('/api/customer/orders').status_code,401)
        self.assertEqual(a.post('/api/customer/register',json={
          'name':'Alice Teste','email':'ALICE@example.com','phone':'11999999991','address':'Rua Alfa, 10','password':'senha-super-12345'
        }).status_code,200)
        self.assertEqual(b.post('/api/customer/register',json={
          'name':'Bruno Teste','email':'bruno@example.com','phone':'11999999992','address':'Rua Beta, 20','password':'outra-senha-12345'
        }).status_code,200)
        self.assertEqual(b.post('/api/customer/register',json={
          'name':'Duplicado','email':'alice@example.com','password':'senha-segura-0000'
        }).status_code,409)
        p=a.get('/api/catalog').json()['products'][0]
        oid_resp=a.post('/api/checkout',json={'customer_name':'ignorado','items':[{'product_id':p['id'],'quantity':2}]})
        self.assertEqual(oid_resp.status_code,200,oid_resp.text)
        number=oid_resp.json()['number']
        self.assertEqual(TestClient(self.app).post('/api/checkout',json={'customer_name':'Teste','items':[{'product_id':p['id'],'quantity':1}]}).status_code,401)
        orders=a.get('/api/customer/orders').json()['orders'];self.assertEqual(len(orders),1)
        oid=orders[0]['id']
        self.assertEqual(orders[0]['status'],'novo')
        self.assertEqual(b.get('/api/customer/orders').json()['orders'],[])
        self.assertEqual(b.get(f'/api/customer/orders/{oid}').status_code,404)
        self.assertEqual(b.get(f'/api/customer/orders/{oid}/receipt.pdf').status_code,404)
        self.assertEqual(a.get(f'/api/customer/orders/{oid}/receipt.pdf').status_code,200)
        self.assertEqual(adm.post('/api/admin/setup',json={'username':'admin','password':'strong-password-xyz'}).status_code,200)
        # Nothing deducted while new.
        self.assertEqual(a.get('/api/catalog').json()['products'][0]['stock'],p['stock'])
        r=adm.patch(f'/api/admin/orders/{oid}/status',json={'status':'confirmado','note':'Pagamento por conferir'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(a.get('/api/catalog').json()['products'][0]['stock'],p['stock']-2)
        self.assertEqual(len(a.get('/api/customer/orders').json()['orders'][0]['events']),2)
        r=adm.post(f'/api/admin/orders/{oid}/payments',json={'amount':30,'method':'Pix'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(adm.patch(f'/api/admin/orders/{oid}/status',json={'status':'cancelado'}).status_code,409)
        self.assertEqual(adm.post(f'/api/admin/orders/{oid}/payments',json={'amount':30,'method':'Pix','refund':True}).status_code,200)
        self.assertEqual(adm.patch(f'/api/admin/orders/{oid}/status',json={'status':'cancelado'}).status_code,200)
        self.assertEqual(a.get('/api/catalog').json()['products'][0]['stock'],p['stock'])
        self.assertEqual(adm.patch(f'/api/admin/orders/{oid}/status',json={'status':'confirmado'}).status_code,409)
        # Approval of personalized quote without stock deduction.
        q=a.post('/api/customer/quotes',json={'product_id':p['id'],'width_mm':1200,'height_mm':2200,'quantity':1,'finish':'Preto'}).json()['quote']
        self.assertEqual(b.get('/api/customer/quotes').json()['quotes'],[])
        self.assertEqual(b.post(f"/api/customer/quotes/{q['id']}/approve").status_code,404)
        self.assertEqual(adm.patch(f"/api/admin/quotes/{q['id']}/price",json={'unit_price':1500.00,'valid_until':'2099-12-31'}).status_code,200)
        self.assertEqual(a.get(f"/api/customer/quotes/{q['id']}/pdf").status_code,200)
        self.assertEqual(b.get(f"/api/customer/quotes/{q['id']}/pdf").status_code,404)
        self.assertEqual(a.post(f"/api/customer/quotes/{q['id']}/approve").status_code,200)
        self.assertEqual(a.post(f"/api/customer/quotes/{q['id']}/approve").status_code,409)
        self.assertEqual(len(a.get('/api/customer/orders').json()['orders']),2)
        # Stock and purchases and protected admin functions
        self.assertEqual(a.get('/api/admin/finance').status_code,401)
        sp=adm.post('/api/admin/suppliers',json={'name':'Fornecedor Teste'}).json()['id']
        pu=adm.post('/api/admin/purchases',json={'supplier_id':sp,'product_id':p['id'],'quantity':4,'unit_cost':100}).json()['id']
        self.assertEqual(adm.post(f'/api/admin/purchases/{pu}/receive').status_code,200)
        self.assertEqual(adm.post(f'/api/admin/purchases/{pu}/receive').status_code,409)
        self.assertEqual(a.get('/api/catalog').json()['products'][0]['stock'],p['stock']+4)
        self.assertEqual(adm.get('/api/admin/report.csv').status_code,200)
        self.assertEqual(adm.get(f'/api/admin/orders/{oid}/delivery.pdf').status_code,200)
        self.assertEqual(adm.put(f'/api/admin/products/{p["id"]}/specs',json={
           'width_mm':1200,'height_mm':1000,'material':'alumínio','finish':'preto','made_to_order':False
        }).status_code,200)
        self.assertEqual(adm.get(f'/api/products/{p["id"]}/details').json()['specs']['width_mm'],1200)
        self.assertEqual(adm.post('/api/admin/expenses',json={'name':'Despesa de teste','amount':99,'paid':True}).status_code,200)
        self.assertEqual(adm.post('/api/admin/stock/adjust',json={'product_id':p['id'],'change_qty':-1,'reason':'Conferência de inventário'}).status_code,200)
        self.assertEqual(adm.post('/api/admin/operations',json={'order_id':oid,'kind':'entrega','scheduled_for':'2026-12-10'}).status_code,200)
        self.assertEqual(adm.post('/api/admin/warranties',json={'order_id':oid,'description':'Acompanhar ajuste de dobradiça'}).status_code,200)
        self.assertEqual(adm.post('/api/admin/staff',json={'name':'Funcionário Teste','role':'Estoque'}).status_code,200)
        # re-login with normalized email
        self.assertEqual(a.post('/api/customer/logout').status_code,200)
        self.assertEqual(a.get('/api/customer/orders').status_code,401)
        self.assertEqual(a.post('/api/customer/login',json={'email':'ALICE@example.com','password':'senha-super-12345'}).status_code,200)
        self.assertEqual(len(a.get('/api/customer/orders').json()['orders']),2)

if __name__=='__main__':unittest.main()
