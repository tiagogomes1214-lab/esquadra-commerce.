# ESQUADRA Commerce 2.0

Sistema demonstrativo local de gestão comercial e loja virtual para **portas, janelas, balcões e esquadrias de alumínio/madeira**. Identidade preto e branco, menu administrativo lateral, página do cliente e comprovantes comerciais personalizados.

## NOVO — Conta de clientes e acompanhamento online

1. O cliente entra na loja (`/`) e adiciona produtos ao carrinho.
2. Ao finalizar, se não estiver autenticado, é direcionado para **`/conta`**, onde cria a conta ou entra com e-mail e senha. O carrinho é preservado no navegador.
3. O pedido é registrado como **novo**, associado à conta do cliente, e NÃO desconta o estoque até a confirmação da loja.
4. No painel (`/admin`), o responsável atualiza a situação do pedido: novo, aguardando pagamento, confirmado, em produção, pronto para retirada, em transporte, instalação agendada, instalado, entregue, cancelado.
5. O cliente entra novamente em **Minha conta > Meus pedidos** para ver número, itens, valores, histórico de status e previsão de entrega. Pode imprimir seu comprovante comercial.
6. Um cliente **não pode ler** pedidos, propostas ou PDFs de outros clientes.

## Orçamentos sob medida

- Cliente logado informa produto, largura/altura em milímetros, acabamento, material, vidro, quantidade e observações.
- Em **Orçamentos** no painel, o administrador responde com preço unitário e validade.
- O cliente vê a proposta, imprime PDF e aprova; a aprovação gera um pedido **novo**, sem cobrar automaticamente.
- Itens originados de orçamento são tratados como sob encomenda: não há baixa automática no estoque de produtos de prateleira ao confirmar.

## Principais funções no painel

| Módulo | Funções |
|---|---|
| Visão geral | Pedidos, produtos, alertas e valores comerciais |
| Pedidos | Vendas manuais, alteração de situação, histórico, previsão de entrega, recebimentos e devoluções manuais |
| Produtos | Cadastro, edição, fotos principais, galeria (até 8 fotos adicionais), especificações, materiais, vidro e medidas |
| Orçamentos | Responder propostas, PDF personalizado e aprovação pelo cliente |
| Clientes | Histórico de compras, nome, telefone, e-mail e endereço |
| Estoque | Baixa somente na confirmação, devolução em cancelamento e ajustes registrados |
| Fornecedores | Cadastro e consulta |
| Compras | Registro e recebimento com reposição de estoque |
| Financeiro | Registro de pagamentos, reembolsos, despesas pagas e pendentes; saldos |
| Operação | Tarefas de fabricação, instalação, entrega e retirada com responsável e data |
| Garantias | Abertura e atualização de atendimentos |
| Equipe | Cadastro operacional de colaboradores e função (não cria logins por cargo ainda) |
| Relatórios | Resumo e exportação de pedidos em CSV |
| Documentos | Comprovante de pedido, proposta comercial e ordem de entrega em PDF; logotipo configurável |

## Instalar no Windows (VS Code)

Requisitos: Python 3.12 ou mais recente, com pip.

1. Extraia o ZIP e abra **ESQUADRA_Commerce_v2** no VS Code.
2. Abra o terminal PowerShell dentro da pasta e digite:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

3. No navegador:

- **Loja:** http://127.0.0.1:8000
- **Minha conta:** http://127.0.0.1:8000/conta
- **Painel administrativo:** http://127.0.0.1:8000/admin

No primeiro acesso ao painel, crie o usuário administrativo e uma senha forte. Cadastre uma conta de cliente diferente para simular uma compra. A loja vem com **oito produtos ilustrativos**; substitua fotos, preços e dados comerciais.

Para rodar de novo: ative `.venv` e execute `python run.py`.

## Testes automatizados

```powershell
python -m unittest discover -s tests -v
```

Os testes cobrem contas separadas de clientes, proteção dos PDFs, compra, status, estoque, cancelamento, reembolso manual, orçamento, compras, financeiro e demais endpoints. Os testes usam um banco temporário para não mexer em dados reais.

## Hospedagem / Docker

O arquivo `Dockerfile` copia `app.py` e `v2.py` e sobe o servidor na porta `PORT` ou `8080`. Pode executar `docker compose up --build`; o volume `esquadra-data` mantém banco, senhas e uploads entre reinicializações do container.

Para publicação HTTPS, configure `COOKIE_SECURE=1` e um endereço público protegido. Garanta **volume persistente** na hospedagem (SQLite é gravado no diretório `data/`). Uma plataforma que recria o container sem persistência perderá pedidos e fotos. O app serve `0.0.0.0:8080` com `start_server.py`.

Faça backup periódico de **todo o diretório `data/`**, com atenção ao banco e imagens. Não disponibilize acesso administrativo inicial na internet antes de configurar a conta com segurança.

## Atenção: limites e itens para a implantação definitiva

- **Não processa pagamento online.** Pix/cartão são registrados manualmente no painel. Integração com gateway, webhook de confirmação e conciliação são trabalhos separados.
- **Não emite NF-e/NFC-e fiscal.** Os PDFs são documentos comerciais, sem autorização da SEFAZ. A emissão fiscal requer integração própria, certificado/dados tributários e validação contábil.
- **Não calcula frete automaticamente**, não contrata transportadoras e não envia mensagens automáticas pelo WhatsApp/e-mail.
- **Não há permissões de login por funcionário**, recuperação de senha por e-mail, auditoria completa nem rate limiting de produção; a tabela Equipe é apenas cadastro operacional.
- **Não é um ERP homologado ou pronto para uso comercial em produção** sem endurecimento de segurança, revisão LGPD, políticas de privacidade, testes adicionais, rotina de backup/restauração e homologação dos processos da loja.
- O SQLite atende ao teste e uso inicial; para grande volume/múltiplos trabalhadores simultâneos, avaliar PostgreSQL.
- Modelos ilustrativos e valores de demonstração não são preços de mercado.

## Estrutura técnica

- `app.py` — backend FastAPI original, pedidos, estoque, PDF de comprovantes e configurações.
- `v2.py` — novas rotas de conta, rastreamento, orçamentos, finanças, compras e serviços; migração das tabelas antigas.
- `templates/store.html` / `static/js/store.js` — vitrine e carrinho.
- `templates/account.html` / `static/js/account.js` / `static/css/account.css` — cadastro, login, pedidos e orçamentos do cliente.
- `templates/admin.html` / `static/js/admin.js` / `static/js/admin-extra.js` — gestão interna.
- `tests/test_flows.py` — teste automático principal.
- `static/img` — imagens ilustrativas.
- `data/` — banco e imagens locais (não incluídos no ZIP).

**Atualizar a versão antiga:** faça backup do diretório `data/` da versão 1, copie para a pasta da versão 2 antes da primeira inicialização e execute. As novas tabelas são criadas automaticamente, mantendo dados antigos. Faça uma cópia de segurança antes de migrar e teste primeiro em uma cópia do banco.

## Atualização da instalação na Discloud

Este pacote contém `discloud.config` e `discloud_start.py` da instalação que já usa o ID `esquadra-commerce`. O script da hospedagem inicia a API com host 0.0.0.0 e porta 8080, desliga os produtos demonstrativos e impede que o primeiro visitante crie um administrador. O banco existente é migrado sem apagar produtos e pedidos; os pedidos da versão 1 são marcados como estoque já baixado para evitar dedução dupla.

**Antes de atualizar um app com vendas reais:** faça backup verificado de `data/` (banco, segredo de sessão e fotos) no painel da Discloud. Atualizar o repositório no GitHub não confirma que o provedor mantém `data/` entre deploys. Os arquivos `.env`/dados nunca devem ser publicados no repositório.

A integração GitHub da Discloud pode exigir `Update/Reinstall` ou novo upload pelo painel para aplicar o commit; confirme o status e o endpoint `/health` após a atualização.

Veja também [Vendas Pro 3.0](VENDAS_PRO_3.md).
