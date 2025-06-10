# modules/timestream/variables.tf

variable "environment_name" {
  description = "Name of the environment (e.g., staging, production) for naming resources."
  type        = string
}

variable "common_tags" {
  description = "Common tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "database_name_suffix" {
  description = "Suffix for the Amazon Timestream database name. Will be prepended with environment_name."
  type        = string
  default     = "PropFirmMarketData" # Example: staging-PropFirmMarketData
}

variable "kms_key_id_for_database" {
  description = "Optional: The ARN of the KMS key to be used to encrypt the database. If not specified, uses an AWS owned KMS key."
  type        = string
  default     = null
}

# --- Table Configurations ---
# Using maps to define multiple tables with their specific settings

variable "tables_config" {
  description = "A map defining configurations for Timestream tables. Key is a logical table name (e.g., 'trades', 'quotes')."
  type = map(object({
    table_name                            = string # Actual table name in Timestream
    memory_store_retention_period_in_hours  = number
    magnetic_store_retention_period_in_days = number
    # Dimensions are defined by the data written, but listing expected primary dimensions here for clarity/documentation
    # This list is not directly used by aws_timestreamwrite_table resource for schema definition.
    # It could be used for generating IAM policies if very fine-grained access to dimensions were needed.
    expected_dimensions                 = list(string)
  }))
  default = {
    "trades" = {
      table_name                            = "Trades"
      memory_store_retention_period_in_hours  = 24 * 7  // 7 days
      magnetic_store_retention_period_in_days = 365 * 2 // 2 years
      expected_dimensions                   = ["ticker", "exchange", "size_dim", "trade_id_dim", "quality_flag"]
    },
    "quotes" = {
      table_name                            = "Quotes"
      memory_store_retention_period_in_hours  = 24 * 1  // 1 day
      magnetic_store_retention_period_in_days = 365 * 1 // 1 year
      expected_dimensions                   = ["ticker", "bid_exchange", "ask_exchange", "quality_flag"]
    },
    "aggregates" = { # This could be a base for Aggregates1Min, Aggregates1Hour etc.
      table_name                            = "Aggregates"
      memory_store_retention_period_in_hours  = 24 * 30 // 30 days
      magnetic_store_retention_period_in_days = 365 * 5 // 5 years
      expected_dimensions                   = ["ticker", "timeframe", "quality_flag"]
    }
  }
}
