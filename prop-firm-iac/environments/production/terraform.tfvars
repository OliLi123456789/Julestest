# environments/production/terraform.tfvars

aws_region = "<YOUR_PRODUCTION_REGION>" # Example: "us-west-2", replace with your target production region

# `environment_name` is defaulted to "production" in variables.tf, so not strictly needed here unless overriding.

# Example VPC configuration - these variables would need to be defined in variables.tf
# Values here would be for the PRODUCTION environment and might differ from staging
# (e.g., different CIDR blocks if needed, or same CIDR but in a different account/VPC).
# For production, you might use larger instance types, more ASG capacity, etc.,
# which would be controlled by variables set here or passed via CI/CD.

# vpc_cidr_block          = "10.100.0.0/16" # Potentially different CIDR for production
# public_subnet_cidrs   = ["10.100.1.0/24", "10.100.2.0/24", "10.100.3.0/24"] # Potentially more AZs/subnets for HA
# private_app_subnet_cidrs = ["10.100.10.0/24", "10.100.11.0/24", "10.100.12.0/24"]
# private_data_subnet_cidrs = ["10.100.20.0/24", "10.100.21.0/24", "10.100.22.0/24"]
# availability_zones    = ["us-west-2a", "us-west-2b", "us-west-2c"] # Ensure these match the region

# Production-specific values for other module variables will be added here.
# Ensure this file is in .gitignore if it contains sensitive default values,
# though actual sensitive values should ideally be passed via CI/CD variables for `terraform apply`.
# For non-sensitive, environment-specific configurations, this file is appropriate.
