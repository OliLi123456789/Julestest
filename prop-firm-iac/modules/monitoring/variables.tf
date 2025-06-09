# modules/monitoring/variables.tf

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production) for tagging and naming resources."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "cloudtrail_s3_bucket_name" {
  description = "Name of the S3 bucket where CloudTrail logs will be stored. This bucket must be created (e.g., by the s3 module) and its policy must allow CloudTrail to write."
  type        = string
}

variable "cloudtrail_s3_key_prefix" {
  description = "S3 key prefix for CloudTrail logs within the bucket (e.g., 'cloudtrail')."
  type        = string
  default     = null # If null, CloudTrail defaults to no prefix or its standard prefix.
}

variable "enable_cloudtrail_cloudwatch_logs" {
  description = "Set to true to enable sending CloudTrail logs to CloudWatch Logs."
  type        = bool
  default     = true
}

variable "cloudtrail_cloudwatch_log_group_name" {
  description = "Name of the CloudWatch Log Group for CloudTrail logs. Required if enable_cloudtrail_cloudwatch_logs is true."
  type        = string
  default     = "" # Should be set if enable_cloudtrail_cloudwatch_logs is true. Example: /aws/cloudtrail/platform-trail
}

variable "cloudtrail_log_group_retention_days" {
  description = "Number of days to retain CloudTrail logs in CloudWatch Logs. 0 means indefinite."
  type        = number
  default     = 365
}

variable "cloudtrail_kms_key_id" {
  description = "KMS Key ID/ARN for encrypting CloudTrail logs (optional). If not provided, S3 default encryption or CloudTrail default is used."
  type        = string
  default     = null
}

# Variables for example CloudWatch Alarms - these are illustrative.
# Real alarm module would be more complex or alarms defined per-resource module.
variable "enable_example_cpu_alarm" {
  description = "Set to true to create an example high CPU alarm (needs specific dimensions to be useful)."
  type        = bool
  default     = false
}

variable "high_cpu_alarm_threshold_percent" {
  description = "CPU utilization threshold for triggering the example alarm."
  type        = number
  default     = 80
}

variable "alarm_sns_topic_arn" {
  description = "ARN of an SNS topic to send alarm notifications to. Required if example alarms are enabled."
  type        = string
  default     = "" # Must be provided if example alarms are to send notifications
}

variable "alarm_evaluation_periods" {
  description = "The number of periods over which data is compared to the specified threshold for alarms."
  type        = number
  default     = 2
}

variable "alarm_period_seconds" {
  description = "The period, in seconds, over which the specified statistic is applied for alarms."
  type        = number
  default     = 300 # 5 minutes
}
