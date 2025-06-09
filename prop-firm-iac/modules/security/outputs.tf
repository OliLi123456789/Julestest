# modules/security/outputs.tf

output "lb_sg_id" {
  description = "The ID of the Load Balancer Security Group."
  value       = aws_security_group.lb.id
}

output "bastion_sg_id" {
  description = "The ID of the Bastion Host Security Group."
  value       = aws_security_group.bastion.id
}

output "web_app_sg_id" {
  description = "The ID of the Web Application Tier Security Group."
  value       = aws_security_group.web_app.id
}

output "app_engine_sg_id" {
  description = "The ID of the Application/Trading Engine Tier Security Group."
  value       = aws_security_group.app_engine.id
}

output "db_sg_id" {
  description = "The ID of the Database Tier Security Group."
  value       = aws_security_group.db.id
}

output "public_nacl_id" {
  description = "The ID of the Network ACL for public subnets."
  value       = aws_network_acl.public_nacl.id
}

output "private_app_nacl_id" {
  description = "The ID of the Network ACL for private app subnets."
  value       = aws_network_acl.private_app_nacl.id
}

output "private_data_nacl_id" {
  description = "The ID of the Network ACL for private data subnets."
  value       = aws_network_acl.private_data_nacl.id
}
