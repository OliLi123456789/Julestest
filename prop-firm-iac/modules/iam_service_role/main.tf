# modules/iam_service_role/main.tf
locals {
  final_role_name = "${var.environment_name}-${var.service_name}-${var.role_name_prefix}-role"
}

resource "aws_iam_role" "service_task_role" {
  name        = local.final_role_name
  description = var.role_description
  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      for principal in var.assume_role_principals : {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = principal
        }
      }
    ]
  })
  tags = merge(var.common_tags, {
    Name    = local.final_role_name,
    Service = var.service_name
  })
}

resource "aws_iam_role_policy_attachment" "custom" {
  count      = length(var.attach_policy_arns)
  role       = aws_iam_role.service_task_role.name
  policy_arn = var.attach_policy_arns[count.index]
}
