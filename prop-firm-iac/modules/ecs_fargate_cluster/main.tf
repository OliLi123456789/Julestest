# modules/ecs_fargate_cluster/main.tf
locals {
  cluster_name_final = var.cluster_name == "" ? "${var.environment_name}-ecs-cluster" : var.cluster_name
}

resource "aws_ecs_cluster" "main" {
  name = local.cluster_name_final

  setting {
    name  = "containerInsights"
    value = "enabled" # Enable Container Insights for monitoring
  }

  tags = merge(var.common_tags, {
    Name = local.cluster_name_final
  })
}

# Default IAM Role for ECS Task Execution
# Allows Fargate tasks to pull images from ECR and send logs to CloudWatch.
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${local.cluster_name_final}-task-exec-role"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Action    = "sts:AssumeRole",
        Effect    = "Allow",
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.common_tags, {
    Name = "${local.cluster_name_final}-task-exec-role"
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
