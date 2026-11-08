"""Conexão com o DynamoDB (Local no dev, real na AWS)."""

import os

import boto3


def get_table():
    """Retorna a tabela de tarefas.

    DYNAMODB_ENDPOINT definido -> DynamoDB Local (docker compose).
    Sem ele -> DynamoDB real da AWS (credenciais vêm do ECS).
    """
    dynamodb = boto3.resource(
        "dynamodb",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        endpoint_url=os.getenv("DYNAMODB_ENDPOINT") or None,
    )
    return dynamodb.Table(os.getenv("TABLE_NAME", "tasks"))


def create_table_if_missing() -> None:
    """Cria a tabela no ambiente local. Na AWS, quem cria é o Terraform."""
    table = get_table()
    client = table.meta.client
    if table.name in client.list_tables()["TableNames"]:
        return
    client.create_table(
        TableName=table.name,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
