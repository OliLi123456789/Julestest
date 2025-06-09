# modules/monitoring/main.tf

# --- AWS CloudTrail ---
resource "aws_cloudtrail" "main_trail" {
  name                          = "${var.environment_name}-platform-trail"
  s3_bucket_name                = var.cloudtrail_s3_bucket_name
  s3_key_prefix                 = var.cloudtrail_s3_key_prefix
  is_multi_region_trail         = true
  enable_logging                = true
  include_global_service_events = true # Recommended for most use cases

  # Optional: Send logs to CloudWatch Logs
  cloud_watch_logs_group_arn = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? aws_cloudwatch_log_group.cloudtrail_log_group[0].arn : null
  cloud_watch_logs_role_arn  = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? aws_iam_role.cloudtrail_to_cloudwatch_role[0].arn : null

  # Optional: KMS encryption
  kms_key_id = var.cloudtrail_kms_key_id

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-platform-trail"
  })
}

# --- CloudWatch Log Group for CloudTrail (Optional) ---
resource "aws_cloudwatch_log_group" "cloudtrail_log_group" {
  count = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? 1 : 0
  name  = var.cloudtrail_cloudwatch_log_group_name
  retention_in_days = var.cloudtrail_log_group_retention_days == 0 ? null : var.cloudtrail_log_group_retention_days # null means indefinite

  tags  = merge(var.common_tags, {
     Name = var.cloudtrail_cloudwatch_log_group_name
  })
}

# --- IAM Role for CloudTrail to write to CloudWatch Logs (Optional) ---
data "aws_iam_policy_document" "cloudtrail_to_cloudwatch_assume_role_policy_doc" {
  count = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? 1 : 0
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cloudtrail_to_cloudwatch_role" {
  count              = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? 1 : 0
  name               = "${var.environment_name}-CloudTrailToCloudWatchLogsRole"
  assume_role_policy = data.aws_iam_policy_document.cloudtrail_to_cloudwatch_assume_role_policy_doc[0].json
  tags               = var.common_tags
}

data "aws_iam_policy_document" "cloudtrail_to_cloudwatch_access_policy_doc" {
  count = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? 1 : 0
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    # Ensure the resource ARN correctly uses the created log group name if dynamic.
    # This requires the log group to be created or its ARN to be known.
    # Using `aws_cloudwatch_log_group.cloudtrail_log_group[0].arn` creates a dependency.
    resources = ["${aws_cloudwatch_log_group.cloudtrail_log_group[0].arn}:log-stream:*", "${aws_cloudwatch_log_group.cloudtrail_log_group[0].arn}:*"]
    effect    = "Allow"
  }
}

resource "aws_iam_role_policy" "cloudtrail_to_cloudwatch_access_policy" {
  count  = var.enable_cloudtrail_cloudwatch_logs && var.cloudtrail_cloudwatch_log_group_name != "" ? 1 : 0
  name   = "${var.environment_name}-CloudTrailToCloudWatchLogsAccess"
  role   = aws_iam_role.cloudtrail_to_cloudwatch_role[0].id
  policy = data.aws_iam_policy_document.cloudtrail_to_cloudwatch_access_policy_doc[0].json
}


# --- Example Basic CloudWatch Alarm (Conceptual / Non-functional without specific dimensions) ---
# This section remains primarily conceptual as per the prompt.
# A truly functional generic alarm module would require more sophisticated input for dimensions or be part of resource-specific modules.

resource "aws_cloudwatch_metric_alarm" "example_high_cpu" {
  count = var.enable_example_cpu_alarm && var.alarm_sns_topic_arn != "" ? 1 : 0

  alarm_name          = "${var.environment_name}-example-high-cpu-utilization"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2" # This makes it specific to EC2, not generic
  period              = var.alarm_period_seconds
  statistic           = "Average"
  threshold           = var.high_cpu_alarm_threshold_percent
  alarm_description   = "Example metric alarm for high CPU utilization. This alarm WILL NOT function correctly without specific dimensions (e.g., InstanceId) and is for illustrative purposes only."

  # CRITICAL: Dimensions are needed for this alarm to target a specific resource.
  # Without dimensions, this alarm will likely stay in INSUFFICIENT_DATA state or not be created correctly.
  # Example:
  # dimensions = {
  #   InstanceId = "i-xxxxxxxxxxxxxxxxx" # This needs to be passed in or determined dynamically
  # }

  insufficient_data_actions = []
  alarm_actions             = [var.alarm_sns_topic_arn]
  ok_actions                = [var.alarm_sns_topic_arn] # Optional: notify on OK state

  tags = merge(var.common_tags, {
    Name        = "${var.environment_name}-example-high-cpu-alarm"
    Scope       = "ExampleOnly"
    Warning     = "NonFunctionalWithoutDimensions"
  })
}

# Note: To make the example alarm truly reusable, the module would need to accept
# a map of dimensions, the metric namespace, metric_name, etc., as variables.
# For this exercise, CloudTrail is the primary functional part of this monitoring module.
