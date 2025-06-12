# global/iam/variables.tf

variable "aws_account_id" {
  description = "The AWS Account ID where these global IAM resources will be created."
  type        = string
}

variable "ci_cd_github_org_repo" {
  description = "The GitHub Organization and Repository slug (e.g., 'MyOrg/MyRepo' or 'MyOrg/*') for OIDC trust policy condition. Allows specifying a single repo or all repos in an org."
  type        = string
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

variable "cicd_ecr_repository_arns" {
  description = "List of ECR repository ARNs that the CI/CD role can interact with (push/pull images)."
  type        = list(string)
  default     = []
}

variable "cicd_ecs_service_arns" {
  description = "List of ECS Service ARNs that the CI/CD role can update (e.g., to deploy new task definitions)."
  type        = list(string)
  default     = []
}

variable "cicd_iam_passrole_arns" {
  description = "List of IAM Role ARNs that CI/CD can pass to ECS tasks. Should include ECS Task Roles."
  type        = list(string)
  default     = []
}

variable "cicd_frontend_s3_bucket_arns" {
  description = "List of S3 bucket ARNs (and object paths like 'arn:aws:s3:::bucketname/*') for frontend static asset deployment."
  type        = list(string)
  default     = [] # e.g., ["arn:aws:s3:::my-frontend-bucket", "arn:aws:s3:::my-frontend-bucket/*"]
}

variable "cicd_cloudfront_distribution_arns" {
  description = "List of CloudFront Distribution ARNs for cache invalidation during frontend deployments."
  type        = list(string)
  default     = [] # e.g., ["arn:aws:cloudfront::ACCOUNT_ID:distribution/DISTRIBUTION_ID"]
}
