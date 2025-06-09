# environments/staging/outputs.tf

output "aws_account_id" {
  description = "The AWS Account ID being used."
  value       = data.aws_caller_identity.current.account_id
}

output "aws_region" {
  description = "The AWS region resources are deployed in."
  value       = var.aws_region
}

output "vpc_id" {
  description = "The ID of the Staging VPC."
  value       = module.vpc.vpc_id
}

output "vpc_cidr_block" {
  description = "The CIDR block of the Staging VPC."
  value       = module.vpc.vpc_cidr_block
}

output "public_subnet_ids" {
  description = "List of IDs of public subnets in Staging."
  value       = module.vpc.public_subnet_ids
}

output "private_app_subnet_ids" {
  description = "List of IDs of private application subnets in Staging."
  value       = module.vpc.private_app_subnet_ids
}

output "private_data_subnet_ids" {
  description = "List of IDs of private data subnets in Staging."
  value       = module.vpc.private_data_subnet_ids
}

output "nat_gateway_public_ips" {
  description = "Public IPs of NAT Gateways in Staging (if enabled)."
  value       = module.vpc.nat_gateway_public_ips
}

output "lb_sg_id" {
  description = "The ID of the Load Balancer Security Group in Staging."
  value       = module.security.lb_sg_id
}

output "web_app_sg_id" {
  description = "The ID of the Web Application Tier Security Group in Staging."
  value       = module.security.web_app_sg_id
}

output "app_engine_sg_id" {
  description = "The ID of the App Engine Tier Security Group in Staging."
  value       = module.security.app_engine_sg_id
}

output "db_sg_id" {
  description = "The ID of the Database Tier Security Group in Staging."
  value       = module.security.db_sg_id
}

output "cicd_github_actions_role_arn" {
  description = "ARN of the CI/CD role for GitHub Actions."
  value       = module.global_iam.cicd_github_actions_role_arn
}

output "cloudtrail_s3_bucket_name" {
  description = "S3 bucket name for CloudTrail logs."
  value       = module.monitoring.cloudtrail_s3_bucket_name # This comes from the monitoring module which gets it from s3 module
}

output "artifacts_s3_bucket_name" {
  description = "S3 bucket name for CI/CD artifacts."
  value       = module.s3_buckets.artifacts_bucket_id # module.s3_buckets.artifacts_bucket_id is the bucket name
}

output "access_logs_s3_bucket_name" {
  description = "S3 bucket name for access logs."
  value       = module.s3_buckets.logging_bucket_id # module.s3_buckets.logging_bucket_id is the bucket name
}

output "cloudtrail_arn" {
  description = "ARN of the CloudTrail trail for Staging."
  value       = module.monitoring.cloudtrail_arn
}
