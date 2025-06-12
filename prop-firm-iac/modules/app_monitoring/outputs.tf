# modules/app_monitoring/outputs.tf
output "log_group_name" {
  description = "Name of the CloudWatch Log Group for the service."
  value       = aws_cloudwatch_log_group.service_logs.name
}
output "log_group_arn" {
  description = "ARN of the CloudWatch Log Group for the service."
  value       = aws_cloudwatch_log_group.service_logs.arn
}

output "alb_5xx_alarm_arn" {
  description = "ARN of the ALB 5XX errors alarm."
  value       = var.enable_alb_5xx_alarm && var.alb_load_balancer_arn_suffix != "" ? aws_cloudwatch_metric_alarm.alb_5xx_errors[0].arn : null
}

output "alb_unhealthy_hosts_alarm_arn" {
  description = "ARN of the ALB unhealthy hosts alarm."
  value       = var.enable_alb_5xx_alarm && var.alb_load_balancer_arn_suffix != "" && var.alb_target_group_arn_suffix != "" ? aws_cloudwatch_metric_alarm.alb_unhealthy_hosts[0].arn : null
}

output "ecs_service_cpu_alarm_arn" {
  description = "ARN of the ECS service CPU utilization alarm."
  value       = var.enable_ecs_service_cpu_alarm && var.ecs_cluster_name != "" && var.ecs_service_name_for_alarms != "" ? aws_cloudwatch_metric_alarm.ecs_service_cpu[0].arn : null
}

output "ecs_service_memory_alarm_arn" {
  description = "ARN of the ECS service memory utilization alarm."
  value       = var.enable_ecs_service_memory_alarm && var.ecs_cluster_name != "" && var.ecs_service_name_for_alarms != "" ? aws_cloudwatch_metric_alarm.ecs_service_memory[0].arn : null
}
