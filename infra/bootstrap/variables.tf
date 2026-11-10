variable "aws_profile" {
  description = "Perfil do AWS CLI usado para autenticar (SSO)"
  type        = string
  default     = "estudos"
}

variable "aws_region" {
  description = "Região da AWS"
  type        = string
  default     = "us-east-1"
}

variable "github_deploy_environment" {
  description = "Nome do GitHub Environment autorizado a usar a role de deploy"
  type        = string
  default     = "aws"
}

variable "github_owner_id" {
  description = "ID numérico do dono do repositório no GitHub (vai no sub do token OIDC)"
  type        = string
  default     = "250064056"
}

variable "github_repository_id" {
  description = "ID numérico do repositório no GitHub (vai no sub do token OIDC)"
  type        = string
  default     = "1432740330"
}

variable "github_repository" {
  description = "Repositório GitHub autorizado a acessar a AWS via OIDC (dono/nome)"
  type        = string
  default     = "ygorsttt-commits/API_First"
}

variable "project_name" {
  description = "Prefixo usado no nome dos recursos"
  type        = string
  default     = "api-first"
}
