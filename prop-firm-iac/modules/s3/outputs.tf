# modules/s3/outputs.tf

output "logging_bucket_id" {
  description = "The ID (name) of the centralized server access logging S3 bucket."
  value       = var.enable_logging_bucket ? aws_s3_bucket.logging[0].id : null
}

output "logging_bucket_arn" {
  description = "The ARN of the centralized server access logging S3 bucket."
  value       = var.enable_logging_bucket ? aws_s3_bucket.logging[0].arn : null
}

output "cloudtrail_bucket_id" {
  description = "The ID (name) of the S3 bucket for CloudTrail logs."
  value       = var.enable_cloudtrail_bucket ? aws_s3_bucket.cloudtrail[0].id : null
}

output "cloudtrail_bucket_arn" {
  description = "The ARN of the S3 bucket for CloudTrail logs."
  value       = var.enable_cloudtrail_bucket ? aws_s3_bucket.cloudtrail[0].arn : null
}

output "artifacts_bucket_id" {
  description = "The ID (name) of the S3 bucket for CI/CD artifacts."
  value       = var.enable_artifacts_bucket ? aws_s3_bucket.artifacts[0].id : null
}

output "artifacts_bucket_arn" {
  description = "The ARN of the S3 bucket for CI/CD artifacts."
  value       = var.enable_artifacts_bucket ? aws_s3_bucket.artifacts[0].arn : null
}

output "rag_data_bucket_id" {
  description = "The ID (name) of the S3 bucket for RAG data."
  value       = var.enable_rag_data_bucket ? aws_s3_bucket.rag_data[0].id : null
}

output "rag_data_bucket_arn" {
  description = "The ARN of the S3 bucket for RAG data."
  value       = var.enable_rag_data_bucket ? aws_s3_bucket.rag_data[0].arn : null
}
