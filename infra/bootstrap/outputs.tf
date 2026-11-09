output "github_deploy_role_arn" {
  description = "ARN da role que o GitHub Actions assume para deploy"
  value       = aws_iam_role.github_deploy.arn
}

output "github_plan_role_arn" {
  description = "ARN da role que o GitHub Actions assume para plan em PRs"
  value       = aws_iam_role.github_plan.arn
}

output "tfstate_bucket_name" {
  description = "Nome do bucket S3 que guarda o state do Terraform"
  value       = aws_s3_bucket.tfstate.bucket
}
