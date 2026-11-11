# Publicar ESQUADRA Commerce na Discloud (plano Platinum)

Este passo a passo funciona no celular, sem computador, pela integração com GitHub.

## 1. Reservar endereço

O subdomínio informado para a Discloud é `esquadra-commerce`. O arquivo `discloud.config` usa `ID=esquadra-commerce` (sem `.discloud.app`). Confirme no painel que o domínio foi reservado na sua conta antes do upload. Depois da ativação, o endereço esperado será `https://esquadra-commerce.discloud.app`.

## 2. Conectar o GitHub

Em Discloud > Integração GitHub, faça login com a conta proprietária `tiagogomes1214-lab`. Autorize especificamente o repositório privado `esquadra-commerce.` (o ponto final faz parte do nome). No painel, clique em `+ Upload` > `GitHub` e selecione esse repositório.

## 3. Variáveis de ambiente (OBRIGATÓRIAS ANTES DO PRIMEIRO DEPLOY)

No painel de upload, adicione variáveis **somente na Discloud**, nunca no GitHub ou no chat:

- `ESQUADRA_ADMIN_USERNAME`: usuário do administrador, com 3 ou mais caracteres.
- `ESQUADRA_ADMIN_PASSWORD`: senha única e forte com pelo menos 16 caracteres.

O sistema cria a primeira conta a partir destas variáveis, guarda somente o hash no SQLite e desativa a criação pública do primeiro administrador. Caso as variáveis estejam ausentes, a aplicação não inicia no primeiro deploy para evitar que outra pessoa assuma o painel.

## 4. Verificar início

O arquivo `discloud.config` executa `python discloud_start.py`, que inicia FastAPI em `0.0.0.0:8080` e ativa cookies de sessão seguros via HTTPS. Uma vez publicado, teste `/health`, a vitrine em `/` e o login em `/admin`.

O `BUILD` instala o `requirements.txt`. O plano Platinum é exigido para sites.

## 5. Dados, limites e segurança

O SQLite é salvo por padrão em `data/esquadra.sqlite3` e imagens em `data/uploads`. **Não suponha que esses dados sobrevivam a atualizações/reinstalações**: valide a persistência da Discloud e estabeleça backup externo do diretório `data` ANTES de receber pedidos reais.

Durante os primeiros testes, não insira dados de clientes reais, não compartilhe o link publicamente e não anuncie a loja como apta a vender em produção. Ainda faltam testes de segurança e operações, monitoramento, backups, proteção contra tentativas de login e conformidade com a LGPD.

As notas PDF são **comprovantes comerciais sem validade fiscal**, não NF-e/NFC-e. Não há cobrança online automática.

Documentação: https://docs.discloud.com/api-and-integrations/github-integration e https://docs.discloud.com/how-to-host/websites-and-apis
