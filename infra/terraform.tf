terraform {
  required_version = ">= 1.14"

  # State remoto no bucket criado por infra/bootstrap (regra 13).
  # use_lockfile = lock nativo do S3, sem precisar de tabela DynamoDB.
  backend "s3" {
    bucket       = "api-first-tfstate-265469156400"
    key          = "app/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
