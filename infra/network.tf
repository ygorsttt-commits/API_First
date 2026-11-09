# Usa a VPC padrão da conta (grátis, já existe em toda conta AWS)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Firewall do container: só o IP permitido acessa a porta da API
resource "aws_security_group" "api" {
  name        = "${var.project_name}-api"
  description = "Acesso a API na porta ${var.container_port}"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "api_http" {
  security_group_id = aws_security_group.api.id
  description       = "API a partir do IP permitido"
  cidr_ipv4         = var.allowed_cidr
  ip_protocol       = "tcp"
  from_port         = var.container_port
  to_port           = var.container_port
}

# Saída liberada: o container precisa baixar a imagem do ECR e falar com o DynamoDB
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.api.id
  description       = "Saida para a internet (ECR, DynamoDB, CloudWatch)"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
