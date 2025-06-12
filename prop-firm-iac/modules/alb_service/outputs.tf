# modules/alb_service/outputs.tf
output "alb_arn" { value = aws_lb.main.arn }
output "alb_dns_name" { value = aws_lb.main.dns_name }
output "alb_zone_id" { value = aws_lb.main.zone_id } # For Route53 alias records from other modules/stacks
output "http_listener_arn" { value = aws_lb_listener.http.arn }
output "https_listener_arn" { value = var.enable_https ? aws_lb_listener.https[0].arn : null }
output "default_target_group_arn" { value = aws_lb_target_group.default.arn }
output "alb_security_group_id" { value = aws_security_group.alb_sg.id }

output "alb_arn_suffix" {
  description = "The ARN suffix of the ALB (e.g., app/name/id)."
  value       = aws_lb.main.arn_suffix
}
output "default_target_group_arn_suffix" {
  description = "The ARN suffix of the default target group (e.g., targetgroup/name/id)."
  value       = aws_lb_target_group.default.arn_suffix
}
