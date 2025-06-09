# environments/staging/backend.tf

terraform {
  backend "s3" {
    bucket         = "prop-firm-terraform-state-<YOUR_AWS_ACCOUNT_ID>-<YOUR_REGION>" # REPLACE with your actual bucket name
    key            = "environments/staging/terraform.tfstate"
    region         = "<YOUR_REGION>"                                                 # REPLACE with your actual region
    dynamodb_table = "prop-firm-terraform-state-lock"                                # REPLACE with your actual DynamoDB table name
    encrypt        = true
  }
}
