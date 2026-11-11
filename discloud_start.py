"""Inicialização da loja na Discloud (HTTPS no proxy, porta 8080)."""
import os
import uvicorn

# Sempre ative essas proteções quando o app for iniciado pela Discloud.
os.environ['ESQUADRA_PUBLIC_DEPLOYMENT'] = '1'
os.environ['COOKIE_SECURE'] = '1'
os.environ['DEMO_SEED'] = '0'
os.environ['PORT'] = '8080'

if __name__ == '__main__':
    uvicorn.run('app:app', host='0.0.0.0', port=8080, workers=1)
