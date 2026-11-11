const ICONS={
 bag:'<path d="M5 8h14l-1 13H6L5 8Z"/><path d="M9 9V6a3 3 0 0 1 6 0v3"/>',
 'arrow-right':'<path d="M5 12h14m-6-6 6 6-6 6"/>',
 'arrow-left':'<path d="M19 12H5m6-6-6 6 6 6"/>',
 'arrow-up-right':'<path d="M7 17 17 7M8 7h9v9"/>',
 x:'<path d="M18 6 6 18M6 6l12 12"/>',
 check:'<path d="m4 12 5 5L20 6"/>',
 ruler:'<path d="M4 16 16 4l4 4L8 20l-4-4zM9 11l2 2m2-6 2 2"/>',
 shield:'<path d="M12 2 4 5v7c0 5 3 8 8 10 5-2 8-5 8-10V5l-8-3z"/><path d="m8 12 3 3 5-6"/>',
 search:'<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',minus:'<path d="M5 12h14"/>'};
const icon = k => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[k]||ICONS.bag}</svg>`;
const money = v => (Number(v||0)/100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const esc = v => String(v??'').replace(/[&<>"']/g,k=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[k]));
let products=[],settings={},cart=new Map(),activeCategory='Todos',query='';
try{cart=new Map(JSON.parse(localStorage.getItem('esquadra_cart')||'[]'));}catch{}
function persistCart(){localStorage.setItem('esquadra_cart',JSON.stringify([...cart]));}
const $=s=>document.querySelector(s);
function symbols(root=document){root.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));}
let toastTimer;
function toast(msg,error=false){const el=$('#toast');el.textContent=msg;el.className=`toast${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.add('hidden'),3700);}
function totals(){let subtotal=0,count=0;cart.forEach((qty,id)=>{const p=products.find(x=>x.id===id);if(p){subtotal+=p.price_cents*qty;count+=qty;}});return {subtotal,count};}
async function init(){symbols();try{const r=await fetch('/api/catalog');if(!r.ok)throw Error();const res=await r.json();products=res.products;settings=res.settings;applySettings();renderFilters();renderProducts();renderCart();}catch{toast('Não foi possível carregar o catálogo.',true);}}
function applySettings(){document.title=`${settings.store_name} — Portas e Janelas`;$('#store-brand').innerHTML=esc(settings.store_name)+'<span class="brand-dot">.</span>';$('#store-tagline').textContent=settings.tagline;$('#store-contact').textContent=`${settings.phone} · ${settings.instagram}`;document.querySelectorAll('.store-footer .brand').forEach(x=>x.innerHTML=esc(settings.store_name)+'<span class="brand-dot">.</span>');}
function renderFilters(){const cats=['Todos',...new Set(products.map(p=>p.category))];$('#filter-pills').innerHTML=cats.map(c=>`<button class="filter-pill ${activeCategory===c?'active':''}" data-filter="${esc(c)}">${esc(c)}</button>`).join('');}
function renderProducts(){const results=products.filter(p=>(activeCategory==='Todos'||p.category===activeCategory)&&(`${p.name} ${p.sku} ${p.category}`.toLowerCase().includes(query.toLowerCase())));
$('#catalog-count').textContent=`${results.length} produto${results.length===1?'':'s'} encontrado${results.length===1?'':'s'}`;
$('#product-grid').innerHTML=results.length?results.map(p=>`<article class="store-product"><div class="store-product-photo"><img src="${esc(p.image_url||'/static/img/porta-aluminio.svg')}" alt="${esc(p.name)}" loading="lazy"/><span class="product-image-tag">${esc(p.dimension||'Sob medida')}</span></div><div class="store-product-info"><div class="store-product-cat">${esc(p.category)}</div><h3>${esc(p.name)}</h3><div class="store-product-meta">${p.stock>0?'Em estoque ·':'Sob consulta ·'} Código ${esc(p.sku)}</div><div class="store-product-bottom"><strong>${money(p.price_cents)}</strong><a class="store-quote-action" href="/configurador?produto=${p.id}" title="Solicitar orçamento com medidas">Personalizar</a><button class="add-cart" data-add="${p.id}" title="Adicionar ao carrinho" ${p.stock<1?'disabled style="opacity:.4"':''}>${icon('plus')}</button></div></div></article>`).join(''):'<div class="catalog-empty">Nenhum produto encontrado. Tente outra pesquisa.</div>';
}
function openCart(){renderCart();$('#cart-backdrop').classList.remove('hidden');$('#cart-drawer').classList.add('open');}
function closeCart(){$('#cart-backdrop').classList.add('hidden');$('#cart-drawer').classList.remove('open');}
function renderCart(){persistCart();const t=totals();$('#cart-count').textContent=t.count;$('#drawer-count').textContent=`(${t.count})`;$('#cart-total').textContent=money(t.subtotal);$('#checkout-total').textContent=money(t.subtotal);$('#checkout-open').disabled=t.count===0;
const items=[...cart.entries()].map(([id,qty])=>{const p=products.find(x=>x.id===id);if(!p)return '';return `<div class="cart-item"><img src="${esc(p.image_url||'/static/img/porta-aluminio.svg')}" alt=""/><div class="cart-item-content"><strong>${esc(p.name)}</strong><span>${esc(p.dimension)} · ${esc(p.sku)}</span><div class="cart-item-bottom"><div class="cart-qty"><button data-qty="${p.id}" data-delta="-1" aria-label="Diminuir">−</button><span>${qty}</span><button data-qty="${p.id}" data-delta="1" aria-label="Aumentar">+</button></div><strong>${money(p.price_cents*qty)}</strong></div></div></div>`;}).join('');$('#cart-body').innerHTML=t.count?items:`<div class="cart-empty">${icon('bag')}<h3>Seu carrinho está vazio</h3><p>Explore nosso catálogo e escolha seus produtos.</p></div>`;
}
function closeCheckout(){$('#checkout-layer').classList.add('hidden');}
$('#filter-pills').addEventListener('click',e=>{const b=e.target.closest('[data-filter]');if(!b)return;activeCategory=b.dataset.filter;renderFilters();renderProducts();});
$('#store-search').addEventListener('input',e=>{query=e.target.value;renderProducts();});
$('#product-grid').addEventListener('click',e=>{const b=e.target.closest('[data-add]');if(!b)return;const id=Number(b.dataset.add),p=products.find(x=>x.id===id);if(!p||p.stock<1)return;const current=cart.get(id)||0;if(current>=p.stock)return toast('Quantidade máxima disponível em estoque.',true);cart.set(id,current+1);renderCart();toast('Produto adicionado ao carrinho.');});
$('#cart-body').addEventListener('click',e=>{const b=e.target.closest('[data-qty]');if(!b)return;const id=Number(b.dataset.qty),p=products.find(x=>x.id===id),newQty=(cart.get(id)||0)+Number(b.dataset.delta);if(newQty>p.stock)return toast('Limite de estoque atingido.',true);if(newQty<=0)cart.delete(id);else cart.set(id,newQty);renderCart();});
$('#cart-open').onclick=openCart;$('#cart-close').onclick=closeCart;$('#cart-backdrop').onclick=closeCart;
$('#checkout-open').onclick=async()=>{const m=await fetch('/api/customer/me').then(r=>r.json()).catch(()=>({authenticated:false}));if(!m.authenticated){location.href='/conta?next=checkout';return;}closeCart();$('#checkout-success').classList.add('hidden');$('#checkout-form').classList.remove('hidden');$('#checkout-layer').classList.remove('hidden');};
$('#checkout-close').onclick=closeCheckout;$('#checkout-finish').onclick=()=>{closeCheckout();window.scrollTo({top:0,behavior:'smooth'});};
$('#checkout-layer').addEventListener('click',e=>{if(e.target.id==='checkout-layer')closeCheckout();});
$('#checkout-form').onsubmit=async e=>{e.preventDefault();const b=$('#checkout-submit');b.disabled=true;b.textContent='Enviando pedido...';const data=Object.fromEntries(new FormData(e.currentTarget).entries());const payload={...data,items:[...cart.entries()].map(([product_id,quantity])=>({product_id,quantity}))};try{const r=await fetch('/api/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const res=await r.json();if(!r.ok)throw Error(typeof res.detail==='string'?res.detail:'Não foi possível enviar o pedido.');$('#success-number').textContent=res.number;cart.clear();renderProducts();renderCart();$('#checkout-form').reset();$('#checkout-form').classList.add('hidden');$('#checkout-success').classList.remove('hidden');}catch(err){toast(err.message,true);}finally{b.disabled=false;b.innerHTML=`Enviar pedido ${icon('arrow-right')}`;}};
document.querySelectorAll('.category-tile').forEach(el=>el.addEventListener('click',()=>{activeCategory=el.dataset.category;renderFilters();renderProducts();}));
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeCart();closeCheckout();}});
init().then(()=>{if(location.hash==='#checkout'&&cart.size)$('#checkout-open').click();});

// Vendas Pro: simulador de frete/cupom sem alterar valores no navegador.
async function previewPurchase(){const el=document.querySelector('#sales-checkout-preview');if(!el||!cart.size)return;
 const form=document.querySelector('#checkout-form');const mode=form.elements.delivery_mode.value;
 try{const r=await fetch('/api/sales/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:[...cart].map(([product_id,quantity])=>({product_id,quantity})),coupon:form.elements.coupon.value,cep:form.elements.cep.value,delivery_mode:mode})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Confira o frete ou cupom.');el.textContent=`Itens ${money(d.subtotal_cents)} · Descontos ${money(d.discount_cents)} · Frete ${money(d.shipping_cents)} · Total ${money(d.total_cents)}`;
 }catch(e){el.textContent=e.message;}}
for(const el of document.querySelectorAll('#checkout-form [name="coupon"],#checkout-form [name="cep"],#checkout-form [name="delivery_mode"]'))el.addEventListener('change',previewPurchase);
const oldCheckout=document.querySelector('#checkout-open').onclick;
document.querySelector('#checkout-open').onclick=async()=>{await oldCheckout();if(!document.querySelector('#checkout-layer').classList.contains('hidden'))previewPurchase();};
document.querySelector('#save-cart-lead').onclick=async()=>{try{const consent=document.querySelector('#cart-recovery-consent').checked;const r=await fetch('/api/customer/cart-draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({consent,items:[...cart].map(([product_id,quantity])=>({product_id,quantity}))})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Faça login para salvar o carrinho.');toast(d.saved?'Carrinho salvo com autorização para contato.':'Preferência removida.');}catch(e){toast(e.message,true)}};
const oldCartRender=renderCart;renderCart=function(){oldCartRender();const id=[...cart.keys()][0];const box=document.querySelector('#suggested-accessories');if(!box)return;box.innerHTML='';if(!id)return;
fetch(`/api/sales/accessories/${id}`).then(r=>r.json()).then(d=>{box.innerHTML=d.accessories?.length?'<strong>Combine com acessórios</strong>'+d.accessories.map(p=>`<button type="button" data-addon="${p.id}">${esc(p.name)} · ${money(p.price_cents)} +</button>`).join(''):''}).catch(()=>{});};
document.querySelector('#suggested-accessories').onclick=e=>{const b=e.target.closest('[data-addon]');if(!b)return;const id=Number(b.dataset.addon),p=products.find(x=>x.id===id);if(!p||p.stock<=(cart.get(id)||0))return toast('Sem estoque disponível.',true);cart.set(id,(cart.get(id)||0)+1);renderCart();};
