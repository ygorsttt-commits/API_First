variable "aws_profile" {
  description = "Perfil do AWS CLI usado para autenticar (SSO)"
  type        = string
  default     = "estudos"
}

variable "aws_region" {
  description = "Região da AWS onde os recursos serão criados"
  type        = string
  default     = "us-east-1"
}

variable "ecr_images_to_keep" {
  description = "Quantidade de imagens mantidas no ECR (as mais antigas são apagadas)"
  type        = number
  default     = 3
}

variable "project_name" {
  description = "Prefixo usado no nome dos recursos"
  type        = string
  default     = "api-first"
}
