import uvicorn
if __name__ == '__main__':
    print('ESQUADRA Commerce: http://127.0.0.1:8000')
    print('Painel administrativo: http://127.0.0.1:8000/admin')
    uvicorn.run('app:app', host='127.0.0.1', port=8000, reload=False)
