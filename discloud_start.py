"""Inicialização segura da aplicação ESQUADRA na Discloud."""
import os
import uvicorn
os.environ['ESQUADRA_PUBLIC_DEPLOYMENT']='1'
os.environ['COOKIE_SECURE']='1'
os.environ['DEMO_SEED']='0'
os.environ['PORT']='8080'
if __name__=='__main__':
    uvicorn.run('app:app', host='0.0.0.0', port=8080, workers=1)
