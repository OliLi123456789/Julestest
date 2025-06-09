# global/iam/outputs.tf

output "cicd_github_actions_role_arn" {
  description = "The ARN of the IAM Role for GitHub Actions CI/CD."
  value       = aws_iam_role.cicd_github_actions.arn
}

output "administrators_group_name" {
  description = "The name of the Administrators IAM group."
  value       = aws_iam_group.administrators.name
}

output "developers_group_name" {
  description = "The name of the Developers IAM group."
  value       = aws_iam_group.developers.name
}

output "cicd_permissions_policy_arn" {
  description = "The ARN of the CICD Permissions Policy."
  value       = aws_iam_policy.cicd_permissions.arn
}

output "administrator_access_policy_arn" {
  description = "The ARN of the Administrator Access Policy."
  value       = aws_iam_policy.administrator_access.arn
}

output "developer_access_policy_arn" {
  description = "The ARN of the Developer Access Policy."
  value       = aws_iam_policy.developer_access.arn
}

output "github_oidc_provider_arn" {
  description = "The ARN of the GitHub OIDC Provider in IAM."
  # Ensure this output refers to the created/managed provider resource.
  value       = aws_iam_openid_connect_provider.github_oidc_provider.arn
}
