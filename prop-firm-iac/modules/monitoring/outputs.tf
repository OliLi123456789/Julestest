# modules/monitoring/outputs.tf

output "cloudtrail_arn" {
  description = "The ARN of the CloudTrail trail."
  value       = aws_cloudtrail.main_trail.arn
}

output "cloudtrail_id" {
  description = "The ID of the CloudTrail trail."
  value       = aws_cloudtrail.main_trail.id
}

output "cloudtrail_s3_bucket_name" {
  description = "The S3 bucket name used for CloudTrail log storage."
  value       = aws_cloudtrail.main_trail.s3_bucket_name
}

output "cloudtrail_s3_key_prefix" {
  description = "The S3 key prefix used for CloudTrail log storage."
  value       = aws_cloudtrail.main_trail.s3_key_prefix
}

output "cloudtrail_cloudwatch_log_group_arn" {
  description = "The ARN of the CloudWatch Log Group for CloudTrail (if configured)."
  value       = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? aws_cloudwatch_log_group.cloudtrail_log_group[0].arn : null
}

output "example_high_cpu_alarm_id" {
  description = "The ID of the example high CPU alarm (if created). This is illustrative."
  value       = var.enable_example_cpu_alarm && var.alarm_sns_topic_arn != "" ? aws_cloudwatch_metric_alarm.example_high_cpu[0].id : null
}

output "example_high_cpu_alarm_arn" {
  description = "The ARN of the example high CPU alarm (if created). This is illustrative."
  value       = var.enable_example_cpu_alarm && var.alarm_sns_topic_arn != "" ? aws_cloudwatch_metric_alarm.example_high_cpu[0].arn : null
}
