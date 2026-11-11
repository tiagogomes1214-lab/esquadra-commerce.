"""Backward-compatible upgrades and public boot protections."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class DeploymentSafetyTests(unittest.TestCase):
    def run_script(self, code, path, public=False, creds=False):
        e={**os.environ,'ESQUADRA_DATA_DIR':str(path),'PYTHONPATH':str(ROOT),
           'ESQUADRA_PUBLIC_DEPLOYMENT':'1' if public else '0','DEMO_SEED':'0'}
        e.pop('ESQUADRA_ADMIN_USERNAME',None);e.pop('ESQUADRA_ADMIN_PASSWORD',None)
        if creds:
            e.update(ESQUADRA_ADMIN_USERNAME='admin',ESQUADRA_ADMIN_PASSWORD='secure-startup-password-123456')
        return subprocess.run([sys.executable,'-c',code],env=e,capture_output=True,text=True)

    def test_public_first_run_requires_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            r=self.run_script('import app',d,public=True,creds=False)
            self.assertNotEqual(r.returncode,0)
            self.assertIn('ESQUADRA_ADMIN_USERNAME',r.stderr)
            r=self.run_script('from app import app; from fastapi.testclient import TestClient; c=TestClient(app); print(c.post("/api/admin/setup",json={"username":"hacker","password":"password123"}).status_code)',d,public=True,creds=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('403',r.stdout)

    def test_v1_unconfirmed_order_stock_not_charged_twice(self):
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'esquadra.sqlite3'
            con=sqlite3.connect(db)
            con.executescript('''
               CREATE TABLE products (id INTEGER PRIMARY KEY,sku TEXT UNIQUE NOT NULL,name TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',dimension TEXT NOT NULL DEFAULT '',price_cents INTEGER NOT NULL,stock INTEGER NOT NULL DEFAULT 0,image_url TEXT,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
               CREATE TABLE customers (id INTEGER PRIMARY KEY,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
               CREATE TABLE orders (id INTEGER PRIMARY KEY,number TEXT UNIQUE NOT NULL,customer_id INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'novo',payment_method TEXT NOT NULL DEFAULT 'a combinar',subtotal_cents INTEGER NOT NULL,discount_cents INTEGER NOT NULL DEFAULT 0,total_cents INTEGER NOT NULL,notes TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,is_demo INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
               CREATE TABLE order_items (id INTEGER PRIMARY KEY,order_id INTEGER NOT NULL,product_id INTEGER NOT NULL,name TEXT NOT NULL,dimension TEXT NOT NULL DEFAULT '',sku TEXT NOT NULL,quantity INTEGER NOT NULL,unit_price_cents INTEGER NOT NULL);
               INSERT INTO products (id,sku,name,category,price_cents,stock,created_at) VALUES (1,'JA-01','Janela','Janelas de alumínio',50000,3,'2026-11-01');
               INSERT INTO customers (id,name,phone,created_at) VALUES (1,'Cliente antigo','11111111','2026-11-01');
               INSERT INTO orders (id,number,customer_id,status,subtotal_cents,total_cents,source,created_at) VALUES (1,'PED-00001',1,'novo',100000,100000,'loja online','2026-11-01');
               INSERT INTO order_items (id,order_id,product_id,name,sku,quantity,unit_price_cents) VALUES (1,1,1,'Janela','JA-01',2,50000);
            ''')
            con.commit();con.close()
            code='''from app import app,db
from fastapi.testclient import TestClient
c=TestClient(app)
c.post('/api/admin/setup',json={'username':'admin','password':'password12345'})
r=c.patch('/api/admin/orders/1/status',json={'status':'confirmado'})
assert r.status_code==200,(r.status_code,r.text)
with db() as dbh: assert dbh.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]==3
r=c.patch('/api/admin/orders/1/status',json={'status':'cancelado'})
assert r.status_code==200,(r.status_code,r.text)
with db() as dbh: assert dbh.execute('SELECT stock FROM products WHERE id=1').fetchone()[0]==5
'''
            r=self.run_script(code,d)
            self.assertEqual(r.returncode,0,r.stderr)

if __name__=='__main__':unittest.main()
