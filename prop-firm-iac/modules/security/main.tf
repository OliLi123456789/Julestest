# modules/security/main.tf

# --- Load Balancer Security Group ---
resource "aws_security_group" "lb" {
  name        = "${var.environment_name}-lb-sg"
  description = "Security group for Load Balancers (ALB/NLB)"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTP from anywhere"
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow HTTPS from anywhere"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1" # Allow all outbound traffic
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-lb-sg"
  })
}

# --- Bastion Host Security Group ---
resource "aws_security_group" "bastion" {
  name        = "${var.environment_name}-bastion-sg"
  description = "Security group for Bastion Host"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.bastion_ingress_ssh_cidrs
    description = "Allow SSH from trusted IPs"
  }

  egress { # Bastion typically needs to SSH into other instances
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block] # Or more specific private subnet CIDRs / SG IDs
    description = "Allow SSH to VPC internal resources"
  }
   egress { # Allow outbound for OS updates etc.
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-bastion-sg"
  })
}

# --- Web Application Tier Security Group ---
resource "aws_security_group" "web_app" {
  name        = "${var.environment_name}-webapp-sg"
  description = "Security group for Web Application Tier (e.g., FastAPI backend)"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = var.web_app_port
    to_port         = var.web_app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.lb.id] # Allow traffic from Load Balancer SG
    description     = "Allow traffic from LB on app port"
  }

  ingress { # For SSH from Bastion
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
    description     = "Allow SSH from Bastion"
  }


  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1" # Allow all outbound for now, can be restricted
    cidr_blocks = ["0.0.0.0/0"] # Assumes NAT GW for external, or VPC Endpoints for AWS services
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-webapp-sg"
  })
}

# --- Application/Trading Engine Tier Security Group ---
resource "aws_security_group" "app_engine" {
  name        = "${var.environment_name}-app-engine-sg"
  description = "Security group for Application/Trading Engine Tier"
  vpc_id      = var.vpc_id

  ingress { # From Web App Tier
    from_port       = var.app_tier_internal_port
    to_port         = var.app_tier_internal_port
    protocol        = "tcp"
    security_groups = [aws_security_group.web_app.id]
    description     = "Allow traffic from Web App Tier"
  }

  ingress { # For intra-tier communication if needed
    from_port       = var.app_tier_internal_port
    to_port         = var.app_tier_internal_port
    protocol        = "tcp"
    self            = true
    description     = "Allow internal communication within App Engine Tier"
  }

  ingress { # For SSH from Bastion
    from_port       = 22
    to_port         = 22
    protocol        = "tcp"
    security_groups = [aws_security_group.bastion.id]
    description     = "Allow SSH from Bastion"
  }

  # Egress to Database Tier SG will be defined by referencing aws_security_group.db.id
  # Egress to external services (Broker API, Polygon, LLM via NAT Gateway)
  egress {
    from_port   = 443 # HTTPS
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Assumes NAT Gateway
  }
  egress { # DNS
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"] # Assumes NAT Gateway or VPC DNS resolver
  }
   egress { # DNS over TCP
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-app-engine-sg"
  })
}

# --- Database Tier Security Group ---
resource "aws_security_group" "db" {
  name        = "${var.environment_name}-db-sg"
  description = "Security group for Database Tier (e.g., PostgreSQL)"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = var.db_port_postgresql
    to_port         = var.db_port_postgresql
    protocol        = "tcp"
    security_groups = [aws_security_group.app_engine.id] # Allow from App Engine Tier
    description     = "Allow PostgreSQL traffic from App Engine Tier"
  }
  # Optionally allow from Bastion SG for admin access via specific rules
  # ingress {
  #   from_port       = var.db_port_postgresql
  #   to_port         = var.db_port_postgresql
  #   protocol        = "tcp"
  #   security_groups = [aws_security_group.bastion.id]
  #   description     = "Allow PostgreSQL from Bastion (Admin)"
  # }

  # Databases generally should have very restricted outbound or no outbound internet access.
  # Egress rules might be needed for specific cases like DB updates if not using private links,
  # or communication with other internal services if required.
  # Default: deny all outbound by not specifying egress rules, or a very restrictive one.
  egress {
    from_port   = 0 # Highly restricted, only if necessary (e.g. to KMS for encryption if using CMK not via endpoint)
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["127.0.0.1/32"] # Effectively blocks external egress
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-db-sg"
  })
}

# --- Network ACLs ---

# Public Subnet NACL
resource "aws_network_acl" "public_nacl" {
  vpc_id     = var.vpc_id
  subnet_ids = var.public_subnet_ids_for_nacl # Associate with public subnets passed as variable

  # Inbound Rules
  rule { # Allow HTTP
    protocol   = "tcp"
    rule_number = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 80
    to_port    = 80
  }
  rule { # Allow HTTPS
    protocol   = "tcp"
    rule_number = 110
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 443
    to_port    = 443
  }
  rule { # Allow SSH (intended for bastion, but NACLs are broad)
    protocol   = "tcp"
    rule_number = 120
    action     = "allow"
    cidr_block = "0.0.0.0/0" # For bastion, this should be restricted if possible at NACL level, but SG is primary control
    from_port  = 22
    to_port    = 22
  }
  rule { # Allow inbound return traffic (ephemeral ports for TCP)
    protocol   = "tcp"
    rule_number = 130
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 1024
    to_port    = 65535
  }
  # Default Deny is implicit

  # Outbound Rules
  rule { # Allow all outbound traffic (for IGW and NAT GW responses)
    protocol   = "-1"
    rule_number = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 0
    to_port    = 0
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-public-nacl"
  })
}

# Private Application Subnet NACL
resource "aws_network_acl" "private_app_nacl" {
  vpc_id     = var.vpc_id
  subnet_ids = var.private_app_subnet_ids_for_nacl

  # Inbound Rules
  rule { # Allow all traffic from within the VPC
    protocol   = "-1" # All protocols
    rule_number = 100
    action     = "allow"
    cidr_block = var.vpc_cidr_block # Allows all internal VPC communication
    from_port  = 0
    to_port    = 0
  }
  # Default Deny for traffic from outside VPC (e.g. internet)

  # Outbound Rules
  rule { # Allow HTTPS to internet (for external APIs via NAT Gateway)
    protocol   = "tcp"
    rule_number = 100
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 443
    to_port    = 443
  }
  rule { # Allow HTTP to internet (less common, but if needed)
    protocol   = "tcp"
    rule_number = 110
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 80
    to_port    = 80
  }
  rule { # Allow DNS (UDP) to VPC resolver or internet
    protocol   = "udp"
    rule_number = 120
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 53
    to_port    = 53
  }
  rule { # Allow DNS (TCP)
    protocol   = "tcp"
    rule_number = 121
    action     = "allow"
    cidr_block = "0.0.0.0/0"
    from_port  = 53
    to_port    = 53
  }
  rule { # Allow outbound return traffic to within VPC (ephemeral ports for TCP)
    protocol   = "tcp"
    rule_number = 130
    action     = "allow"
    cidr_block = var.vpc_cidr_block
    from_port  = 1024
    to_port    = 65535
  }
  # Default Deny for other outbound traffic

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-app-nacl"
  })
}

# Private Data Subnet NACL (Strictest)
resource "aws_network_acl" "private_data_nacl" {
  vpc_id     = var.vpc_id
  subnet_ids = var.private_data_subnet_ids_for_nacl

  # Inbound Rules
  rule { # Allow traffic from App Subnets on DB port
    protocol   = "tcp"
    rule_number = 100
    action     = "allow"
    cidr_block = var.vpc_cidr_block # Could be more specific using App Subnet CIDRs if passed as var
    from_port  = var.db_port_postgresql
    to_port    = var.db_port_postgresql
  }
  rule { # Allow inbound return traffic from App Subnets (ephemeral ports for TCP)
    protocol   = "tcp"
    rule_number = 110
    action     = "allow"
    cidr_block = var.vpc_cidr_block # Could be more specific using App Subnet CIDRs
    from_port  = 1024
    to_port    = 65535
  }
  # Default Deny all other inbound

  # Outbound Rules
  rule { # Allow responses back to App Subnets from DB port
    protocol   = "tcp"
    rule_number = 100
    action     = "allow"
    cidr_block = var.vpc_cidr_block # Could be more specific using App Subnet CIDRs
    from_port  = 1024 # DB source port will be ephemeral when responding
    to_port    = 65535 # App destination port will be ephemeral
  }
  # Default Deny all other outbound (no internet access from data tier)

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-data-nacl"
  })
}
