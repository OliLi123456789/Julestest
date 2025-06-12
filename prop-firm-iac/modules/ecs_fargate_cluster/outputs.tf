# modules/ecs_fargate_cluster/outputs.tf
output "ecs_cluster_arn" {
  description = "ARN of the ECS Cluster."
  value       = aws_ecs_cluster.main.arn
}

output "ecs_cluster_name" {
  description = "Name of the ECS Cluster."
  value       = aws_ecs_cluster.main.name
}

output "ecs_task_execution_role_arn" {
  description = "ARN of the default ECS Task Execution Role."
  value       = aws_iam_role.ecs_task_execution_role.arn
}

output "ecs_task_execution_role_name" {
  description = "Name of the default ECS Task Execution Role."
  value       = aws_iam_role.ecs_task_execution_role.name
}
