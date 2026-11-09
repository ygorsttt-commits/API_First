output "dynamodb_table_name" {
  description = "Nome da tabela DynamoDB de tarefas"
  value       = aws_dynamodb_table.tasks.name
}

output "ecr_repository_url" {
  description = "Endereço do repositório ECR (usado no docker push)"
  value       = aws_ecr_repository.api.repository_url
}

output "ecs_cluster_name" {
  description = "Nome do cluster ECS"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "Nome do serviço ECS da API"
  value       = aws_ecs_service.api.name
}

output "log_group_name" {
  description = "Grupo de logs da API no CloudWatch"
  value       = aws_cloudwatch_log_group.api.name
}
