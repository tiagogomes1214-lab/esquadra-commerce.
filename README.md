# ESQUADRA Commerce

Loja virtual + painel administrativo para comércio de portas, janelas e esquadrias. Design preto/branco, responsivo e adaptável ao nome da sua empresa.

## Funcionalidades incluídas

- **Vitrine pública:** catálogo, categorias, busca, carrinho, formulário de pedido e valores estimados.
- **Painel administrativo:** acesso com login e senha configurados no primeiro uso.
- **Produtos:** criar/editar, SKU, categoria, medidas, descrição, preço, estoque, ativo/inativo e **upload de fotos**.
- **Pedidos:** registrar vendas manuais, receber pedidos da loja, alterar status, calcular totais e descontos, repor estoque em cancelamentos.
- **Clientes:** cadastro automático a partir de pedidos e histórico de compras.
- **Notas personalizadas:** gerar e imprimir **comprovantes de venda em PDF** com logo, dados da empresa, cliente, itens, medidas, preço, descontos e mensagem de rodapé.
- **Personalização:** nome da loja, logotipo, telefone, e-mail, Instagram, endereço, título e rodapé do comprovante.
- **SQLite:** dados persistem em `data/esquadra.sqlite3`. Fotos enviadas ficam em `data/uploads/`.

## Como executar no Windows

1. Extraia o ZIP e abra a pasta no VS Code.
2. No terminal, rode:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

3. Acesse **http://127.0.0.1:8000** para abrir a loja.
4. Acesse **http://127.0.0.1:8000/admin** para abrir o painel. **Na primeira visita, crie seu usuário e sua senha**.
5. Em **Configurações**, coloque dados reais da empresa, faça o upload da logo e personalize a nota. Em **Produtos**, substitua as imagens ilustrativas pelas fotos reais e revise os preços.

Para rodar novamente em outro dia:

```powershell
.venv\Scripts\activate
python run.py
```

## Dados de demonstração (opcionais)

Se quiser começar com 5 vendas de exemplo na primeira execução, inicie com a variável `DEMO_SEED=1`. No PowerShell:

```powershell
$env:DEMO_SEED="1"
python run.py
```

Os pedidos criados aparecerão como demonstrativos. É possível removê-los em **Configurações** ou **Visão geral**. Os 8 produtos que aparecem inicialmente são **exemplos** com preços ilustrativos, não preços oficiais.

## Implantação e segurança

- Para uso público, configure HTTPS, `COOKIE_SECURE=1`, reverse proxy, domínio, backups frequentes do diretório `data`, e armazenamento persistente. Restrinja criação de administradores; a conta só é criada se ainda não existir nenhuma.
- SQLite é adequado para pequeno volume e uso inicial. Para alta concorrência e escala, migrar para PostgreSQL.
- Não há gateway de pagamentos, cálculo de frete, emissão de NF-e/NFC-e autorizada pela SEFAZ ou integração com transportadoras. A compra da vitrine **envia um pedido**, mas não recebe pagamento online.
- Os comprovantes em PDF são **documentos comerciais, sem validade fiscal**. Para documentos fiscais verdadeiros, será necessária integração homologada e dados tributários adequados.
- Antes de publicar em produção, recomenda-se adicionar: recuperação de senha, proteção antiabuso/rate limiting, política de privacidade conforme LGPD, controle de permissões por usuário, e fluxo de aprovação de orçamento, entrega e instalação.
- Não coloque dados reais de clientes em um ambiente de demonstração compartilhado.

## Estrutura do projeto

- `app.py` — API FastAPI, regras de negócio, banco e PDF das notas.
- `run.py` — inicialização local.
- `templates/store.html` — loja pública.
- `templates/admin.html` — painel administrativo.
- `static/css/styles.css` — aparência responsiva.
- `static/js/store.js` — catálogo e carrinho.
- `static/js/admin.js` — gestão de produtos, vendas, clientes e configurações.
- `static/img/` — ilustrações de exemplo, substituíveis pelo upload.
- `data/` — banco e arquivos da empresa (não incluídos no ZIP depois de testes).

Projeto demonstrativo local. Use dados e logotipo próprios da empresa antes de apresentar a clientes.

## Rodar em Docker / outro servidor

Com Docker instalado, execute `docker compose up --build` e abra `http://localhost:8080`.
O banco e as fotos permanecem no volume `esquadra-data`.

Alternativamente, após instalar os pacotes, rode `python start_server.py`: ele escuta em `0.0.0.0` e na porta configurada por `PORT` (padrão: 8080).

**Importante:** conclua a criação da conta administrativa em um ambiente seguro *antes* de publicar o primeiro acesso na internet. Não exponha o painel sem HTTPS e proteção adequada. O projeto é uma base funcional e exige endurecimento de segurança, testes e integrações para operação comercial em produção.
