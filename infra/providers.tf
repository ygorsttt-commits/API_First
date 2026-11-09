provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # Tags aplicadas automaticamente em TUDO que o Terraform criar
  default_tags {
    tags = {
      Project   = "API_First"
      ManagedBy = "Terraform"
    }
  }
}
