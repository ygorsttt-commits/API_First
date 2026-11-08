# Imagem base: Python 3.12 em Linux enxuto
FROM python:3.12-slim

# Pasta de trabalho dentro do container
WORKDIR /code

# Instala as bibliotecas primeiro (fica em cache se requirements.txt não mudar)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o projeto
COPY . .

EXPOSE 8000

# Comando padrão (produção/AWS). Em dev, o docker-compose troca por um com --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
