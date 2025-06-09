# modules/bastion/outputs.tf

output "bastion_instance_id" {
  description = "The ID of the bastion host EC2 instance."
  value       = aws_instance.bastion_host.id
}

output "bastion_public_ip" {
  description = "The public IP address of the bastion host."
  # value       = var.assign_static_ip_to_bastion ? aws_eip.bastion_eip[0].public_ip : aws_instance.bastion_host.public_ip
  # Assuming dynamic IP if EIP is not explicitly created and assigned.
  # If an EIP resource named 'bastion_eip' were uncommented and used, the output would be:
  # value       = aws_eip.bastion_eip.public_ip
  # For now, it will output the dynamic public IP assigned to the instance.
  value       = aws_instance.bastion_host.public_ip
}

output "bastion_private_ip" {
  description = "The private IP address of the bastion host."
  value       = aws_instance.bastion_host.private_ip
}

output "bastion_public_dns" {
  description = "The public DNS name of the bastion host."
  # value       = var.assign_static_ip_to_bastion ? aws_eip.bastion_eip[0].public_dns : aws_instance.bastion_host.public_dns
  # Similar logic for EIP as above.
  value       = aws_instance.bastion_host.public_dns
}

output "bastion_instance_arn" {
  description = "The ARN of the bastion host EC2 instance."
  value       = aws_instance.bastion_host.arn
}
