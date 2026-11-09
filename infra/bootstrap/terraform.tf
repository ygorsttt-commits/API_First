# Bootstrap: criado uma única vez, do PC, com state LOCAL.
# É o "ovo" do problema do ovo e da galinha: cria o bucket onde o
# restante da infraestrutura vai guardar o state.
terraform {
  required_version = ">= 1.14"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
