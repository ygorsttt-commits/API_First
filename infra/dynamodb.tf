# Tabela de tarefas: mesma estrutura do DynamoDB Local (chave "id" do tipo texto)
resource "aws_dynamodb_table" "tasks" {
  name         = "${var.project_name}-tasks"
  billing_mode = "PAY_PER_REQUEST" # paga só pelo uso, sem capacidade reservada
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}
