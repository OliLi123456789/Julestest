# global/iam/variables.tf

variable "aws_account_id" {
  description = "The AWS Account ID where these global IAM resources will be created."
  type        = string
}

variable "ci_cd_github_org_repo" {
  description = "The GitHub Organization and Repository slug (e.g., 'MyOrg/prop-firm-iac' or 'MyOrg/*') for OIDC trust policy."
  type        = string
  # Example: "YourGitHubOrg/YourRepoName" or "YourGitHubOrg/*" for all repos in org
}

variable "admin_group_name" {
  description = "Name for the IAM group for administrators."
  type        = string
  default     = "PlatformAdministrators"
}

variable "developer_group_name" {
  description = "Name for the IAM group for developers."
  type        = string
  default     = "PlatformDevelopers"
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "terraform_state_bucket_name" {
  description = "The name of the S3 bucket used for Terraform state."
  type        = string
  # Example: "prop-firm-terraform-state-your-account-id-your-region"
}

variable "terraform_state_lock_table_name" {
  description = "The name of the DynamoDB table used for Terraform state locking."
  type        = string
  # Example: "prop-firm-terraform-state-lock"
}

variable "aws_region" {
  description = "The AWS region where global resources like the OIDC provider might be considered, and for constructing ARNs."
  type        = string
}
