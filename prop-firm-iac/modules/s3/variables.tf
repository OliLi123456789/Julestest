# modules/s3/variables.tf

variable "bucket_name_prefix" {
  description = "A prefix for S3 bucket names to help ensure uniqueness and organization."
  type        = string
}

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production) for tagging and naming."
  type        = string
}

variable "aws_account_id" {
  description = "AWS Account ID, used in bucket naming and policy for CloudTrail if needed."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "enable_logging_bucket" {
  description = "Set to true to create a centralized S3 bucket for server access logs."
  type        = bool
  default     = false
}

variable "enable_cloudtrail_bucket" {
  description = "Set to true to create an S3 bucket specifically for CloudTrail logs."
  type        = bool
  default     = false
}

variable "enable_artifacts_bucket" {
  description = "Set to true to create an S3 bucket for storing CI/CD artifacts."
  type        = bool
  default     = false
}

variable "force_destroy_buckets" {
  description = "Set to true to allow Terraform to destroy buckets even if they contain objects. Use with caution, primarily for non-production."
  type        = bool
  default     = false
}

variable "versioning_enabled" {
  description = "Set to true to enable versioning on created buckets."
  type        = bool
  default     = true # Good default for most buckets
}
