# modules/vpc/outputs.tf

output "vpc_id" {
  description = "The ID of the VPC."
  value       = aws_vpc.main.id
}

output "vpc_cidr_block" {
  description = "The CIDR block of the VPC."
  value       = aws_vpc.main.cidr_block
}

output "public_subnet_ids" {
  description = "List of IDs of public subnets."
  value       = aws_subnet.public[*].id
}

output "private_app_subnet_ids" {
  description = "List of IDs of private application subnets."
  value       = aws_subnet.private_app[*].id
}

output "private_data_subnet_ids" {
  description = "List of IDs of private data subnets."
  value       = aws_subnet.private_data[*].id
}

output "nat_gateway_public_ips" {
  description = "Public IPs of NAT Gateways. Empty if NAT GW is disabled."
  value       = var.enable_nat_gateway ? aws_eip.nat[*].public_ip : []
}

output "igw_id" {
  description = "The ID of the Internet Gateway."
  value       = aws_internet_gateway.gw.id
}

output "default_public_route_table_id" {
  description = "The ID of the public route table."
  value       = aws_route_table.public.id
}

# Outputting all private app route table IDs (one per AZ if not single_nat_gateway)
output "private_app_route_table_ids" {
  description = "List of IDs of private application route tables."
  value       = aws_route_table.private_app[*].id
}

# Outputting all private data route table IDs (one per AZ if not single_nat_gateway)
output "private_data_route_table_ids" {
  description = "List of IDs of private data route tables."
  value       = aws_route_table.private_data[*].id
}
