# modules/app_monitoring/main.tf
locals {
  log_group_name_final = var.log_group_name == "" ? "/ecs/${var.environment_name}/${var.service_name}" : var.log_group_name
}

resource "aws_cloudwatch_log_group" "service_logs" {
  name              = local.log_group_name_final
  retention_in_days = var.log_retention_days == 0 ? null : var.log_retention_days # 0 means indefinite for Terraform null value
  tags              = merge(var.common_tags, { Name = local.log_group_name_final, Service = var.service_name })
}

# ALB 5XX Error Alarm
resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  count = var.enable_alb_5xx_alarm && var.alb_load_balancer_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-${var.service_name}-alb-5xx-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  threshold           = var.error_rate_alarm_threshold_count # Number of 5XX errors
  alarm_description   = "High number of 5XX errors from ALB for ${var.service_name} (LoadBalancer: ${var.alb_load_balancer_arn_suffix})"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  statistic           = "Sum"
  period              = 300   # 5 minutes

  dimensions = {
    LoadBalancer = var.alb_load_balancer_arn_suffix
  }
  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn] # Send notification on OK state transition as well
  tags          = merge(var.common_tags, { Name = "${var.environment_name}-${var.service_name}-alb-5xx-high", Service = var.service_name })
}

# ALB Unhealthy Hosts Alarm
resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  # Re-using enable_alb_5xx_alarm for simplicity, could be a separate var if needed.
  count = var.enable_alb_5xx_alarm && var.alb_load_balancer_arn_suffix != "" && var.alb_target_group_arn_suffix != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-${var.service_name}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  threshold           = var.unhealthy_host_alarm_threshold_count
  alarm_description   = "Unhealthy hosts in ALB target group for ${var.service_name} (TargetGroup: ${var.alb_target_group_arn_suffix})"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "UnHealthyHostCount"
  statistic           = "Maximum" # Use Maximum to catch any instance of unhealthy hosts in the period
  period              = 300 # 5 minutes

  dimensions = {
    LoadBalancer = var.alb_load_balancer_arn_suffix
    TargetGroup  = var.alb_target_group_arn_suffix
  }
  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
  tags          = merge(var.common_tags, { Name = "${var.environment_name}-${var.service_name}-alb-unhealthy-hosts", Service = var.service_name })
}

# ECS Service CPU Utilization Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_service_cpu" {
  count = var.enable_ecs_service_cpu_alarm && var.ecs_cluster_name != "" && var.ecs_service_name_for_alarms != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-${var.ecs_service_name_for_alarms}-cpu-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  threshold           = var.cpu_alarm_threshold_percent
  alarm_description   = "High CPU utilization for ECS service ${var.ecs_service_name_for_alarms} in cluster ${var.ecs_cluster_name}"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 300 # 5 minutes

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name_for_alarms
  }
  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
  tags          = merge(var.common_tags, { Name = "${var.environment_name}-${var.ecs_service_name_for_alarms}-cpu-high", Service = var.service_name })
}

# ECS Service Memory Utilization Alarm
resource "aws_cloudwatch_metric_alarm" "ecs_service_memory" {
  count = var.enable_ecs_service_memory_alarm && var.ecs_cluster_name != "" && var.ecs_service_name_for_alarms != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-${var.ecs_service_name_for_alarms}-memory-high"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  threshold           = var.memory_alarm_threshold_percent
  alarm_description   = "High Memory utilization for ECS service ${var.ecs_service_name_for_alarms} in cluster ${var.ecs_cluster_name}"
  namespace           = "AWS/ECS"
  metric_name         = "MemoryUtilization"
  statistic           = "Average"
  period              = 300 # 5 minutes

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name_for_alarms
  }
  alarm_actions = [var.alarm_sns_topic_arn]
  ok_actions    = [var.alarm_sns_topic_arn]
  tags          = merge(var.common_tags, { Name = "${var.environment_name}-${var.ecs_service_name_for_alarms}-memory-high", Service = var.service_name })
}
