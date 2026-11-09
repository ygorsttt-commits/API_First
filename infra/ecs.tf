resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 1 # estudo: logs somem em 1 dia (custo mínimo)
}

resource "aws_ecs_cluster" "main" {
  name = var.project_name
}

# "Receita" do container: imagem, CPU, memória, variáveis e logs
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project_name}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256 # 0,25 vCPU (menor tamanho do Fargate)
  memory                   = 512 # 0,5 GB
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true

    portMappings = [{
      containerPort = var.container_port
      protocol      = "tcp"
    }]

    # Sem DYNAMODB_ENDPOINT: a API usa o DynamoDB real da AWS
    environment = [
      { name = "TABLE_NAME", value = aws_dynamodb_table.tasks.name },
      { name = "AWS_REGION", value = var.aws_region },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

# Mantém 1 container rodando (se cair, o ECS sobe outro)
resource "aws_ecs_service" "api" {
  name                  = "${var.project_name}-api"
  cluster               = aws_ecs_cluster.main.id
  task_definition       = aws_ecs_task_definition.api.arn
  desired_count         = 1
  launch_type           = "FARGATE"
  wait_for_steady_state = true # o apply só termina quando o container estiver rodando

  network_configuration {
    subnets          = data.aws_subnets.default.ids
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # sem ALB: o container recebe um IP público próprio
  }
}
