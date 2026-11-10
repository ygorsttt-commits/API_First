variable "allowed_cidr" {
  description = "Faixa de IP autorizada a acessar a API (ex.: 187.0.0.1/32). Definida em terraform.tfvars"
  type        = string

  validation {
    condition     = can(cidrhost(var.allowed_cidr, 0))
    error_message = "allowed_cidr deve ser um CIDR válido, ex.: 187.0.0.1/32."
  }
}

variable "aws_profile" {
  description = "Perfil do AWS CLI (SSO) no PC. null no CI, que autentica via OIDC"
  type        = string
  default     = null
}

variable "aws_region" {
  description = "Região da AWS onde os recursos serão criados"
  type        = string
  default     = "us-east-1"
}

variable "container_port" {
  description = "Porta em que a API escuta dentro do container"
  type        = number
  default     = 8000
}

variable "ecr_images_to_keep" {
  description = "Quantidade de imagens mantidas no ECR (as mais antigas são apagadas)"
  type        = number
  default     = 3
}

variable "image_tag" {
  description = "Tag da imagem no ECR a ser executada (hash curto do commit)"
  type        = string
}

variable "project_name" {
  description = "Prefixo usado no nome dos recursos"
  type        = string
  default     = "api-first"
}
