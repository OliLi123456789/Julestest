# modules/app_monitoring/variables.tf
variable "environment_name" {
  description = "Name of the environment."
  type        = string
}
variable "service_name" {
  description = "Name of the service for which resources are being created (e.g., 'llm-chatbot', 'webapp-backend'). Used for naming."
  type        = string
}
variable "common_tags" {
  description = "Common tags to apply."
  type        = map(string)
  default     = {}
}

# Log Group Variables
variable "log_group_name" {
  description = "Name for the CloudWatch Log Group. If empty, it's derived from env and service name."
  type        = string
  default     = ""
}
variable "log_retention_days" {
  description = "Number of days to retain logs in the CloudWatch Log Group. 0 means indefinite."
  type        = number
  default     = 90
}

# Alarm Variables
variable "alarm_sns_topic_arn" {
  description = "ARN of an SNS topic to send alarm notifications to."
  type        = string
}
variable "enable_alb_5xx_alarm" {
  description = "Enable alarm for high 5XX error rate on ALB."
  type        = bool
  default     = true
}
variable "alb_load_balancer_arn_suffix" {
  description = "ALB ARN Suffix (e.g., app/staging-api-alb/12345abcdef). Output from aws_lb resource."
  type        = string
  default     = "" # Required if alb_5xx_alarm or unhealthy_host_alarm is enabled
}
variable "alb_target_group_arn_suffix" {
  description = "ALB Target Group ARN Suffix (e.g., targetgroup/staging-api-default-tg/12345abcdef). Output from aws_lb_target_group resource."
  type        = string
  default     = "" # Required if unhealthy_host_alarm is enabled
}

variable "enable_ecs_service_cpu_alarm" {
  description = "Enable alarm for high CPU utilization on ECS Service."
  type        = bool
  default     = true
}
variable "enable_ecs_service_memory_alarm" {
  description = "Enable alarm for high Memory utilization on ECS Service."
  type        = bool
  default     = true
}
variable "ecs_cluster_name" {
  description = "Name of the ECS Cluster the service runs in."
  type        = string
  default     = "" # Required if ECS alarms are enabled
}
variable "ecs_service_name_for_alarms" {
  description = "Name of the ECS Service to monitor (as deployed in ECS)."
  type        = string
  default     = "" # Required if ECS alarms are enabled
}
variable "cpu_alarm_threshold_percent" { type = number; default = 80 }
variable "memory_alarm_threshold_percent" { type = number; default = 80 }
variable "error_rate_alarm_threshold_count" { type = number; default = 5 } # Using count for 5XX, not percentage directly for Sum statistic. Threshold is count of 5XX errors.
variable "unhealthy_host_alarm_threshold_count" { type = number; default = 1 }
