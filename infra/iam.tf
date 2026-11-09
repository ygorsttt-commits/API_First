data "aws_caller_identity" "current" {}

# Quem pode "vestir" as roles abaixo: só tarefas do ECS desta conta
data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# Role de EXECUÇÃO: usada pelo ECS para baixar a imagem e gravar logs
resource "aws_iam_role" "ecs_execution" {
  name               = "${var.project_name}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Role da TAREFA: usada pelo código da API (boto3). Só acessa a tabela de tarefas.
resource "aws_iam_role" "ecs_task" {
  name               = "${var.project_name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "dynamodb_tasks" {
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.tasks.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task_dynamodb" {
  name   = "dynamodb-tasks"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.dynamodb_tasks.json
}
