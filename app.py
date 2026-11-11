"""ESQUADRA Commerce — loja virtual + gestão comercial para esquadrias."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('ESQUADRA_DATA_DIR', ROOT / 'data'))
DATA.mkdir(parents=True, exist_ok=True)
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(exist_ok=True)
DB = DATA / 'esquadra.sqlite3'
SECRET_FILE = DATA / '.session_secret'
if not SECRET_FILE.exists():
    SECRET_FILE.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass

app = FastAPI(title='ESQUADRA Commerce', version='1.0.0', docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_FILE.read_text(encoding='utf-8').strip(), same_site='lax', https_only=os.getenv('COOKIE_SECURE') == '1')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
app.mount('/media', StaticFiles(directory=UPLOADS), name='media')

CATEGORIES = ['Portas de alumínio', 'Janelas de alumínio', 'Portas de madeira', 'Janelas de madeira', 'Portas sacada', 'Balcões']
SAMPLE_PRODUCTS = [
    ('PA-001', 'Porta de alumínio lambril', 'Portas de alumínio', 'Elegância e resistência com acabamento de alto padrão.', '210 × 80 cm', 89900, 12, 'porta-aluminio.svg'),
    ('JA-002', 'Janela de correr 2 folhas', 'Janelas de alumínio', 'Leveza, ventilação e luminosidade para todos os ambientes.', '120 × 100 cm', 67900, 18, 'janela-aluminio.svg'),
    ('PS-003', 'Porta sacada 4 folhas', 'Portas sacada', 'Amplitude e integração de espaços com deslizamento suave.', '210 × 200 cm', 189900, 8, 'porta-sacada.svg'),
    ('PM-004', 'Porta lisa de madeira', 'Portas de madeira', 'Design atemporal para ambientes aconchegantes.', '210 × 80 cm', 45900, 15, 'porta-madeira.svg'),
    ('BA-005', 'Balcão de alumínio 3 folhas', 'Balcões', 'Solução prática para cozinhas e áreas de serviço.', '120 × 100 cm', 74900, 10, 'balcao.svg'),
    ('JM-006', 'Janela de madeira veneziana', 'Janelas de madeira', 'Charme clássico com ventilação e acabamento natural.', '120 × 100 cm', 98900, 6, 'janela-madeira.svg'),
    ('JA-007', 'Janela maxim-ar preta', 'Janelas de alumínio', 'Linhas minimalistas para projetos contemporâneos.', '60 × 60 cm', 38900, 21, 'janela-aluminio.svg'),
    ('PA-008', 'Porta de giro preta com vidro', 'Portas de alumínio', 'Modernidade e iluminação sem abrir mão da robustez.', '210 × 90 cm', 129900, 5, 'porta-sacada.svg'),
]


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('PRAGMA journal_mode = WAL')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def seed():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', dimension TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL,
          stock INTEGER NOT NULL DEFAULT 0, image_url TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
          email TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
          id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE NOT NULL, customer_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'novo', payment_method TEXT NOT NULL DEFAULT 'a combinar',
          subtotal_cents INTEGER NOT NULL, discount_cents INTEGER NOT NULL DEFAULT 0, total_cents INTEGER NOT NULL,
          notes TEXT NOT NULL DEFAULT '', source TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
          FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS order_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
          name TEXT NOT NULL, dimension TEXT NOT NULL DEFAULT '', sku TEXT NOT NULL,
          quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL,
          FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        );
        ''')
        defaults = {
          'store_name': 'ESQUADRA', 'company_name': 'Sua empresa de esquadrias',
          'document': '', 'phone': '(11) 99999-9999', 'email': 'contato@exemplo.com',
          'address': 'Seu endereço comercial', 'instagram': '@suaempresa',
          'tagline': 'Design que transforma espaços.', 'receipt_title': 'COMPROVANTE DE VENDA',
          'receipt_footer': 'Obrigado pela preferência! Este documento é um comprovante comercial, sem valor fiscal.',
          'logo_url': '', 'hero_note': 'PORTAS, JANELAS E SOLUÇÕES SOB MEDIDA',
        }
        for k, v in defaults.items():
            c.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (k,v))
        if not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
            for sku, name, cat, desc, dim, price, stock, img in SAMPLE_PRODUCTS:
                c.execute('''INSERT INTO products(sku,name,category,description,dimension,price_cents,stock,image_url,active,created_at)
                  VALUES(?,?,?,?,?,?,?,?,1,?)''', (sku,name,cat,desc,dim,price,stock,'/static/img/'+img,now_iso()))
        if os.getenv('DEMO_SEED') == '1' and not c.execute('SELECT 1 FROM orders LIMIT 1').fetchone():
            samples = [
                ('Mariana Costa','(11) 98844-1020','pedido entregue', 'entregue',1,2,'pix'),
                ('Carlos Ferreira','(11) 97730-6642','obra residencial', 'em produção',3,1,'transferência'),
                ('Ana Ribeiro','(11) 96640-2187','retirada em loja', 'confirmado',4,2,'cartão na loja'),
                ('Roberto Mendes','(11) 95537-0982','previsão a confirmar', 'novo',5,2,'a combinar'),
                ('Julia Nascimento','(11) 94420-1034','visita técnica', 'novo',6,1,'a combinar'),
            ]
            for i, (name, phone, note, status, pid, qty, payment) in enumerate(samples):
                c.execute('INSERT INTO customers(name,phone,created_at) VALUES(?,?,?)', (name,phone,now_iso()))
                cid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                p = c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
                num = f'PED-{i+1:05d}'
                total = p['price_cents']*qty
                c.execute('''INSERT INTO orders(number,customer_id,status,payment_method,subtotal_cents,total_cents,notes,source,is_demo,created_at)
                   VALUES(?,?,?,?,?,?,?,?,1,?)''', (num,cid,status,payment,total,total,note,'demonstração',now_iso()))
                oid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
                c.execute('INSERT INTO order_items(order_id,product_id,name,dimension,sku,quantity,unit_price_cents) VALUES(?,?,?,?,?,?,?)',
                   (oid,pid,p['name'],p['dimension'],p['sku'],qty,p['price_cents']))

seed()


def settings_dict(c):
    return {r['key']:r['value'] for r in c.execute('SELECT * FROM settings').fetchall()}


def as_dict(row):
    return dict(row) if row else None


def logged_in(req: Request) -> bool:
    return bool(req.session.get('admin_id'))


def require_admin(req: Request):
    if not logged_in(req):
        raise HTTPException(401, 'Faça login para acessar o painel.')


def hash_password(password: str, salt: str):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 260_000).hex()


def provision_public_admin():
    """Bootstrap the first administrator using secrets set in the hosting dashboard.

    A public deployment must never let the first visitor claim the administrator account.
    Environment passwords are used only on first initialization; only a salted hash is stored.
    """
    if os.getenv('ESQUADRA_PUBLIC_DEPLOYMENT') != '1':
        return
    with db() as c:
        if c.execute('SELECT 1 FROM admins LIMIT 1').fetchone():
            return
        username = os.getenv('ESQUADRA_ADMIN_USERNAME', '').strip()
        password = os.getenv('ESQUADRA_ADMIN_PASSWORD', '')
        if len(username) < 3 or len(password) < 16:
            raise RuntimeError('Para iniciar em producao, configure ESQUADRA_ADMIN_USERNAME (min. 3 caracteres) e ESQUADRA_ADMIN_PASSWORD (min. 16 caracteres) nas variaveis de ambiente da hospedagem.')
        salt = secrets.token_hex(16)
        c.execute('INSERT INTO admins(username,salt,password_hash) VALUES(?,?,?)',
                  (username, salt, hash_password(password, salt)))


provision_public_admin()


def money_cents(value):
    try:
        val = Decimal(str(value))
        cents = int((val*100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except Exception:
        raise HTTPException(422, 'Preço inválido.')
    if cents < 0 or cents > 10**11:
        raise HTTPException(422, 'Preço fora do intervalo permitido.')
    return cents


def get_order(c, order_id):
    r = c.execute('''SELECT o.*, cu.name customer_name, cu.phone customer_phone,
      cu.email customer_email, cu.address customer_address FROM orders o
      JOIN customers cu ON cu.id=o.customer_id WHERE o.id=?''',(order_id,)).fetchone()
    if not r: raise HTTPException(404, 'Pedido não encontrado.')
    d = dict(r)
    d['items'] = [dict(x) for x in c.execute('SELECT * FROM order_items WHERE order_id=?',(order_id,)).fetchall()]
    return d


class AuthPayload(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=200)


class ProductPayload(BaseModel):
    sku: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=180)
    category: str
    description: str = Field(default='', max_length=1400)
    dimension: str = Field(default='', max_length=80)
    price: float = Field(ge=0, le=999999999)
    stock: int = Field(ge=0, le=1000000)
    active: bool = True


class OrderLine(BaseModel):
    product_id: int
    quantity: int = Field(ge=1, le=1000)


class NewOrder(BaseModel):
    customer_name: str = Field(min_length=2, max_length=180)
    phone: str = Field(default='', max_length=60)
    email: str = Field(default='', max_length=180)
    address: str = Field(default='', max_length=500)
    payment_method: str = Field(default='a combinar', max_length=80)
    notes: str = Field(default='', max_length=1000)
    discount: float = Field(default=0, ge=0)
    items: list[OrderLine] = Field(min_length=1, max_length=80)


class StatusPayload(BaseModel):
    status: Literal['novo','confirmado','em produção','entregue','cancelado']


class SettingsPayload(BaseModel):
    store_name: str = Field(min_length=2,max_length=80)
    company_name: str = Field(default='',max_length=180)
    document: str = Field(default='',max_length=60)
    phone: str = Field(default='',max_length=60)
    email: str = Field(default='',max_length=180)
    address: str = Field(default='',max_length=400)
    instagram: str = Field(default='',max_length=90)
    tagline: str = Field(default='',max_length=160)
    receipt_title: str = Field(default='COMPROVANTE DE VENDA',max_length=100)
    receipt_footer: str = Field(default='',max_length=500)
    hero_note: str = Field(default='',max_length=160)


@app.get('/', response_class=HTMLResponse)
def store():
    return FileResponse(ROOT / 'templates/store.html')


@app.get('/admin', response_class=HTMLResponse)
def admin():
    return FileResponse(ROOT / 'templates/admin.html')


@app.get('/api/catalog')
def catalog():
    with db() as c:
        return {'products':[dict(x) for x in c.execute('SELECT * FROM products WHERE active=1 ORDER BY id DESC').fetchall()],
                'categories':CATEGORIES, 'settings':settings_dict(c)}


@app.get('/api/admin/me')
def me(req:Request):
    with db() as c:
        setup = bool(c.execute('SELECT 1 FROM admins LIMIT 1').fetchone())
    return {'authenticated':logged_in(req),'needs_setup':not setup,'username':req.session.get('username')}


@app.post('/api/admin/setup')
def setup(req:Request, body:AuthPayload):
    if os.getenv('ESQUADRA_PUBLIC_DEPLOYMENT') == '1':
        raise HTTPException(403, 'Configuracao inicial desabilitada na hospedagem publica.')
    with db() as c:
        if c.execute('SELECT 1 FROM admins LIMIT 1').fetchone():
            raise HTTPException(403,'Configuração inicial já realizada.')
        salt = secrets.token_hex(16)
        c.execute('INSERT INTO admins(username,salt,password_hash) VALUES(?,?,?)',
                  (body.username.strip(),salt,hash_password(body.password,salt)))
        aid = c.execute('SELECT last_insert_rowid()').fetchone()[0]
    req.session['admin_id'] = aid
    req.session['username'] = body.username.strip()
    return {'ok': True}


@app.post('/api/admin/login')
def login(req:Request, body:AuthPayload):
    with db() as c:
        row = c.execute('SELECT * FROM admins WHERE username=?',(body.username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row['password_hash'], hash_password(body.password,row['salt'])):
        raise HTTPException(401,'Usuário ou senha incorretos.')
    req.session.clear()
    req.session['admin_id'] = row['id']
    req.session['username'] = row['username']
    return {'ok':True}


@app.post('/api/admin/logout')
def logout(req:Request):
    req.session.clear()
    return {'ok':True}


@app.get('/api/admin/summary')
def summary(req:Request):
    require_admin(req)
    with db() as c:
        stats = c.execute('''SELECT COUNT(*) order_count, COALESCE(SUM(CASE WHEN status != 'cancelado' THEN total_cents ELSE 0 END),0) revenue,
          SUM(CASE WHEN status='novo' THEN 1 ELSE 0 END) new_count FROM orders''').fetchone()
        product_count = c.execute('SELECT COUNT(*) FROM products WHERE active=1').fetchone()[0]
        customer_count = c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]
        low_stock = [dict(x) for x in c.execute('SELECT * FROM products WHERE stock<=5 AND active=1 ORDER BY stock LIMIT 6').fetchall()]
        recent = [get_order(c,x['id']) for x in c.execute('SELECT id FROM orders ORDER BY id DESC LIMIT 7').fetchall()]
        categories = [dict(x) for x in c.execute('SELECT category, COUNT(*) total FROM products WHERE active=1 GROUP BY category ORDER BY total DESC').fetchall()]
        demo_count = c.execute('SELECT COUNT(*) FROM orders WHERE is_demo=1').fetchone()[0]
        return {'stats':{**dict(stats),'product_count':product_count,'customer_count':customer_count},
                'recent_orders':recent,'low_stock':low_stock,'categories':categories,'demo_count':demo_count}


@app.get('/api/admin/products')
def all_products(req:Request):
    require_admin(req)
    with db() as c:
        return {'products':[dict(x) for x in c.execute('SELECT * FROM products ORDER BY id DESC').fetchall()], 'categories':CATEGORIES}


@app.post('/api/admin/products')
def add_product(req:Request, body:ProductPayload):
    require_admin(req)
    if body.category not in CATEGORIES: raise HTTPException(422,'Categoria inválida.')
    with db() as c:
        try:
            cur=c.execute('''INSERT INTO products(sku,name,category,description,dimension,price_cents,stock,active,created_at)
              VALUES(?,?,?,?,?,?,?,?,?)''', (body.sku.strip(),body.name.strip(),body.category,body.description,body.dimension,
                money_cents(body.price),body.stock,int(body.active),now_iso()))
        except sqlite3.IntegrityError: raise HTTPException(409,'Já existe produto com este SKU.')
        return {'product':as_dict(c.execute('SELECT * FROM products WHERE id=?',(cur.lastrowid,)).fetchone())}


@app.put('/api/admin/products/{pid}')
def edit_product(pid:int,req:Request,body:ProductPayload):
    require_admin(req)
    if body.category not in CATEGORIES: raise HTTPException(422,'Categoria inválida.')
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone(): raise HTTPException(404,'Produto não encontrado.')
        try:
            c.execute('''UPDATE products SET sku=?,name=?,category=?,description=?,dimension=?,price_cents=?,stock=?,active=? WHERE id=?''',
                      (body.sku.strip(),body.name.strip(),body.category,body.description,body.dimension,money_cents(body.price),body.stock,int(body.active),pid))
        except sqlite3.IntegrityError: raise HTTPException(409,'Já existe produto com este SKU.')
        return {'product':as_dict(c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone())}


async def safe_image_upload(file:UploadFile, prefix:str):
    data = await file.read(5*1024*1024+1)
    if not data or len(data)>5*1024*1024: raise HTTPException(422,'A imagem precisa ter até 5 MB.')
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        if img.format not in ('JPEG','PNG','WEBP') or img.width>8000 or img.height>8000:
            raise ValueError('Formato ou dimensões inválidas')
        img = img.convert('RGB')
        img.thumbnail((1800,1800))
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(422,'Envie uma imagem JPG, PNG ou WebP válida.')
    filename = f'{prefix}-{uuid.uuid4().hex}.jpg'
    path = UPLOADS / filename
    img.save(path,format='JPEG',quality=88,optimize=True)
    return '/media/'+filename


@app.post('/api/admin/products/{pid}/image')
async def upload_product_image(pid:int,req:Request,file:UploadFile=File(...)):
    require_admin(req)
    with db() as c:
        old = c.execute('SELECT image_url FROM products WHERE id=?',(pid,)).fetchone()
        if not old: raise HTTPException(404,'Produto não encontrado.')
    url=await safe_image_upload(file,'produto')
    with db() as c:
        c.execute('UPDATE products SET image_url=? WHERE id=?',(url,pid))
    return {'image_url':url}


@app.get('/api/admin/customers')
def customers(req:Request):
    require_admin(req)
    with db() as c:
        return {'customers':[dict(x) for x in c.execute('''SELECT cu.*,COUNT(o.id) order_count,
          COALESCE(SUM(CASE WHEN o.status!='cancelado' THEN o.total_cents ELSE 0 END),0) total_spent
          FROM customers cu LEFT JOIN orders o ON o.customer_id=cu.id GROUP BY cu.id ORDER BY cu.id DESC''').fetchall()]}


def create_order(body:NewOrder,source:str):
    quantities = {}
    for line in body.items:
        quantities[line.product_id] = quantities.get(line.product_id,0)+line.quantity
    with db() as c:
        # Serializa a leitura e baixa de estoque para evitar vendas simultâneas acima do disponível.
        c.execute('BEGIN IMMEDIATE')
        product_items=[]
        for pid,qty in quantities.items():
            p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
            if not p: raise HTTPException(422,'Produto indisponível no catálogo.')
            if p['stock'] < qty: raise HTTPException(409,f'Estoque insuficiente para {p["name"]}. Disponível: {p["stock"]}.')
            product_items.append((p,qty))
        subtotal=sum(p['price_cents']*qty for p,qty in product_items)
        discount=money_cents(body.discount)
        if discount>subtotal: raise HTTPException(422,'Desconto não pode ultrapassar o valor do pedido.')
        customer=c.execute('SELECT * FROM customers WHERE phone=? ORDER BY id LIMIT 1',(body.phone.strip(),)).fetchone() if body.phone.strip() else None
        if customer:
            cid=customer['id']
            c.execute('UPDATE customers SET name=?,email=?,address=? WHERE id=?',
                      (body.customer_name.strip(),body.email.strip(),body.address.strip(),cid))
        else:
            cur=c.execute('INSERT INTO customers(name,phone,email,address,created_at) VALUES(?,?,?,?,?)',
                (body.customer_name.strip(),body.phone.strip(),body.email.strip(),body.address.strip(),now_iso()))
            cid=cur.lastrowid
        temp=f'TEMP-{uuid.uuid4().hex}'
        cur=c.execute('''INSERT INTO orders(number,customer_id,status,payment_method,subtotal_cents,discount_cents,total_cents,notes,source,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?)''', (temp,cid,'novo',body.payment_method,subtotal,discount,subtotal-discount,body.notes,source,now_iso()))
        oid=cur.lastrowid
        order_number=f'PED-{oid:05d}'
        c.execute('UPDATE orders SET number=? WHERE id=?',(order_number,oid))
        for p,qty in product_items:
            c.execute('''INSERT INTO order_items(order_id,product_id,name,dimension,sku,quantity,unit_price_cents)
            VALUES(?,?,?,?,?,?,?)''',(oid,p['id'],p['name'],p['dimension'],p['sku'],qty,p['price_cents']))
            c.execute('UPDATE products SET stock=stock-? WHERE id=?',(qty,p['id']))
        return get_order(c,oid)


@app.post('/api/checkout')
def checkout(body:NewOrder):
    order=create_order(body,'loja online')
    return {'ok':True,'number':order['number'],'total_cents':order['total_cents']}


@app.post('/api/admin/orders')
def admin_order(req:Request,body:NewOrder):
    require_admin(req)
    return {'order':create_order(body,'venda manual')}


@app.get('/api/admin/orders')
def orders(req:Request):
    require_admin(req)
    with db() as c:
        return {'orders':[get_order(c,x['id']) for x in c.execute('SELECT id FROM orders ORDER BY id DESC').fetchall()]}


@app.patch('/api/admin/orders/{oid}/status')
def change_status(oid:int,req:Request,body:StatusPayload):
    require_admin(req)
    with db() as c:
        o=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
        if not o: raise HTTPException(404,'Pedido não encontrado.')
        if body.status=='cancelado' and o['status']!='cancelado':
            for item in c.execute('SELECT * FROM order_items WHERE order_id=?',(oid,)).fetchall():
                c.execute('UPDATE products SET stock=stock+? WHERE id=?',(item['quantity'],item['product_id']))
        if o['status']=='cancelado' and body.status!='cancelado':
            for item in c.execute('SELECT * FROM order_items WHERE order_id=?',(oid,)).fetchall():
                p=c.execute('SELECT stock FROM products WHERE id=?',(item['product_id'],)).fetchone()
                if not p or p['stock']<item['quantity']: raise HTTPException(409,'Estoque insuficiente para reativar o pedido.')
                c.execute('UPDATE products SET stock=stock-? WHERE id=?',(item['quantity'],item['product_id']))
        c.execute('UPDATE orders SET status=? WHERE id=?',(body.status,oid))
        return {'order':get_order(c,oid)}


@app.get('/api/admin/settings')
def get_settings(req:Request):
    require_admin(req)
    with db() as c: return {'settings':settings_dict(c)}


@app.put('/api/admin/settings')
def set_settings(req:Request,body:SettingsPayload):
    require_admin(req)
    with db() as c:
        for k,v in body.model_dump().items():
            c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,v.strip()))
        return {'settings':settings_dict(c)}


@app.post('/api/admin/settings/logo')
async def upload_logo(req:Request,file:UploadFile=File(...)):
    require_admin(req)
    url=await safe_image_upload(file,'logo')
    with db() as c:
        c.execute("UPDATE settings SET value=? WHERE key='logo_url'",(url,))
    return {'logo_url':url}


@app.delete('/api/admin/demo-data')
def delete_demo(req:Request):
    require_admin(req)
    with db() as c:
        ids=[row[0] for row in c.execute('SELECT id FROM orders WHERE is_demo=1')]
        for oid in ids:
            c.execute('DELETE FROM order_items WHERE order_id=?',(oid,))
            c.execute('DELETE FROM orders WHERE id=?',(oid,))
        c.execute('DELETE FROM customers WHERE id NOT IN (SELECT DISTINCT customer_id FROM orders)')
    return {'removed':len(ids)}


def brl(cents:int):
    return 'R$ '+f'{cents/100:,.2f}'.replace(',','X').replace('.',',').replace('X','.')


def clean(text):
    return escape(str(text or '')).replace('\n','<br/>')


@app.get('/api/admin/orders/{oid}/receipt.pdf')
def receipt(oid:int,req:Request):
    require_admin(req)
    with db() as c:
        order=get_order(c,oid)
        info=settings_dict(c)
    buf=io.BytesIO()
    doc=SimpleDocTemplate(buf, pagesize=A4, leftMargin=42,rightMargin=42,topMargin=36,bottomMargin=38,
            title=f'{info["receipt_title"]} — {order["number"]}', author=info['store_name'])
    ink=colors.HexColor('#181A1D'); grey=colors.HexColor('#6E737A'); line=colors.HexColor('#E4E5E7')
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='BrandCustom',fontName='Helvetica-Bold',fontSize=20,leading=24,textColor=ink))
    styles.add(ParagraphStyle(name='SubCustom',fontName='Helvetica',fontSize=9,leading=13,textColor=grey))
    styles.add(ParagraphStyle(name='TitleCustom',fontName='Helvetica-Bold',fontSize=14,leading=17,textColor=ink))
    styles.add(ParagraphStyle(name='LabelCustom',fontName='Helvetica-Bold',fontSize=8,leading=12,textColor=grey))
    styles.add(ParagraphStyle(name='BodyCustom',fontName='Helvetica',fontSize=9,leading=14,textColor=ink))
    styles.add(ParagraphStyle(name='ItemCustom',fontName='Helvetica',fontSize=9,leading=13,textColor=ink))
    styles.add(ParagraphStyle(name='FooterCustom',fontName='Helvetica',fontSize=8,leading=12,textColor=grey,alignment=TA_CENTER))
    story=[]
    logo=None
    logo_url=info.get('logo_url','')
    if logo_url.startswith('/media/'):
        p=UPLOADS/Path(logo_url).name
        if p.exists():
            try:
                logo=RLImage(str(p),width=57,height=57,kind='proportional',hAlign='LEFT')
            except Exception: pass
    brand_data=[Paragraph(clean(info['store_name']),styles['BrandCustom']),Paragraph(clean(info['company_name']),styles['SubCustom']),
                *([Paragraph('CNPJ / CPF: '+clean(info['document']),styles['SubCustom'])] if info.get('document') else []),
                Paragraph(clean(info['address']),styles['SubCustom']),Paragraph(clean(info['phone'])+'  |  '+clean(info['email']),styles['SubCustom'])]
    brand_table=Table([[logo or '',brand_data]],colWidths=[72,440] if logo else [0,512])
    brand_table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),0),
      ('RIGHTPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),16),('LINEBELOW',(0,0),(-1,-1),1.1,ink)]))
    story.append(brand_table)
    story.append(Spacer(1,20))
    story.append(Paragraph(clean(info['receipt_title']),styles['TitleCustom']))
    story.append(Spacer(1,7))
    meta=Table([[Paragraph('PEDIDO',styles['LabelCustom']),Paragraph('DATA DA VENDA',styles['LabelCustom']),Paragraph('STATUS',styles['LabelCustom'])],
        [Paragraph(clean(order['number']),styles['BodyCustom']),Paragraph(clean(order['created_at'][:16].replace('T',' às ')),styles['BodyCustom']),
         Paragraph(clean(order['status']).upper(),styles['BodyCustom'])]],colWidths=[164,190,158])
    meta.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#F3F4F5')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
         ('LEFTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,0),11),('BOTTOMPADDING',(0,1),(-1,1),12)]))
    story.append(meta);story.append(Spacer(1,22))
    story.append(Paragraph('DADOS DO CLIENTE',styles['LabelCustom']))
    story.append(Spacer(1,6))
    story.append(Paragraph(clean(order['customer_name']),styles['BodyCustom']))
    if order['customer_phone']: story.append(Paragraph('Telefone: '+clean(order['customer_phone']),styles['SubCustom']))
    if order['customer_address']: story.append(Paragraph('Endereço: '+clean(order['customer_address']),styles['SubCustom']))
    story.append(Spacer(1,23))
    rows=[[Paragraph('PRODUTO',styles['LabelCustom']),Paragraph('QTD.',styles['LabelCustom']),
         Paragraph('UNITÁRIO',styles['LabelCustom']),Paragraph('TOTAL',styles['LabelCustom'])]]
    for item in order['items']:
        name=clean(item['name'])+'<br/><font color="#777D84" size="8">'+clean(item['sku'])+' · '+clean(item['dimension'])+'</font>'
        rows.append([Paragraph(name,styles['ItemCustom']),Paragraph(str(item['quantity']),styles['BodyCustom']),
          Paragraph(brl(item['unit_price_cents']),styles['BodyCustom']),Paragraph(brl(item['unit_price_cents']*item['quantity']),styles['BodyCustom'])])
    tab=Table(rows,colWidths=[257,40,101,114],repeatRows=1,hAlign='LEFT')
    tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#F3F4F5')),
      ('LINEBELOW',(0,0),(-1,0),1,ink),('LINEBELOW',(0,1),(-1,-1),.5,line),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
      ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),12)]))
    story.append(tab);story.append(Spacer(1,16))
    totals=Table([[Paragraph('Subtotal',styles['SubCustom']),Paragraph(brl(order['subtotal_cents']),styles['BodyCustom'])],
       [Paragraph('Desconto',styles['SubCustom']),Paragraph('- '+brl(order['discount_cents']),styles['BodyCustom'])],
       [Paragraph('TOTAL DO PEDIDO',styles['TitleCustom']),Paragraph(brl(order['total_cents']),styles['TitleCustom'])]],colWidths=[170,135],hAlign='RIGHT')
    totals.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('LINEABOVE',(0,2),(-1,2),1,ink),
      ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),8),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0)]))
    story.append(totals);story.append(Spacer(1,23))
    story.append(Paragraph('FORMA DE PAGAMENTO',styles['LabelCustom']))
    story.append(Paragraph(clean(order['payment_method']),styles['BodyCustom']))
    if order['notes']:
        story.append(Spacer(1,12));story.append(Paragraph('OBSERVAÇÕES',styles['LabelCustom']))
        story.append(Paragraph(clean(order['notes']),styles['BodyCustom']))
    story.append(Spacer(1,32))
    story.append(Paragraph(clean(info['receipt_footer']),styles['FooterCustom']))
    story.append(Spacer(1,7))
    story.append(Paragraph('DOCUMENTO COMERCIAL · NÃO SUBSTITUI NOTA FISCAL',styles['FooterCustom']))
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(buf,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{order["number"]}.pdf"'})


@app.get('/health')
def health():
    return {'status':'ok'}
