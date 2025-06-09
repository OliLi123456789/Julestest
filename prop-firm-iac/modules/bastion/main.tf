# modules/bastion/main.tf

resource "aws_instance" "bastion_host" {
  ami           = var.ami_id
  instance_type = var.instance_type
  key_name      = var.key_name # Can be null if SSM Session Manager is primary access
  subnet_id     = var.public_subnet_id // Must be a public subnet

  vpc_security_group_ids = [var.bastion_sg_id]

  # Public IP is automatically assigned if the public subnet has map_public_ip_on_launch = true.
  # Setting this true ensures it, overriding subnet default if it were false.
  associate_public_ip_address = true

  iam_instance_profile = var.iam_instance_profile_name // Attach IAM role for SSM, CW Logs etc.

  monitoring = var.enable_detailed_monitoring

  user_data_replace_on_change = true # If user_data changes, replace the instance.
  user_data                   = var.user_data_script # For initial setup, MFA, logging agents.

  tags = merge(var.common_tags, {
    Name        = "${var.environment_name}-bastion-host-01" # Adding -01 for potential future multiple bastions
    Role        = "BastionHost"
    Environment = var.environment_name
  })
}

# (Optional) Elastic IP for a static public IP for the bastion
# If a static IP is required for whitelisting external access to the bastion.
# resource "aws_eip" "bastion_eip" {
#   # Conditionally create if a flag variable is set, e.g. var.assign_static_ip_to_bastion
#   # count = var.assign_static_ip_to_bastion ? 1 : 0
#   instance = aws_instance.bastion_host.id
#   # domain   = "vpc" # Use "vpc" to allocate from the VPC scope. For EC2-VPC.
#   # The 'domain' argument is only valid for vpc EIPs.
#   # For EC2-Classic, it would be different, but we are in VPC.
#   # Modern providers infer this; simply associating with an instance in VPC is enough.
#   # The 'vpc = true' syntax is for older versions or specific contexts.
#   # If `associate_public_ip_address` is true on the instance, an EIP is not strictly needed unless you want to retain the IP.
#   # If using EIP, set associate_public_ip_address = false on the instance.
#
#   tags = merge(var.common_tags, {
#     Name = "${var.environment_name}-bastion-eip-01"
#   })
# }
