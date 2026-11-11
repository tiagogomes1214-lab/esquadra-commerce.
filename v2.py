"""ESQUADRA Commerce 2.0: area do cliente, orcamentos e gestao avancada.
Sem gateway bancario ou autorizacao fiscal: pagamentos sao registros manuais.
"""
from __future__ import annotations
import hmac
import secrets
import sqlite3
from datetime import datetime
from fastapi import HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from app import (app, ROOT, db, now_iso, hash_password, require_admin,
                 money_cents, create_order, get_order, safe_image_upload,
                 CATEGORIES, UPLOADS, NewOrder, OrderLine, login_throttle, note_failed_login, clear_failed_login)


def migrate():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS customer_accounts (
            customer_id INTEGER PRIMARY KEY REFERENCES customers(id), email_normalized TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            status TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS stock_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL REFERENCES products(id),
            change_qty INTEGER NOT NULL,reason TEXT NOT NULL,order_id INTEGER,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id),
            amount_cents INTEGER NOT NULL,method TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,category TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,due_at TEXT,paid INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,number TEXT UNIQUE,customer_id INTEGER NOT NULL REFERENCES customers(id),
            product_id INTEGER REFERENCES products(id),product_name TEXT NOT NULL,sku TEXT NOT NULL,
            width_mm INTEGER,height_mm INTEGER,material TEXT NOT NULL DEFAULT '',finish TEXT NOT NULL DEFAULT '',
            glass TEXT NOT NULL DEFAULT '',quantity INTEGER NOT NULL,notes TEXT NOT NULL DEFAULT '',
            unit_price_cents INTEGER NOT NULL DEFAULT 0,total_cents INTEGER NOT NULL DEFAULT 0,
            valid_until TEXT,status TEXT NOT NULL DEFAULT 'solicitado',order_id INTEGER REFERENCES orders(id),
            created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,document TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,supplier_id INTEGER REFERENCES suppliers(id),
            product_id INTEGER NOT NULL REFERENCES products(id),quantity INTEGER NOT NULL,
            unit_cost_cents INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'pendente',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS product_specs (
            product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
            width_mm INTEGER,height_mm INTEGER,material TEXT NOT NULL DEFAULT '',finish TEXT NOT NULL DEFAULT '',
            glass TEXT NOT NULL DEFAULT '',opening TEXT NOT NULL DEFAULT '',warranty_months INTEGER DEFAULT 0,
            made_to_order INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS product_gallery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            image_url TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id),
            kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'agendado',assigned_to TEXT NOT NULL DEFAULT '',
            scheduled_for TEXT,notes TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS warranties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id),
            description TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'aberta',created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,role TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
        ''')
        cols={r['name'] for r in c.execute('PRAGMA table_info(orders)')}
        if 'estimated_delivery' not in cols:
            c.execute('ALTER TABLE orders ADD COLUMN estimated_delivery TEXT')
        cols={r['name'] for r in c.execute('PRAGMA table_info(order_items)')}
        if 'made_to_order' not in cols:
            c.execute('ALTER TABLE order_items ADD COLUMN made_to_order INTEGER NOT NULL DEFAULT 0')
        # v1 already decremented stock at order creation, even when status='novo'.
        # Record that history only during the first migration; never charge stock twice.
        cols={r['name'] for r in c.execute('PRAGMA table_info(orders)')}
        if 'stock_deducted' not in cols:
            c.execute('ALTER TABLE orders ADD COLUMN stock_deducted INTEGER NOT NULL DEFAULT 0')
            c.execute("UPDATE orders SET stock_deducted=1 WHERE status!='cancelado'")
        # Timeline for preexisting v1 orders.
        c.execute('''INSERT INTO order_events(order_id,status,note,created_at)
              SELECT o.id,o.status,'Pedido importado da versão anterior.',o.created_at FROM orders o
              WHERE NOT EXISTS (SELECT 1 FROM order_events e WHERE e.order_id=o.id)''')

migrate()


def customer_id(req:Request) -> int:
    cid=req.session.get('customer_id')
    if not cid: raise HTTPException(401,'Entre em sua conta para continuar.')
    return int(cid)


def customer_info(c,cid):
    row=c.execute('''SELECT cu.id,cu.name,cu.email,cu.phone,cu.address,cu.created_at
      FROM customers cu JOIN customer_accounts ca ON ca.customer_id=cu.id WHERE cu.id=?''',(cid,)).fetchone()
    if not row: raise HTTPException(401,'Conta não encontrada. Entre novamente.')
    return dict(row)


class Register(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    email:str=Field(min_length=5,max_length=180)
    phone:str=Field(default='',max_length=60)
    address:str=Field(default='',max_length=500)
    password:str=Field(min_length=10,max_length=200)

class CustomerLogin(BaseModel):
    email:str=Field(min_length=5,max_length=180)
    password:str=Field(min_length=1,max_length=200)

class Profile(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    phone:str=Field(default='',max_length=60)
    address:str=Field(default='',max_length=500)

class PasswordChange(BaseModel):
    current_password:str
    new_password:str=Field(min_length=10,max_length=200)


@app.get('/conta')
def account_page(): return FileResponse(ROOT/'templates/account.html')

@app.post('/api/customer/register')
def register(req:Request,body:Register):
    email=body.email.strip().lower()
    if '@' not in email or '.' not in email.split('@')[-1]:
        raise HTTPException(422,'E-mail inválido.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM customer_accounts WHERE email_normalized=?',(email,)).fetchone():
            raise HTTPException(409,'Este e-mail já está cadastrado. Entre em sua conta.')
        cur=c.execute('INSERT INTO customers(name,phone,email,address,created_at) VALUES(?,?,?,?,?)',
                 (body.name.strip(),body.phone.strip(),email,body.address.strip(),now_iso()))
        cid=cur.lastrowid
        salt=secrets.token_hex(16)
        c.execute('INSERT INTO customer_accounts(customer_id,email_normalized,salt,password_hash,created_at) VALUES(?,?,?,?,?)',
                  (cid,email,salt,hash_password(body.password,salt),now_iso()))
    req.session['customer_id']=cid
    return {'ok':True,'customer_id':cid}

@app.post('/api/customer/login')
def customer_login(req:Request,body:CustomerLogin):
    key=login_throttle('customer', body.email)
    with db() as c:
        row=c.execute('SELECT * FROM customer_accounts WHERE email_normalized=?',(body.email.strip().lower(),)).fetchone()
    if not row or not hmac.compare_digest(row['password_hash'],hash_password(body.password,row['salt'])):
        note_failed_login(key)
        raise HTTPException(401,'E-mail ou senha incorretos.')
    clear_failed_login(key)
    req.session['customer_id']=row['customer_id']
    return {'ok':True}

@app.post('/api/customer/logout')
def customer_logout(req:Request):
    req.session.pop('customer_id',None)
    return {'ok':True}

@app.get('/api/customer/me')
def customer_me(req:Request):
    cid=req.session.get('customer_id')
    if not cid:return {'authenticated':False}
    with db() as c:
        try: return {'authenticated':True,'customer':customer_info(c,cid)}
        except HTTPException: return {'authenticated':False}

@app.put('/api/customer/profile')
def update_profile(req:Request,body:Profile):
    cid=customer_id(req)
    with db() as c:
        customer_info(c,cid)
        c.execute('UPDATE customers SET name=?,phone=?,address=? WHERE id=?',(body.name.strip(),body.phone.strip(),body.address.strip(),cid))
        return {'customer':customer_info(c,cid)}

@app.put('/api/customer/password')
def change_password(req:Request,body:PasswordChange):
    cid=customer_id(req)
    with db() as c:
        row=c.execute('SELECT * FROM customer_accounts WHERE customer_id=?',(cid,)).fetchone()
        if not row or not hmac.compare_digest(row['password_hash'],hash_password(body.current_password,row['salt'])):
            raise HTTPException(401,'Senha atual incorreta.')
        salt=secrets.token_hex(16)
        c.execute('UPDATE customer_accounts SET salt=?,password_hash=? WHERE customer_id=?',(salt,hash_password(body.new_password,salt),cid))
        return {'ok':True}

@app.get('/api/customer/orders')
def my_orders(req:Request):
    cid=customer_id(req)
    with db() as c:
        customer_info(c,cid)
        ids=c.execute('SELECT id FROM orders WHERE customer_id=? ORDER BY id DESC',(cid,)).fetchall()
        return {'orders':[get_order(c,x['id']) for x in ids]}

@app.get('/api/customer/orders/{oid}')
def my_order(oid:int,req:Request):
    cid=customer_id(req)
    with db() as c:
        row=c.execute('SELECT 1 FROM orders WHERE id=? AND customer_id=?',(oid,cid)).fetchone()
        if not row: raise HTTPException(404,'Pedido não encontrado.')
        return {'order':get_order(c,oid)}


class QuoteRequest(BaseModel):
    product_id:int
    quantity:int=Field(default=1,ge=1,le=200)
    width_mm:int|None=Field(default=None,ge=100,le=15000)
    height_mm:int|None=Field(default=None,ge=100,le=15000)
    material:str=Field(default='',max_length=60)
    finish:str=Field(default='',max_length=60)
    glass:str=Field(default='',max_length=80)
    notes:str=Field(default='',max_length=1000)


def quote_row(c,q):
    result=dict(q)
    result['customer_name']=c.execute('SELECT name FROM customers WHERE id=?',(q['customer_id'],)).fetchone()[0]
    return result

@app.post('/api/customer/quotes')
def quote_request(req:Request,body:QuoteRequest):
    cid=customer_id(req)
    with db() as c:
        customer_info(c,cid)
        p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(body.product_id,)).fetchone()
        if not p: raise HTTPException(404,'Produto não encontrado.')
        cur=c.execute('''INSERT INTO quotes(customer_id,product_id,product_name,sku,width_mm,height_mm,material,finish,
          glass,quantity,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
          (cid,p['id'],p['name'],p['sku'],body.width_mm,body.height_mm,body.material.strip(),body.finish.strip(),
           body.glass.strip(),body.quantity,body.notes.strip(),now_iso()))
        c.execute('UPDATE quotes SET number=? WHERE id=?',(f'ORC-{cur.lastrowid:05d}',cur.lastrowid))
        return {'quote':quote_row(c,c.execute('SELECT * FROM quotes WHERE id=?',(cur.lastrowid,)).fetchone())}

@app.get('/api/customer/quotes')
def my_quotes(req:Request):
    cid=customer_id(req)
    with db() as c:
        customer_info(c,cid)
        return {'quotes':[quote_row(c,x) for x in c.execute('SELECT * FROM quotes WHERE customer_id=? ORDER BY id DESC',(cid,))]}

class QuotePrice(BaseModel):
    unit_price:float=Field(ge=0.01,le=10000000)
    valid_until:str=Field(default='',max_length=20)
    notes:str=Field(default='',max_length=1000)

@app.get('/api/admin/quotes')
def admin_quotes(req:Request):
    require_admin(req)
    with db() as c: return {'quotes':[quote_row(c,x) for x in c.execute('SELECT * FROM quotes ORDER BY id DESC')]}

@app.patch('/api/admin/quotes/{qid}/price')
def quote_price(qid:int,req:Request,body:QuotePrice):
    require_admin(req)
    with db() as c:
        q=c.execute('SELECT * FROM quotes WHERE id=?',(qid,)).fetchone()
        if not q: raise HTTPException(404,'Orçamento não encontrado.')
        if q['status']=='aprovado':raise HTTPException(409,'Orçamento já aprovado e convertido em pedido.')
        price=money_cents(body.unit_price)
        c.execute('UPDATE quotes SET unit_price_cents=?,total_cents=?,valid_until=?,notes=?,status=? WHERE id=?',
            (price,price*q['quantity'],body.valid_until or None,body.notes,'enviado',qid))
        return {'quote':quote_row(c,c.execute('SELECT * FROM quotes WHERE id=?',(qid,)).fetchone())}

@app.post('/api/customer/quotes/{qid}/approve')
def approve_quote(qid:int,req:Request):
    cid=customer_id(req)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        q=c.execute('SELECT * FROM quotes WHERE id=? AND customer_id=?',(qid,cid)).fetchone()
        if not q: raise HTTPException(404,'Orçamento não encontrado.')
        if q['status']!='enviado' or q['total_cents']<=0: raise HTTPException(409,'Este orçamento não está disponível para aprovação.')
        if q['valid_until']:
            try:
                if datetime.strptime(q['valid_until'],'%Y-%m-%d').date()<datetime.now().date():
                    raise HTTPException(409,'Orçamento expirado. Solicite uma nova proposta.')
            except ValueError: raise HTTPException(422,'Data de validade inválida.')
        p=c.execute('SELECT id FROM products WHERE id=?',(q['product_id'],)).fetchone()
        if not p:raise HTTPException(409,'O produto não está mais cadastrado.')
        cust=customer_info(c,cid)
        cur=c.execute('''INSERT INTO orders(number,customer_id,status,payment_method,subtotal_cents,total_cents,notes,source,created_at)
          VALUES(?,?,?,?,?,?,?,?,?)''',(f'QT-{secrets.token_hex(8)}',cid,'novo','a combinar',q['total_cents'],q['total_cents'],
          f'Pedido sob medida a partir do orçamento {q["number"]}: {q["notes"]}','orçamento aprovado',now_iso()))
        oid=cur.lastrowid
        c.execute('UPDATE orders SET number=? WHERE id=?',(f'PED-{oid:05d}',oid))
        dims=f'{q["width_mm"] or "?"} × {q["height_mm"] or "?"} mm · {q["finish"] or "sob consulta"}'
        c.execute('''INSERT INTO order_items(order_id,product_id,name,dimension,sku,quantity,unit_price_cents,made_to_order)
          VALUES(?,?,?,?,?,?,?,1)''',(oid,q['product_id'],q['product_name'],dims,q['sku'],q['quantity'],q['unit_price_cents']))
        c.execute('INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)',
                  (oid,'novo',f'Orçamento {q["number"]} aprovado pelo cliente.',now_iso()))
        c.execute('UPDATE quotes SET status=?,order_id=? WHERE id=?',('aprovado',oid,qid))
        return {'order':get_order(c,oid)}


class Payment(BaseModel):
    amount:float=Field(gt=0,le=10000000)
    method:str=Field(min_length=2,max_length=80)
    notes:str=Field(default='',max_length=400)
    refund:bool=False

@app.post('/api/admin/orders/{oid}/payments')
def add_payment(oid:int,req:Request,body:Payment):
    require_admin(req)
    cents=money_cents(body.amount)
    if cents<=0:raise HTTPException(422,'Valor inválido.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        o=c.execute('SELECT total_cents,status FROM orders WHERE id=?',(oid,)).fetchone()
        if not o:raise HTTPException(404,'Pedido não encontrado.')
        if o['status']=='cancelado': raise HTTPException(409,'Pedido cancelado não recebe pagamentos.')
        paid=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE order_id=?',(oid,)).fetchone()[0]
        signed=-cents if body.refund else cents
        if paid+signed<0 or paid+signed>o['total_cents']:raise HTTPException(422,'Valor excede o saldo permitido do pedido.')
        cur=c.execute('INSERT INTO payments(order_id,amount_cents,method,notes,created_at) VALUES(?,?,?,?,?)',
                      (oid,signed,body.method.strip(),body.notes.strip(),now_iso()))
        return {'payment_id':cur.lastrowid,'paid_cents':paid+signed,'balance_cents':o['total_cents']-paid-signed}

@app.get('/api/admin/finance')
def finances(req:Request):
    require_admin(req)
    with db() as c:
        paid=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments').fetchone()[0]
        exp_paid=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM expenses WHERE paid=1').fetchone()[0]
        total=c.execute("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE status!='cancelado'").fetchone()[0]
        payments=[dict(x) for x in c.execute('''SELECT p.*,o.number FROM payments p JOIN orders o ON o.id=p.order_id ORDER BY p.id DESC LIMIT 150''')]
        expenses=[dict(x) for x in c.execute('SELECT * FROM expenses ORDER BY id DESC LIMIT 150')]
        return {'paid_cents':paid,'expenses_paid_cents':exp_paid,'order_value_cents':total,
                'outstanding_cents':max(0,total-paid),'payments':payments,'expenses':expenses}

class Expense(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    category:str=Field(default='Operacional',max_length=80)
    amount:float=Field(gt=0,le=10000000)
    paid:bool=False
    due_at:str=Field(default='',max_length=20)

@app.post('/api/admin/expenses')
def expense_create(req:Request,body:Expense):
    require_admin(req)
    with db() as c:
        cur=c.execute('INSERT INTO expenses(name,category,amount_cents,paid,due_at,created_at) VALUES(?,?,?,?,?,?)',
            (body.name.strip(),body.category.strip(),money_cents(body.amount),int(body.paid),body.due_at or None,now_iso()))
        return {'id':cur.lastrowid}


class Supplier(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    phone:str=Field(default='',max_length=60)
    email:str=Field(default='',max_length=180)
    document:str=Field(default='',max_length=60)
    notes:str=Field(default='',max_length=500)

@app.get('/api/admin/suppliers')
def suppliers(req:Request):
    require_admin(req)
    with db() as c:return {'suppliers':[dict(x) for x in c.execute('SELECT * FROM suppliers ORDER BY id DESC')]}

@app.post('/api/admin/suppliers')
def supplier_create(req:Request,body:Supplier):
    require_admin(req)
    with db() as c:
        cur=c.execute('INSERT INTO suppliers(name,phone,email,document,notes) VALUES(?,?,?,?,?)',tuple(body.model_dump().values()))
        return {'id':cur.lastrowid}

class Purchase(BaseModel):
    supplier_id:int|None=None
    product_id:int
    quantity:int=Field(ge=1,le=1000000)
    unit_cost:float=Field(ge=0,le=10000000)

@app.get('/api/admin/purchases')
def purchases(req:Request):
    require_admin(req)
    with db() as c:
        rows=c.execute('''SELECT pu.*,p.name product_name,s.name supplier_name FROM purchases pu
          JOIN products p ON p.id=pu.product_id LEFT JOIN suppliers s ON s.id=pu.supplier_id ORDER BY pu.id DESC''')
        return {'purchases':[dict(x) for x in rows]}

@app.post('/api/admin/purchases')
def purchase_create(req:Request,body:Purchase):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(body.product_id,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        if body.supplier_id and not c.execute('SELECT 1 FROM suppliers WHERE id=?',(body.supplier_id,)).fetchone():raise HTTPException(404,'Fornecedor não encontrado.')
        cur=c.execute('''INSERT INTO purchases(supplier_id,product_id,quantity,unit_cost_cents,created_at)
            VALUES(?,?,?,?,?)''',(body.supplier_id,body.product_id,body.quantity,money_cents(body.unit_cost),now_iso()))
        return {'id':cur.lastrowid}

@app.post('/api/admin/purchases/{pid}/receive')
def purchase_receive(pid:int,req:Request):
    require_admin(req)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        p=c.execute('SELECT * FROM purchases WHERE id=?',(pid,)).fetchone()
        if not p:raise HTTPException(404,'Compra não encontrada.')
        if p['status']!='pendente':raise HTTPException(409,'Compra já recebida.')
        c.execute('UPDATE purchases SET status=? WHERE id=?',('recebido',pid))
        c.execute('UPDATE products SET stock=stock+? WHERE id=?',(p['quantity'],p['product_id']))
        c.execute('INSERT INTO stock_movements(product_id,change_qty,reason,created_at) VALUES(?,?,?,?)',
              (p['product_id'],p['quantity'],f'Entrada de compra #{pid}',now_iso()))
        return {'ok':True}

class StockAdjustment(BaseModel):
    product_id:int
    change_qty:int=Field(ge=-100000,le=100000)
    reason:str=Field(min_length=3,max_length=300)

@app.post('/api/admin/stock/adjust')
def stock_adjust(req:Request,body:StockAdjustment):
    require_admin(req)
    if body.change_qty==0:raise HTTPException(422,'Informe uma quantidade diferente de zero.')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        p=c.execute('SELECT stock FROM products WHERE id=?',(body.product_id,)).fetchone()
        if not p:raise HTTPException(404,'Produto não encontrado.')
        if p['stock']+body.change_qty<0:raise HTTPException(409,'Quantidade indisponível.')
        c.execute('UPDATE products SET stock=stock+? WHERE id=?',(body.change_qty,body.product_id))
        c.execute('INSERT INTO stock_movements(product_id,change_qty,reason,created_at) VALUES(?,?,?,?)',
                  (body.product_id,body.change_qty,body.reason.strip(),now_iso()))
        return {'stock':p['stock']+body.change_qty}

@app.get('/api/admin/stock/movements')
def stock_movements(req:Request):
    require_admin(req)
    with db() as c:
        return {'movements':[dict(x) for x in c.execute('''SELECT m.*,p.name product_name FROM stock_movements m JOIN products p
            ON p.id=m.product_id ORDER BY m.id DESC LIMIT 200''')]}


class ProductSpecs(BaseModel):
    width_mm:int|None=Field(default=None,ge=100,le=15000)
    height_mm:int|None=Field(default=None,ge=100,le=15000)
    material:str=Field(default='',max_length=80)
    finish:str=Field(default='',max_length=80)
    glass:str=Field(default='',max_length=80)
    opening:str=Field(default='',max_length=80)
    warranty_months:int=Field(default=0,ge=0,le=240)
    made_to_order:bool=False

@app.put('/api/admin/products/{pid}/specs')
def set_specs(pid:int,req:Request,body:ProductSpecs):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        b=body.model_dump()
        c.execute('''INSERT INTO product_specs(product_id,width_mm,height_mm,material,finish,glass,opening,warranty_months,made_to_order)
          VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET width_mm=excluded.width_mm,height_mm=excluded.height_mm,
          material=excluded.material,finish=excluded.finish,glass=excluded.glass,opening=excluded.opening,
          warranty_months=excluded.warranty_months,made_to_order=excluded.made_to_order''',
          (pid,b['width_mm'],b['height_mm'],b['material'],b['finish'],b['glass'],b['opening'],b['warranty_months'],int(b['made_to_order'])))
    return {'ok':True}

@app.get('/api/products/{pid}/details')
def product_details(pid:int):
    with db() as c:
        p=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
        if not p:raise HTTPException(404,'Produto não encontrado.')
        spec=c.execute('SELECT * FROM product_specs WHERE product_id=?',(pid,)).fetchone()
        gallery=c.execute('SELECT image_url FROM product_gallery WHERE product_id=?',(pid,)).fetchall()
        return {'product':dict(p),'specs':dict(spec) if spec else None,'gallery':[g[0] for g in gallery]}

@app.post('/api/admin/products/{pid}/gallery')
async def upload_gallery(pid:int,req:Request,file:UploadFile=File(...)):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        count=c.execute('SELECT COUNT(*) FROM product_gallery WHERE product_id=?',(pid,)).fetchone()[0]
        if count>=8:raise HTTPException(422,'Máximo de oito fotos adicionais por produto.')
    url=await safe_image_upload(file,'galeria')
    with db() as c:c.execute('INSERT INTO product_gallery(product_id,image_url) VALUES(?,?)',(pid,url))
    return {'image_url':url}


class Operation(BaseModel):
    order_id:int
    kind:str=Field(min_length=3,max_length=80)
    status:str=Field(default='agendado',max_length=80)
    assigned_to:str=Field(default='',max_length=180)
    scheduled_for:str=Field(default='',max_length=40)
    notes:str=Field(default='',max_length=600)

@app.get('/api/admin/operations')
def operation_list(req:Request):
    require_admin(req)
    with db() as c:
        return {'operations':[dict(x) for x in c.execute('''SELECT op.*,o.number FROM operations op JOIN orders o ON o.id=op.order_id ORDER BY op.id DESC''')]}

@app.post('/api/admin/operations')
def operation_create(req:Request,body:Operation):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM orders WHERE id=?',(body.order_id,)).fetchone():raise HTTPException(404,'Pedido não encontrado.')
        cur=c.execute('''INSERT INTO operations(order_id,kind,status,assigned_to,scheduled_for,notes,created_at)
           VALUES(?,?,?,?,?,?,?)''',(body.order_id,body.kind,body.status,body.assigned_to,body.scheduled_for or None,body.notes,now_iso()))
        return {'id':cur.lastrowid}

class OperationStatus(BaseModel):
    status:str=Field(min_length=3,max_length=80)

@app.patch('/api/admin/operations/{oid}')
def operation_update(oid:int,req:Request,body:OperationStatus):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM operations WHERE id=?',(oid,)).fetchone():raise HTTPException(404,'Operação não encontrada.')
        c.execute('UPDATE operations SET status=? WHERE id=?',(body.status,oid))
        return {'ok':True}

class Warranty(BaseModel):
    order_id:int
    description:str=Field(min_length=3,max_length=800)

@app.get('/api/admin/warranties')
def warranty_list(req:Request):
    require_admin(req)
    with db() as c:
        return {'warranties':[dict(x) for x in c.execute('''SELECT w.*,o.number FROM warranties w JOIN orders o ON o.id=w.order_id ORDER BY w.id DESC''')]}

@app.post('/api/admin/warranties')
def warranty_create(req:Request,body:Warranty):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM orders WHERE id=?',(body.order_id,)).fetchone():raise HTTPException(404,'Pedido não encontrado.')
        cur=c.execute('INSERT INTO warranties(order_id,description,created_at) VALUES(?,?,?)',(body.order_id,body.description,now_iso()))
        return {'id':cur.lastrowid}

class WarrantyStatus(BaseModel):
    status:str=Field(min_length=2,max_length=80)

@app.patch('/api/admin/warranties/{wid}')
def warranty_update(wid:int,req:Request,body:WarrantyStatus):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM warranties WHERE id=?',(wid,)).fetchone():raise HTTPException(404,'Garantia não encontrada.')
        c.execute('UPDATE warranties SET status=? WHERE id=?',(body.status,wid))
        return {'ok':True}

class EstimateDate(BaseModel):
    estimated_delivery:str=Field(max_length=40)

@app.patch('/api/admin/orders/{oid}/delivery')
def delivery_date(oid:int,req:Request,body:EstimateDate):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM orders WHERE id=?',(oid,)).fetchone():raise HTTPException(404,'Pedido não encontrado.')
        c.execute('UPDATE orders SET estimated_delivery=? WHERE id=?',(body.estimated_delivery or None,oid))
        c.execute('INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)',
                (oid,c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()[0],
                 'Previsão de entrega atualizada: '+(body.estimated_delivery or 'a confirmar'),now_iso()))
        return {'ok':True}

class Staff(BaseModel):
    name:str=Field(min_length=2,max_length=180)
    role:str=Field(min_length=2,max_length=80)

@app.get('/api/admin/staff')
def staff_list(req:Request):
    require_admin(req)
    with db() as c:return {'staff':[dict(x) for x in c.execute('SELECT * FROM staff ORDER BY id DESC')]}

@app.post('/api/admin/staff')
def staff_create(req:Request,body:Staff):
    require_admin(req)
    with db() as c:
        cur=c.execute('INSERT INTO staff(name,role,created_at) VALUES(?,?,?)',(body.name,body.role,now_iso()))
        return {'id':cur.lastrowid}

@app.get('/api/admin/report.csv')
def report_csv(req:Request):
    require_admin(req)
    import csv, io
    from fastapi.responses import Response
    out=io.StringIO();w=csv.writer(out,delimiter=';')
    w.writerow(['Pedido','Cliente','Status','Total (centavos)','Recebido (centavos)','Criado em'])
    with db() as c:
        for r in c.execute('''SELECT o.number,cu.name,o.status,o.total_cents,
          (SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE order_id=o.id) paid,o.created_at
          FROM orders o JOIN customers cu ON cu.id=o.customer_id ORDER BY o.id'''):
            w.writerow(list(r))
    return Response(content='\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',
      headers={'Content-Disposition':'attachment; filename="esquadra-relatorio.csv"'})

@app.get('/api/customer/orders/{oid}/receipt.pdf')
def customer_receipt(oid:int,req:Request):
    cid=customer_id(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM orders WHERE id=? AND customer_id=?',(oid,cid)).fetchone():
            raise HTTPException(404,'Pedido não encontrado.')
    from app import build_receipt
    return build_receipt(oid)

# PDFs comerciais personalizados (nao sao NF-e/NFC-e)
def commercial_pdf(title:str,number:str,customer:str,lines:list[tuple[str,str]],footer:str):
    import io
    from html import escape as e
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image as RLImage
    from fastapi.responses import StreamingResponse
    from app import settings_dict
    with db() as c: store=settings_dict(c)
    buf=io.BytesIO();doc=SimpleDocTemplate(buf,pagesize=A4,leftMargin=42,rightMargin=42,topMargin=45,bottomMargin=42)
    sty=getSampleStyleSheet()
    sty.add(ParagraphStyle(name='Brand2',parent=sty['Heading1'],fontSize=22,leading=27,textColor=colors.HexColor('#141719')))
    sty.add(ParagraphStyle(name='Head2',parent=sty['Heading2'],fontSize=14,leading=19,spaceAfter=10,textColor=colors.HexColor('#141719')))
    sty.add(ParagraphStyle(name='Text2',parent=sty['Normal'],fontSize=9,leading=15))
    sty.add(ParagraphStyle(name='Grey2',parent=sty['Normal'],fontSize=8,leading=12,textColor=colors.HexColor('#777E84')))
    story=[]
    if store.get('logo_url','').startswith('/media/'):
        img=UPLOADS/store['logo_url'].split('/')[-1]
        if img.exists():story.append(RLImage(str(img),width=48,height=48,kind='proportional'))
    story.append(Paragraph(e(store.get('store_name','ESQUADRA')),sty['Brand2']))
    story.append(Paragraph(e(store.get('company_name','')),sty['Text2']))
    story.append(Paragraph(e(store.get('document',''))+' · '+e(store.get('phone','')),sty['Grey2']))
    story.append(Paragraph(e(store.get('address','')),sty['Grey2']))
    story.append(Spacer(1,24))
    story.append(Paragraph(e(title),sty['Head2']))
    story.append(Paragraph('Documento: '+e(number)+' · Emissão: '+e(now_iso()[:16].replace('T',' ')),sty['Grey2']))
    story.append(Spacer(1,15))
    story.append(Paragraph('CLIENTE: '+e(customer),sty['Text2']))
    story.append(Spacer(1,17))
    rows=[[Paragraph('DESCRIÇÃO',sty['Grey2']),Paragraph('INFORMAÇÃO',sty['Grey2'])]]
    for key,value in lines:
        rows.append([Paragraph(e(key),sty['Text2']),Paragraph(e(str(value)).replace('\n','<br/>'),sty['Text2'])])
    t=Table(rows,colWidths=[154,358],repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#ECEFF1')),
      ('LINEBELOW',(0,0),(-1,-1),.5,colors.HexColor('#D7DCDF')),
      ('LEFTPADDING',(0,0),(-1,-1),11),('RIGHTPADDING',(0,0),(-1,-1),11),
      ('TOPPADDING',(0,0),(-1,-1),11),('BOTTOMPADDING',(0,0),(-1,-1),11),
      ('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(t);story.append(Spacer(1,26));story.append(Paragraph(e(footer),sty['Grey2']))
    story.append(Spacer(1,13));story.append(Paragraph('DOCUMENTO COMERCIAL · NÃO SUBSTITUI NOTA FISCAL',sty['Grey2']))
    doc.build(story);buf.seek(0)
    return StreamingResponse(buf,media_type='application/pdf',headers={'Content-Disposition':f'inline; filename="{number}.pdf"'})


def quote_pdf_content(qid:int):
    from app import brl
    with db() as c:
        q=c.execute('SELECT * FROM quotes WHERE id=?',(qid,)).fetchone()
        if not q:raise HTTPException(404,'Orçamento não encontrado.')
        cu=customer_info(c,q['customer_id'])
        lines=[('Produto',q['product_name']),('Código',q['sku']),('Medidas',f'{q["width_mm"] or "A definir"} x {q["height_mm"] or "A definir"} mm'),
         ('Quantidade',str(q['quantity'])),('Material',q['material'] or 'A confirmar'),('Acabamento',q['finish'] or 'A confirmar'),
         ('Vidro',q['glass'] or 'A confirmar'),('Observações',q['notes'] or '—'),
         ('Preço unitário',brl(q['unit_price_cents']) if q['total_cents'] else 'Em análise'),
         ('VALOR TOTAL',brl(q['total_cents']) if q['total_cents'] else 'A definir'),
         ('Validade',q['valid_until'] or 'A confirmar'),('Situação',q['status'])]
        return commercial_pdf('PROPOSTA COMERCIAL · ESQUADRIAS SOB MEDIDA',q['number'],cu['name'],lines,
         'Proposta sujeita à confirmação de medidas, disponibilidade, entrega e instalação. O pedido é gerado após aprovação.')

@app.get('/api/admin/quotes/{qid}/pdf')
def quote_pdf_admin(qid:int,req:Request):
    require_admin(req)
    return quote_pdf_content(qid)

@app.get('/api/customer/quotes/{qid}/pdf')
def quote_pdf_customer(qid:int,req:Request):
    cid=customer_id(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM quotes WHERE id=? AND customer_id=?',(qid,cid)).fetchone():raise HTTPException(404,'Orçamento não encontrado.')
    return quote_pdf_content(qid)

@app.get('/api/admin/orders/{oid}/delivery.pdf')
def delivery_pdf_admin(oid:int,req:Request):
    require_admin(req)
    with db() as c:
        o=get_order(c,oid)
    items='\n'.join(f"{i['quantity']}x {i['name']} ({i['dimension']})" for i in o['items'])
    return commercial_pdf('ORDEM DE ENTREGA',o['number'],o['customer_name'],
      [('Telefone',o['customer_phone']),('Endereço',o['customer_address']),('Produtos',items),
       ('Data prevista',o['estimated_delivery'] or 'A confirmar'),('Situação',o['status']),
       ('Recebido por','______________________________________')],
      'Confirme as quantidades e condições dos produtos antes de assinar o recebimento.')
