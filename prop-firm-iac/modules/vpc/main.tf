# modules/vpc/main.tf

# --- VPC ---
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-vpc"
  })
}

# --- Internet Gateway ---
resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-igw"
  })
}

# --- Public Subnets ---
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true # Instances in public subnets get public IPs by default

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-public-subnet-${var.availability_zones[count.index]}"
    Tier = "Public"
  })
}

# --- Elastic IPs for NAT Gateways ---
resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? (var.single_nat_gateway ? 1 : length(var.public_subnet_cidrs)) : 0
  # 'domain = "vpc"' or just relying on association is the modern way.
  # Simply creating an EIP without other params makes it a VPC EIP.
  tags = merge(var.common_tags, {
    Name = var.single_nat_gateway ? "${var.environment_name}-nat-eip" : "${var.environment_name}-nat-eip-${var.availability_zones[count.index]}"
  })
}


# --- NAT Gateways ---
resource "aws_nat_gateway" "nat" {
  count           = var.enable_nat_gateway ? (var.single_nat_gateway ? 1 : length(var.public_subnet_cidrs)) : 0
  allocation_id   = aws_eip.nat[count.index].id
  subnet_id       = aws_subnet.public[count.index].id # Place NAT GW in a public subnet

  tags = merge(var.common_tags, {
    Name = var.single_nat_gateway ? "${var.environment_name}-nat-gw" : "${var.environment_name}-nat-gw-${var.availability_zones[count.index]}"
  })

  depends_on = [aws_internet_gateway.gw]
}

# --- Private Application Subnets ---
resource "aws_subnet" "private_app" {
  count             = length(var.private_app_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_app_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-app-subnet-${var.availability_zones[count.index]}"
    Tier = "PrivateApp"
  })
}

# --- Private Data Subnets ---
resource "aws_subnet" "private_data" {
  count             = length(var.private_data_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_data_subnet_cidrs[count.index]
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-data-subnet-${var.availability_zones[count.index]}"
    Tier = "PrivateData"
  })
}

# --- Public Route Table ---
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-public-rtb"
  })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- Private Route Tables (one per AZ for private_app subnets for potentially different NAT GWs) ---
resource "aws_route_table" "private_app" {
  count  = var.enable_nat_gateway ? length(var.private_app_subnet_cidrs) : 0
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[var.single_nat_gateway ? 0 : count.index].id
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-app-rtb-${var.availability_zones[count.index]}"
  })
}

resource "aws_route_table_association" "private_app" {
  count          = var.enable_nat_gateway ? length(aws_subnet.private_app) : 0
  subnet_id      = aws_subnet.private_app[count.index].id
  route_table_id = aws_route_table.private_app[count.index].id
}

# --- Private Route Tables (one per AZ for private_data subnets for potentially different NAT GWs) ---
# Often data subnets might not need NAT, or share the app tier's NAT.
# For this module, we'll provide NAT gateway access by default if enabled.
# Specific routes for VPC endpoints should be added separately if NAT GW access is fully disabled for data tier.
resource "aws_route_table" "private_data" {
  count  = var.enable_nat_gateway ? length(var.private_data_subnet_cidrs) : 0
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat[var.single_nat_gateway ? 0 : count.index].id
  }

  tags = merge(var.common_tags, {
    Name = "${var.environment_name}-private-data-rtb-${var.availability_zones[count.index]}"
  })
}

resource "aws_route_table_association" "private_data" {
  count          = var.enable_nat_gateway ? length(aws_subnet.private_data) : 0
  subnet_id      = aws_subnet.private_data[count.index].id
  route_table_id = aws_route_table.private_data[count.index].id
}

# If NAT gateway is disabled (var.enable_nat_gateway = false),
# the private_app_rtb and private_data_rtb resources will not be created (due to count = 0).
# In such a scenario, these subnets will only have routes to other resources within the VPC
# (e.g., VPC endpoints) if those routes are explicitly defined elsewhere (e.g., in a vpc_endpoint module
# or directly in the environment's main.tf). This module doesn't create those specific endpoint routes.
# The default is to give private subnets a path to the internet via NAT GW if enabled.
