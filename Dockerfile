# Imagem base: Python 3.12 em Linux enxuto
FROM python:3.12-slim

# Aplica correções de segurança dos pacotes do sistema
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# Pasta de trabalho dentro do container
WORKDIR /code

# Instala as bibliotecas primeiro (fica em cache se os requirements não mudarem)
# INSTALL_DEV=true (só no docker-compose) adiciona ferramentas de teste e lint
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# Copia o projeto
COPY . .

EXPOSE 8000

# Comando padrão (produção/AWS). Em dev, o docker-compose troca por um com --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
