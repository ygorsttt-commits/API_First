# Repositório de imagens Docker da API
resource "aws_ecr_repository" "api" {
  name                 = var.project_name
  image_tag_mutability = "IMMUTABLE" # uma tag (ex.: commit) nunca é sobrescrita
  force_delete         = true        # permite o destroy mesmo com imagens dentro (estudo)

  image_scanning_configuration {
    scan_on_push = true # scan básico de vulnerabilidades, gratuito
  }
}

# Mantém só as N imagens mais recentes para não acumular custo
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Manter apenas as ${var.ecr_images_to_keep} imagens mais recentes"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = var.ecr_images_to_keep
      }
      action = { type = "expire" }
    }]
  })
}
