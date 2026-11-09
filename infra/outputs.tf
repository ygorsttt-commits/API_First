output "dynamodb_table_name" {
  description = "Nome da tabela DynamoDB de tarefas"
  value       = aws_dynamodb_table.tasks.name
}

output "ecr_repository_url" {
  description = "Endereço do repositório ECR (usado no docker push)"
  value       = aws_ecr_repository.api.repository_url
}
