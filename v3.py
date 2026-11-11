"""ESQUADRA 3.0: vendas, marketing consentido e Checkout Pro Mercado Pago.

Todas as migrações são aditivas. Pagamentos reais exigem credenciais privadas,
webhook assinado e HTTPS. Nenhum segredo é exposto à interface.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import re
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field
from app import app, db, now_iso, require_admin, get_order, money_cents
from v2 import customer_id


def migrate_sales():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS pricing_rules (
          product_id INTEGER PRIMARY KEY REFERENCES products(id),
          price_m2_cents INTEGER NOT NULL DEFAULT 0, minimum_cents INTEGER NOT NULL DEFAULT 0,
          black_pct INTEGER NOT NULL DEFAULT 0, premium_glass_cents INTEGER NOT NULL DEFAULT 0,
          extra_leaf_cents INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS delivery_zones (
          id INTEGER PRIMARY KEY AUTOINCREMENT, cep_prefix TEXT UNIQUE NOT NULL,
          description TEXT NOT NULL DEFAULT '', fee_cents INTEGER NOT NULL, lead_days INTEGER NOT NULL DEFAULT 7,
          active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS coupons (
          code TEXT PRIMARY KEY, percent INTEGER NOT NULL CHECK(percent BETWEEN 1 AND 70),
          minimum_cents INTEGER NOT NULL DEFAULT 0, max_uses INTEGER NOT NULL DEFAULT 100,
          uses INTEGER NOT NULL DEFAULT 0, valid_until TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS coupon_uses (
          order_id INTEGER PRIMARY KEY REFERENCES orders(id),code TEXT NOT NULL REFERENCES coupons(code));
        CREATE TABLE IF NOT EXISTS customer_tiers (
          customer_id INTEGER PRIMARY KEY REFERENCES customers(id),
          tier TEXT NOT NULL DEFAULT 'varejo', discount_pct INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS accessory_links (
          product_id INTEGER NOT NULL REFERENCES products(id),accessory_id INTEGER NOT NULL REFERENCES products(id),
          PRIMARY KEY(product_id,accessory_id));
        CREATE TABLE IF NOT EXISTS cart_leads (
          customer_id INTEGER PRIMARY KEY REFERENCES customers(id), cart_json TEXT NOT NULL DEFAULT '[]',
          consent INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,followup_status TEXT NOT NULL DEFAULT 'pendente');
        CREATE TABLE IF NOT EXISTS opportunities (
          id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER REFERENCES customers(id),
          title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'novo',value_cents INTEGER NOT NULL DEFAULT 0,
          next_contact TEXT NOT NULL DEFAULT '',loss_reason TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS verified_reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES products(id),
          customer_id INTEGER NOT NULL REFERENCES customers(id),order_id INTEGER NOT NULL REFERENCES orders(id),
          stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5), comment TEXT NOT NULL,
          published INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,
          UNIQUE(product_id,customer_id,order_id));
        CREATE TABLE IF NOT EXISTS product_views (
          product_id INTEGER NOT NULL REFERENCES products(id),day TEXT NOT NULL,
          count INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(product_id,day));
        CREATE TABLE IF NOT EXISTS mp_intents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL REFERENCES orders(id),
          amount_cents INTEGER NOT NULL, external_reference TEXT UNIQUE NOT NULL,
          preference_id TEXT, checkout_url TEXT, status TEXT NOT NULL DEFAULT 'iniciado',
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mp_payments (
          payment_id TEXT PRIMARY KEY,intent_id INTEGER NOT NULL REFERENCES mp_intents(id),
          order_id INTEGER NOT NULL REFERENCES orders(id),amount_cents INTEGER NOT NULL,
          status TEXT NOT NULL, recorded INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
        ''')
        cols={x['name'] for x in c.execute('PRAGMA table_info(orders)')}
        for name,decl in [('shipping_cents','INTEGER NOT NULL DEFAULT 0'),
                          ('coupon_code',"TEXT NOT NULL DEFAULT ''"),
                          ('sales_discount_cents','INTEGER NOT NULL DEFAULT 0'),
                          ('delivery_cep',"TEXT NOT NULL DEFAULT ''")]:
            if name not in cols:
                c.execute(f'ALTER TABLE orders ADD COLUMN {name} {decl}')
        qcols={x['name'] for x in c.execute('PRAGMA table_info(quotes)')}
        if 'options_json' not in qcols:
            c.execute("ALTER TABLE quotes ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}' ")

migrate_sales()


def get_delivery(c,cep):
    cep=re.sub(r'\D','',cep or '')
    if len(cep)!=8: raise HTTPException(422,'Informe um CEP válido com 8 dígitos.')
    row=c.execute('''SELECT * FROM delivery_zones WHERE active=1 AND ? LIKE (cep_prefix || '%')
                     ORDER BY LENGTH(cep_prefix) DESC LIMIT 1''',(cep,)).fetchone()
    if not row: raise HTTPException(422,'Ainda não entregamos neste CEP. Escolha retirada ou solicite orçamento.')
    return dict(row)


def price_adjustments(c,cid,subtotal,body):
    """Servidor é a única autoridade dos preços promocionais e do frete."""
    tier=c.execute('SELECT * FROM customer_tiers WHERE customer_id=?',(cid,)).fetchone() if cid else None
    wholesale_pct=int(tier['discount_pct']) if tier and tier['tier']=='profissional' else 0
    wholesale_discount=subtotal*wholesale_pct//100
    coupon_discount=0
    coupon_code=(body.coupon or '').strip().upper()
    accepted_coupon=''
    if coupon_code:
        co=c.execute('SELECT * FROM coupons WHERE code=?',(coupon_code,)).fetchone()
        if not co or not co['active'] or co['uses']>=co['max_uses'] or (co['valid_until'] and co['valid_until']<date.today().isoformat()) or subtotal<co['minimum_cents']:
            raise HTTPException(422,'Cupom indisponível, expirado ou não atende às regras.')
        coupon_discount=subtotal*co['percent']//100
        if coupon_discount>wholesale_discount:
            accepted_coupon=coupon_code
    discount=max(wholesale_discount,coupon_discount)
    shipping=0;delivery_cep=''
    if body.delivery_mode=='entrega':
        zone=get_delivery(c,body.cep)
        shipping=zone['fee_cents'];delivery_cep=re.sub(r'\D','',body.cep)
    return discount,shipping,accepted_coupon,delivery_cep


class PreviewCheckout(BaseModel):
    items:list[dict]=Field(min_length=1,max_length=80)
    coupon:str=Field(default='',max_length=30)
    cep:str=Field(default='',max_length=12)
    delivery_mode:str=Field(default='retirada',pattern='^(entrega|retirada)$')

@app.post('/api/sales/preview')
def preview_checkout(req:Request,body:PreviewCheckout):
    # Simula apenas: o checkout sempre recalcula dentro da transação.
    with db() as c:
        subtotal=0
        for item in body.items:
            if set(item)!={'product_id','quantity'}:raise HTTPException(422,'Item inválido.')
            try:pid=int(item['product_id']);qty=int(item['quantity'])
            except (TypeError,ValueError):raise HTTPException(422,'Item inválido.')
            if qty<1 or qty>1000:raise HTTPException(422,'Quantidade inválida.')
            p=c.execute('SELECT price_cents,active FROM products WHERE id=?',(pid,)).fetchone()
            if not p or not p['active']:raise HTTPException(422,'Produto indisponível.')
            subtotal+=p['price_cents']*qty
        class Values:pass
        x=Values();x.coupon=body.coupon;x.cep=body.cep;x.delivery_mode=body.delivery_mode
        discount,shipping,code,delivery_cep=price_adjustments(c,req.session.get('customer_id'),subtotal,x)
        return {'subtotal_cents':subtotal,'discount_cents':discount,'shipping_cents':shipping,
                'total_cents':subtotal-discount+shipping,'coupon_applied':code,'delivery_cep':delivery_cep}

@app.get('/api/sales/shipping/{cep}')
def shipping_preview(cep:str):
    with db() as c:
        z=get_delivery(c,cep)
        return {'fee_cents':z['fee_cents'],'description':z['description'],'lead_days':z['lead_days']}


class CustomEstimate(BaseModel):
    product_id:int
    width_mm:int=Field(ge=100,le=15000)
    height_mm:int=Field(ge=100,le=15000)
    quantity:int=Field(default=1,ge=1,le=200)
    finish:str=Field(default='branco',max_length=40)
    glass:str=Field(default='comum',max_length=40)
    leaves:int=Field(default=2,ge=1,le=8)
    opening:str=Field(default='correr',max_length=50)

@app.post('/api/sales/estimate')
def estimate(body:CustomEstimate):
    with db() as c:
        p=c.execute('SELECT id,name,active FROM products WHERE id=?',(body.product_id,)).fetchone()
        rule=c.execute('SELECT * FROM pricing_rules WHERE product_id=?',(body.product_id,)).fetchone()
        if not p or not p['active']:raise HTTPException(404,'Produto indisponível.')
        if not rule or not rule['price_m2_cents']:
            return {'available':False,'message':'Solicite orçamento para estas medidas.'}
        # Area inteira em mm² para evitar imprecisão monetária em ponto flutuante.
        area=body.width_mm*body.height_mm
        base=max(rule['minimum_cents'],(rule['price_m2_cents']*area+999999)//1000000)
        if body.finish.casefold() in {'preto','preta'}:
            base+=base*rule['black_pct']//100
        if body.glass.casefold() in {'temperado','laminado','premium'}:
            base+=rule['premium_glass_cents']
        base+=max(0,body.leaves-2)*rule['extra_leaf_cents']
        return {'available':True,'unit_price_cents':base,'total_cents':base*body.quantity,
                'warning':'Estimativa. Medidas, material, mão de obra e instalação precisam da confirmação da loja.'}

class PricingRule(BaseModel):
    price_m2:float=Field(ge=0,le=1_000_000)
    minimum:float=Field(ge=0,le=1_000_000)
    black_pct:int=Field(default=0,ge=0,le=100)
    premium_glass:float=Field(default=0,ge=0,le=1_000_000)
    extra_leaf:float=Field(default=0,ge=0,le=1_000_000)

@app.put('/api/admin/sales/pricing/{pid}')
def save_pricing(pid:int,req:Request,body:PricingRule):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        c.execute('''INSERT INTO pricing_rules(product_id,price_m2_cents,minimum_cents,black_pct,premium_glass_cents,extra_leaf_cents)
        VALUES(?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET price_m2_cents=excluded.price_m2_cents,
        minimum_cents=excluded.minimum_cents,black_pct=excluded.black_pct,premium_glass_cents=excluded.premium_glass_cents,
        extra_leaf_cents=excluded.extra_leaf_cents''',(pid,money_cents(body.price_m2),money_cents(body.minimum),body.black_pct,
        money_cents(body.premium_glass),money_cents(body.extra_leaf)))
        return {'ok':True}

class ShippingZone(BaseModel):
    cep_prefix:str=Field(pattern='^[0-9]{1,5}$')
    description:str=Field(default='',max_length=120)
    fee:float=Field(ge=0,le=100000)
    lead_days:int=Field(default=7,ge=1,le=180)
    active:bool=True

@app.post('/api/admin/sales/shipping')
def save_shipping(req:Request,body:ShippingZone):
    require_admin(req)
    with db() as c:
        c.execute('''INSERT INTO delivery_zones(cep_prefix,description,fee_cents,lead_days,active) VALUES(?,?,?,?,?)
        ON CONFLICT(cep_prefix) DO UPDATE SET description=excluded.description,fee_cents=excluded.fee_cents,
        lead_days=excluded.lead_days,active=excluded.active''',(body.cep_prefix,body.description,money_cents(body.fee),body.lead_days,int(body.active)))
        return {'ok':True}

class Coupon(BaseModel):
    code:str=Field(pattern='^[A-Za-z0-9_-]{3,25}$')
    percent:int=Field(ge=1,le=70)
    minimum:float=Field(default=0,ge=0)
    max_uses:int=Field(default=100,ge=1,le=1_000_000)
    valid_until:str=Field(default='',max_length=10)
    active:bool=True

@app.post('/api/admin/sales/coupons')
def save_coupon(req:Request,body:Coupon):
    require_admin(req)
    if body.valid_until:
        try:date.fromisoformat(body.valid_until)
        except ValueError:raise HTTPException(422,'Data inválida.')
    with db() as c:
        c.execute('''INSERT INTO coupons(code,percent,minimum_cents,max_uses,valid_until,active)
        VALUES(?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET percent=excluded.percent,minimum_cents=excluded.minimum_cents,
        max_uses=excluded.max_uses,valid_until=excluded.valid_until,active=excluded.active''',
        (body.code.upper(),body.percent,money_cents(body.minimum),body.max_uses,body.valid_until,int(body.active)))
        return {'ok':True}

class Tier(BaseModel):
    customer_id:int
    tier:str=Field(pattern='^(varejo|profissional)$')
    discount_pct:int=Field(default=0,ge=0,le=50)

@app.post('/api/admin/sales/tier')
def customer_tier(req:Request,body:Tier):
    require_admin(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM customers WHERE id=?',(body.customer_id,)).fetchone():raise HTTPException(404,'Cliente não encontrado.')
        c.execute('''INSERT INTO customer_tiers(customer_id,tier,discount_pct) VALUES(?,?,?)
        ON CONFLICT(customer_id) DO UPDATE SET tier=excluded.tier,discount_pct=excluded.discount_pct''',
        (body.customer_id,body.tier,body.discount_pct))
        return {'ok':True}

class Accessory(BaseModel):
    product_id:int
    accessory_id:int

@app.post('/api/admin/sales/accessory')
def add_accessory(req:Request,body:Accessory):
    require_admin(req)
    if body.product_id==body.accessory_id:raise HTTPException(422,'Escolha produtos diferentes.')
    with db() as c:
        for pid in (body.product_id,body.accessory_id):
            if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        c.execute('INSERT OR IGNORE INTO accessory_links(product_id,accessory_id) VALUES(?,?)',(body.product_id,body.accessory_id))
        return {'ok':True}

@app.get('/api/sales/accessories/{pid}')
def accessories(pid:int):
    with db() as c:
        rows=c.execute('''SELECT p.id,p.name,p.price_cents,p.image_url FROM products p JOIN accessory_links a ON a.accessory_id=p.id
        WHERE a.product_id=? AND p.active=1 AND p.stock>0''',(pid,)).fetchall()
        return {'accessories':[dict(x) for x in rows]}

class Draft(BaseModel):
    items:list[dict]=Field(default_factory=list,max_length=50)
    consent:bool=False

@app.post('/api/customer/cart-draft')
def cart_draft(req:Request,body:Draft):
    cid=customer_id(req)
    with db() as c:
        if not body.consent:
            c.execute('DELETE FROM cart_leads WHERE customer_id=?',(cid,))
            return {'saved':False}
        import json
        cleaned=[]
        for item in body.items:
            pid=int(item.get('product_id',0));qty=int(item.get('quantity',0))
            if not 1<=qty<=100 or not c.execute('SELECT 1 FROM products WHERE id=? AND active=1',(pid,)).fetchone():
                raise HTTPException(422,'Carrinho inválido.')
            cleaned.append({'product_id':pid,'quantity':qty})
        c.execute('''INSERT INTO cart_leads(customer_id,cart_json,consent,updated_at) VALUES(?,?,1,?)
        ON CONFLICT(customer_id) DO UPDATE SET cart_json=excluded.cart_json,consent=1,updated_at=excluded.updated_at,followup_status='pendente' ''',
        (cid,json.dumps(cleaned),now_iso()))
        return {'saved':True}

class Opportunity(BaseModel):
    customer_id:int|None=None
    title:str=Field(min_length=3,max_length=150)
    value:float=Field(default=0,ge=0)
    next_contact:str=Field(default='',max_length=10)
    notes:str=Field(default='',max_length=500)

@app.post('/api/admin/sales/opportunities')
def new_opportunity(req:Request,body:Opportunity):
    require_admin(req)
    with db() as c:
        if body.customer_id and not c.execute('SELECT 1 FROM customers WHERE id=?',(body.customer_id,)).fetchone():raise HTTPException(404,'Cliente não encontrado.')
        r=c.execute('INSERT INTO opportunities(customer_id,title,value_cents,next_contact,notes,created_at) VALUES(?,?,?,?,?,?)',
        (body.customer_id,body.title,money_cents(body.value),body.next_contact,body.notes,now_iso()))
        return {'id':r.lastrowid}

class OpportunityState(BaseModel):
    status:str=Field(pattern='^(novo|contatado|proposta|ganho|perdido)$')
    loss_reason:str=Field(default='',max_length=200)

@app.patch('/api/admin/sales/opportunities/{oid}')
def change_opportunity(oid:int,req:Request,body:OpportunityState):
    require_admin(req)
    with db() as c:
        c.execute('UPDATE opportunities SET status=?,loss_reason=? WHERE id=?',(body.status,body.loss_reason,oid))
        if not c.execute('SELECT 1 FROM opportunities WHERE id=?',(oid,)).fetchone():raise HTTPException(404,'Oportunidade não encontrada.')
        return {'ok':True}

class Review(BaseModel):
    product_id:int
    order_id:int
    stars:int=Field(ge=1,le=5)
    comment:str=Field(min_length=5,max_length=650)

@app.post('/api/customer/sales/reviews')
def submit_review(req:Request,body:Review):
    cid=customer_id(req)
    with db() as c:
        order=c.execute("SELECT 1 FROM orders WHERE id=? AND customer_id=? AND status IN ('entregue','instalado')",(body.order_id,cid)).fetchone()
        item=c.execute('SELECT 1 FROM order_items WHERE order_id=? AND product_id=?',(body.order_id,body.product_id)).fetchone()
        if not order or not item:raise HTTPException(403,'Avaliação exige compra entregue ou instalada.')
        try:
            c.execute('INSERT INTO verified_reviews(product_id,customer_id,order_id,stars,comment,created_at) VALUES(?,?,?,?,?,?)',
            (body.product_id,cid,body.order_id,body.stars,body.comment.strip(),now_iso()))
        except Exception as exc:
            if 'UNIQUE' in str(exc):raise HTTPException(409,'Você já avaliou este produto nesse pedido.')
            raise
        return {'ok':True,'moderated':True}

@app.get('/api/sales/reviews/{pid}')
def public_reviews(pid:int):
    with db() as c:
        rows=c.execute('''SELECT r.stars,r.comment,r.created_at,substr(cu.name,1,1) initial
          FROM verified_reviews r JOIN customers cu ON cu.id=r.customer_id
          WHERE r.product_id=? AND r.published=1 ORDER BY r.id DESC LIMIT 30''',(pid,)).fetchall()
        return {'reviews':[dict(x) for x in rows]}

@app.post('/api/sales/view/{pid}')
def count_view(pid:int):
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=? AND active=1',(pid,)).fetchone():raise HTTPException(404,'Produto não encontrado.')
        c.execute('''INSERT INTO product_views(product_id,day,count) VALUES(?,?,1) ON CONFLICT(product_id,day)
        DO UPDATE SET count=count+1''',(pid,date.today().isoformat()))
        return {'ok':True}

@app.get('/api/admin/sales/overview')
def sales_overview(req:Request):
    require_admin(req)
    with db() as c:
        tables={
          'pricing':[dict(x) for x in c.execute('SELECT * FROM pricing_rules')],
          'zones':[dict(x) for x in c.execute('SELECT * FROM delivery_zones ORDER BY cep_prefix')],
          'coupons':[dict(x) for x in c.execute('SELECT * FROM coupons ORDER BY code')],
          'tiers':[dict(x) for x in c.execute('SELECT * FROM customer_tiers')],
          'leads':[dict(x) for x in c.execute('''SELECT l.customer_id,l.cart_json,l.updated_at,l.followup_status,cu.name,cu.email
                  FROM cart_leads l JOIN customers cu ON cu.id=l.customer_id WHERE l.consent=1 ORDER BY l.updated_at DESC LIMIT 100''')],
          'opportunities':[dict(x) for x in c.execute('''SELECT o.*,cu.name customer_name FROM opportunities o LEFT JOIN customers cu ON cu.id=o.customer_id ORDER BY o.id DESC LIMIT 100''')],
          'reviews':[dict(x) for x in c.execute('''SELECT r.*,p.name product_name,cu.name customer_name FROM verified_reviews r
                  JOIN products p ON p.id=r.product_id JOIN customers cu ON cu.id=r.customer_id ORDER BY r.id DESC LIMIT 100''')],
          'top_products':[dict(x) for x in c.execute('''SELECT p.name,COALESCE(SUM(v.count),0) views FROM products p
                  LEFT JOIN product_views v ON v.product_id=p.id GROUP BY p.id ORDER BY views DESC LIMIT 10''')],
          'accessories':[dict(x) for x in c.execute('SELECT * FROM accessory_links')]
        }
        tables['quote_count']=c.execute('SELECT count(*) FROM quotes').fetchone()[0]
        tables['quote_approved']=c.execute("SELECT count(*) FROM quotes WHERE status='aprovado'").fetchone()[0]
        tables['sales_total']=c.execute('SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE status!=?',('cancelado',)).fetchone()[0]
        tables['payments_received']=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments').fetchone()[0]
        tables['mp_enabled']=bool(os.getenv('MP_ACCESS_TOKEN') and os.getenv('MP_WEBHOOK_SECRET') and os.getenv('ESQUADRA_BASE_URL','').startswith('https://'))
        return tables

class ReviewModeration(BaseModel):
    published:bool

@app.patch('/api/admin/sales/reviews/{rid}')
def moderate_review(rid:int,req:Request,body:ReviewModeration):
    require_admin(req)
    with db() as c:
        cur=c.execute('UPDATE verified_reviews SET published=? WHERE id=?',(int(body.published),rid))
        if not cur.rowcount:raise HTTPException(404,'Avaliação não encontrada.')
        return {'ok':True}

@app.patch('/api/admin/sales/leads/{cid}')
def mark_lead(cid:int,req:Request):
    require_admin(req)
    with db() as c:
        r=c.execute("UPDATE cart_leads SET followup_status='contatado' WHERE customer_id=? AND consent=1",(cid,))
        if not r.rowcount:raise HTTPException(404,'Lead não encontrado.')
        return {'ok':True}


# MERCADO PAGO: Checkout Pro com preferência criada exclusivamente pelo backend.
# Não aceite valores, token ou situação de pagamento fornecidos pelo navegador.
def mp_config():
    token=os.getenv('MP_ACCESS_TOKEN','').strip()
    secret=os.getenv('MP_WEBHOOK_SECRET','').strip()
    base=os.getenv('ESQUADRA_BASE_URL','').rstrip('/')
    if not token or not secret or not base.startswith('https://') or urlsplit(base).hostname in {'localhost','127.0.0.1'}:
        raise HTTPException(503,'Pagamento online ainda não configurado. Fale com a loja.')
    return token,secret,base


def mp_request(method,url,token,**kwargs):
    try:
        r=httpx.request(method,url,headers={'Authorization':f'Bearer {token}','Content-Type':'application/json',**kwargs.pop('headers',{})},
                        timeout=12.0,**kwargs)
        r.raise_for_status()
        return r.json()
    except (httpx.RequestError,httpx.HTTPStatusError,ValueError):
        raise HTTPException(502,'Falha temporária na comunicação com o Mercado Pago.')

class PayChoice(BaseModel):
    installment:str=Field(default='total',pattern='^(total|entrada30|entrada50)$')

@app.post('/api/customer/orders/{oid}/mercadopago')
def start_mp_payment(oid:int,req:Request,body:PayChoice):
    cid=customer_id(req)
    token,secret,base=mp_config()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        order=c.execute('SELECT * FROM orders WHERE id=? AND customer_id=?',(oid,cid)).fetchone()
        if not order:raise HTTPException(404,'Pedido não encontrado.')
        if order['status']=='cancelado':raise HTTPException(409,'Pedido cancelado não pode ser pago.')
        received=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE order_id=?',(oid,)).fetchone()[0]
        balance=order['total_cents']-received
        if balance<=0:raise HTTPException(409,'Este pedido já está pago.')
        percent={'total':100,'entrada30':30,'entrada50':50}[body.installment]
        due=min(balance,max(100,(order['total_cents']*percent+99)//100))
        # Reutilize um checkout ainda aberto para reduzir tentativas repetidas de cobrança.
        existing=c.execute("SELECT * FROM mp_intents WHERE order_id=? AND amount_cents=? AND status='criado' AND checkout_url IS NOT NULL ORDER BY id DESC LIMIT 1",(oid,due)).fetchone()
        if existing and existing['checkout_url']:
            return {'checkout_url':existing['checkout_url'],'amount_cents':due,'order_number':order['number'],'status':'aguardando pagamento'}
        # A preferência é criada antes de atualizar pedidos, sem enviar dados sensíveis de conta.
        nonce=secrets.token_hex(8)
        cur=c.execute('INSERT INTO mp_intents(order_id,amount_cents,external_reference,created_at) VALUES(?,?,?,?)',
                      (oid,due,f'esquadra:{oid}:{nonce}',now_iso()))
        iid=cur.lastrowid
        ref=f'esquadra:{oid}:{nonce}'
    # Link explícito para a conta logada; retorno nunca atualiza status sem webhook autenticado.
    payload={'items':[{'id':f'PED-{oid}','title':f'Pedido {order["number"]} · {"entrada" if percent<100 else "pagamento"}',
                       'quantity':1,'currency_id':'BRL','unit_price':due/100}],
             'external_reference':ref,
             'payer':{'email':order_customer_email(oid)},
             'notification_url':base+'/api/webhooks/mercadopago',
             'back_urls':{key:base+'/conta?pagamento='+key for key in ('success','pending','failure')},
             'auto_return':'approved',
             'statement_descriptor':'ESQUADRA'}
    data=mp_request('POST','https://api.mercadopago.com/checkout/preferences',token,
                    headers={'X-Idempotency-Key':f'esquadra-{iid}-{nonce}'},json=payload)
    link=data.get('sandbox_init_point') if os.getenv('MP_MODE')=='sandbox' else data.get('init_point')
    if not link or not urlsplit(link).hostname or not (urlsplit(link).hostname=='mercadopago.com' or urlsplit(link).hostname.endswith('.mercadopago.com') or urlsplit(link).hostname.endswith('.mercadopago.com.br')):
        raise HTTPException(502,'URL de checkout inválida retornada pelo provedor.')
    with db() as c:
        c.execute('UPDATE mp_intents SET preference_id=?,checkout_url=?,status=? WHERE id=?',
                  (str(data.get('id','')),link,'criado',iid))
    return {'checkout_url':link,'amount_cents':due,'order_number':order['number'],'status':'aguardando pagamento'}


def order_customer_email(oid):
    with db() as c:
        row=c.execute('SELECT cu.email FROM orders o JOIN customers cu ON cu.id=o.customer_id WHERE o.id=?',(oid,)).fetchone()
        return row['email'] if row else ''


def validate_mp_signature(secret,signature,request_id,data_id):
    try:
        values=dict(p.strip().split('=',1) for p in signature.split(','))
        ts=values['ts'];sig=values['v1']
        if not re.fullmatch(r'\d{9,16}',ts) or not re.fullmatch(r'[a-fA-F0-9]{64}',sig):return False
        # Restringe eventos antigos mas permite pequenas diferenças no relógio do servidor.
        stamp=int(ts)
        if stamp>10**12:stamp=stamp/1000
        if abs(datetime.now(timezone.utc).timestamp()-stamp)>600:return False
    except (ValueError,KeyError):return False
    manifest=f'id:{str(data_id).lower()};request-id:{request_id};ts:{ts};'
    actual=hmac.new(secret.encode(),manifest.encode(),'sha256').hexdigest()
    return hmac.compare_digest(actual,sig.lower())

@app.post('/api/webhooks/mercadopago')
async def mp_webhook(req:Request):
    token,secret,base=mp_config()
    body=await req.json()
    payment_id=str((body.get('data') or {}).get('id') or '')
    query_id=req.query_params.get('data.id') or req.query_params.get('id') or payment_id
    if body.get('type')!='payment' or not payment_id.isdigit() or payment_id!=query_id:
        raise HTTPException(400,'Notificação inválida.')
    if not validate_mp_signature(secret,req.headers.get('x-signature',''),req.headers.get('x-request-id',''),payment_id):
        raise HTTPException(401,'Assinatura inválida.')
    info=mp_request('GET',f'https://api.mercadopago.com/v1/payments/{payment_id}',token)
    reference=str(info.get('external_reference') or '')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        intent=c.execute('SELECT * FROM mp_intents WHERE external_reference=?',(reference,)).fetchone()
        if not intent:return {'ok':True,'ignored':True}
        order=c.execute('SELECT * FROM orders WHERE id=?',(intent['order_id'],)).fetchone()
        if not order or order['status']=='cancelado':return {'ok':True,'ignored':True}
        amount=money_cents(info.get('transaction_amount',0))
        currency=info.get('currency_id')
        if amount!=intent['amount_cents'] or currency!='BRL':
            raise HTTPException(409,'Notificação com valor ou moeda divergente.')
        status=str(info.get('status') or 'unknown')
        old=c.execute('SELECT * FROM mp_payments WHERE payment_id=?',(payment_id,)).fetchone()
        # Um pagamento antes aprovado pode receber reembolso/chargeback. Registre
        # o movimento inverso uma única vez, sem ocultá-lo nos relatórios.
        if old and old['recorded'] and status in {'refunded','charged_back'}:
            c.execute('INSERT INTO payments(order_id,amount_cents,method,notes,created_at) VALUES(?,?,?,?,?)',
                      (intent['order_id'],-old['amount_cents'],'Mercado Pago',f'Estorno confirmado na API · {payment_id}',now_iso()))
            c.execute('UPDATE mp_payments SET recorded=0,status=?,updated_at=? WHERE payment_id=?',
                      (status,now_iso(),payment_id))
            c.execute('INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)',
                      (intent['order_id'],order['status'],'Estorno ou contestação de pagamento informado pelo Mercado Pago. Necessária conferência da loja.',now_iso()))
            return {'ok':True,'payment_status':status}
        if old and (old['recorded'] or old['status'] in {'refunded','charged_back'}):return {'ok':True,'duplicate':True}
        if old and old['intent_id']!=intent['id']:raise HTTPException(409,'Pagamento com referência divergente.')
        c.execute('''INSERT INTO mp_payments(payment_id,intent_id,order_id,amount_cents,status,updated_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(payment_id) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',
                     (payment_id,intent['id'],intent['order_id'],amount,status,now_iso()))
        if status!='approved':
            c.execute('UPDATE mp_intents SET status=? WHERE id=?',(status,intent['id']))
            return {'ok':True,'payment_status':status}
        received=c.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE order_id=?',(intent['order_id'],)).fetchone()[0]
        if received+amount>order['total_cents']:raise HTTPException(409,'Valor recebido supera o pedido.')
        c.execute('INSERT INTO payments(order_id,amount_cents,method,notes,created_at) VALUES(?,?,?,?,?)',
                  (intent['order_id'],amount,'Mercado Pago',f'Pagamento verificado na API · {payment_id}',now_iso()))
        c.execute('UPDATE mp_payments SET recorded=1 WHERE payment_id=?',(payment_id,))
        c.execute("UPDATE mp_intents SET status='approved' WHERE id=?",(intent['id'],))
        note=f'Mercado Pago confirmou recebimento de R$ {amount/100:.2f}; saldo restante R$ {(order["total_cents"]-received-amount)/100:.2f}.'
        # Não altera estoque até ser possível confirmar o pedido com segurança.
        if received+amount==order['total_cents'] and not order['stock_deducted']:
            items=c.execute('SELECT * FROM order_items WHERE order_id=?',(intent['order_id'],)).fetchall()
            sufficient=all(i['made_to_order'] or (p is not None and p['stock']>=i['quantity'])
                           for i in items for p in [c.execute('SELECT stock FROM products WHERE id=?',(i['product_id'],)).fetchone()])
            if sufficient:
                for item in items:
                    if not item['made_to_order']:
                        c.execute('UPDATE products SET stock=stock-? WHERE id=?',(item['quantity'],item['product_id']))
                        c.execute('INSERT INTO stock_movements(product_id,change_qty,reason,order_id,created_at) VALUES(?,?,?,?,?)',
                                  (item['product_id'],-item['quantity'],'Pagamento confirmado pelo Mercado Pago',intent['order_id'],now_iso()))
                c.execute("UPDATE orders SET status='confirmado',stock_deducted=1 WHERE id=?",(intent['order_id'],))
                c.execute('INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)',
                          (intent['order_id'],'confirmado',note,now_iso()))
                return {'ok':True,'payment_status':status,'order_status':'confirmado'}
            note+=' Estoque precisa ser conferido pela loja.'
        c.execute('INSERT INTO order_events(order_id,status,note,created_at) VALUES(?,?,?,?)',
                  (intent['order_id'],order['status'],note,now_iso()))
        return {'ok':True,'payment_status':status}

@app.get('/api/customer/orders/{oid}/online-payments')
def my_mp_payments(oid:int,req:Request):
    cid=customer_id(req)
    with db() as c:
        if not c.execute('SELECT 1 FROM orders WHERE id=? AND customer_id=?',(oid,cid)).fetchone():
            raise HTTPException(404,'Pedido não encontrado.')
        return {'payments':[dict(x) for x in c.execute('''SELECT amount_cents,status,created_at FROM mp_intents
               WHERE order_id=? ORDER BY id DESC LIMIT 20''',(oid,))],
                'enabled':bool(os.getenv('MP_ACCESS_TOKEN') and os.getenv('MP_WEBHOOK_SECRET'))}
