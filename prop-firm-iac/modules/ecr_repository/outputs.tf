# modules/ecr_repository/outputs.tf
output "repository_url" {
  description = "The URL of the ECR repository."
  value       = aws_ecr_repository.main.repository_url
}

output "repository_arn" {
  description = "The ARN of the ECR repository."
  value       = aws_ecr_repository.main.arn
}

output "repository_name" {
  description = "The name of the ECR repository."
  value       = aws_ecr_repository.main.name
}
