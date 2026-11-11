# ESQUADRA Commerce 3.0 — Vendas Pro

Sistema de vendas para portas, janelas e esquadrias. Esta versão atualiza a 2.0 **sem apagar os dados**. As tabelas novas são criadas automaticamente.

## Recursos novos

- `/configurador`: largura, altura, acabamento, tipo de vidro, quantidade de folhas, abertura e preço estimado. Só mostra preço quando o vendedor configura as regras do produto, e a proposta final continua exigindo aprovação da loja.
- Painel > Vendas Pro: regras de preço por m², mínimo, adicionais por vidro e folhas; zonas de entrega por prefixo de CEP, prazos e custos; cupons com validade e limite de usos; descontos para clientes profissionais aprovados; acessórios relacionados.
- Carrinho: cupom, retirada ou entrega com CEP. O servidor recalcula preços, descontos e frete.
- CRM: oportunidades, motivos de perda, próximos contatos e carrinhos salvos somente com consentimento do cliente. **Não há envios de WhatsApp ou e-mail automáticos.**
- Área do cliente: entrada de 30%, 50% ou quitação do saldo via Mercado Pago Checkout Pro (quando configurado). Parcelamento no cartão depende da conta e do checkout do provedor.
- Avaliações: apenas compradores de pedidos entregues/instalados podem avaliar; publicação exige moderação.
- Indicadores: faturamento registrado, pagamentos recebidos e conversão de orçamentos (distintos), visualização de produtos agregada.

## Configurar Mercado Pago na Discloud

As seguintes variáveis ficam **somente no painel privado de hospedagem**, nunca no GitHub, no código nem no chat:

- `MP_ACCESS_TOKEN`: token privado de integração da conta Mercado Pago da loja.
- `MP_WEBHOOK_SECRET`: segredo de assinatura da configuração de webhooks.
- `ESQUADRA_BASE_URL`: endereço HTTPS público, sem barra no fim, exemplo `https://esquadra-commerce.discloud.app`.
- `MP_MODE`: `production` na conta real; `sandbox` ao testar com as credenciais adequadas.

Na configuração Webhooks do Mercado Pago, associe o evento `payment` à URL `https://SEU-DOMINIO/api/webhooks/mercadopago`.

O servidor cria preferências via `/checkout/preferences`, redireciona o cliente para o Mercado Pago e **não confirma o pagamento pelo redirecionamento do navegador**. O webhook assinado é conferido por HMAC, o pagamento é consultado na API do Mercado Pago, valor e moeda são validados, e a baixa é idempotente. Estornos são registrados com sinal negativo e sinalizam revisão manual. Nunca inclua o token em scripts front-end.

## Migração e homologação

1. **Antes de atualizar**, faça backup restaurável de todo `data/` da Discloud: `esquadra.sqlite3`, fotos e segredo de sessão.
2. Confirme armazenamento persistente. Sem volume permanente, uma reinstalação pode apagar o banco e os uploads.
3. Rode `python -m unittest discover -s tests -v` no ambiente de teste e confira `/health`.
4. Configure preços reais de cada produto no painel e regiões de entrega. Quando não há faixa de CEP cadastrada, a loja só permite retirada.
5. Teste com credenciais de teste do Mercado Pago e webhooks assinados, também os cenários pendente, aprovado, duplicado e estorno antes de liberar cobranças.
6. Verifique pagamento, produção, frete, garantia, comprovante e acompanhamento de pedido com usuários de teste.

## Limites

- PDFs comerciais personalizados **não** são NF-e/NFC-e fiscais.
- O frete é calculado por tabela local, não por transportadora contratada.
- A estimativa de esquadria não substitui orçamento técnico nem inclui necessariamente instalação e mão de obra.
- Não há integrações reais de WhatsApp, mensagens automáticas, recuperação de senha ou controle de acesso individual por cargo.
- Antes da venda pública, revise LGPD, segurança, retenção, backups, conciliação e a situação fiscal com profissionais competentes.
- A configuração da conta de recebimentos deve ser feita pelo representante legal elegível da empresa, de acordo com as regras do Mercado Pago.

## Testes

`python -m unittest discover -s tests -v`

Os testes incluem caixa de pagamento simulado, validação de assinatura e duplicidade de notificações, cupom, frete, preços estimados, autorização por cliente e privacidade de carrinhos.

Arquivos principais: `v3.py`, `static/js/admin-sales.js`, `static/js/account-sales.js`, `static/js/configurator.js`, `templates/configurator.html`, `static/css/sales.css`, `static/css/sales-extras.css`, `tests/test_sales.py`.
